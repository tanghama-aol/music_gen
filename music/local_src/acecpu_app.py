"""ACE-Step 1.5 XL (CPU) - Gradio frontend + CLI for ace-server GGUF inference"""

import os
import sys
import time
import json
import argparse
import base64
import tempfile
import subprocess
import shutil
import string
import random
import requests
import logging
import threading

from train_engine import (
    preprocess_audio,
    train_lora_generator,
    cancel_training,
    _training_cancel,
    get_trained_loras as _get_trained_loras_engine,
    MAX_TRAINING_TIME,
)

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable limits (edit here, not buried in code)
# ---------------------------------------------------------------------------

MAX_TOTAL_AUDIO = 1800       # seconds total across all uploaded files (30 min)
# MAX_TRAINING_TIME is imported from train_engine (single source of truth)
MAX_AUDIO_FILES = 50         # max number of training audio files per run

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

ACE_SERVER = os.environ.get("ACE_SERVER", "http://127.0.0.1:8085")
OUTPUT_DIR = os.environ.get("ACE_OUTPUT_DIR", "/app/outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Clean up old inference temp files (older than 1 hour) at startup
_CLEANUP_MAX_AGE = 3600  # seconds
try:
    _now = time.time()
    for _fname in os.listdir(OUTPUT_DIR):
        if _fname.lower().endswith((".wav", ".mp3")):
            _fpath = os.path.join(OUTPUT_DIR, _fname)
            try:
                if os.path.isfile(_fpath) and (_now - os.path.getmtime(_fpath)) > _CLEANUP_MAX_AGE:
                    os.remove(_fpath)
            except OSError:
                pass
except Exception:
    pass

ACE_CHECKPOINT_DIR = os.environ.get("ACE_CHECKPOINT_DIR", "/app/checkpoints")
ACE_SOURCE_DIR = "/app/ace-step-source"
ACE_HF_MODEL = "ACE-Step/Ace-Step1.5"
ADAPTER_DIR = os.environ.get("ACE_ADAPTER_DIR", "/app/adapters")
MODELS_DIR = os.environ.get("ACE_MODELS_DIR", "/app/models")

ACE_SERVER_BIN = "/app/ace-server"

# Detect if running on HF Space (ace-server available) vs locally (PyTorch only)
_is_space = os.path.isfile(ACE_SERVER_BIN) or os.environ.get("SPACE_ID") is not None
_training_lock = threading.Lock()

# HF repo for on-demand GGUF downloads
GGUF_HF_REPO = "Serveurperso/ACE-Step-1.5-GGUF"

# ---------------------------------------------------------------------------
# ace-server helpers
# ---------------------------------------------------------------------------

def _server_ok():
    try:
        return requests.get(f"{ACE_SERVER}/health", timeout=5).status_code == 200
    except Exception:
        return False


def _get_props():
    """Fetch server properties (models, adapters)."""
    try:
        r = requests.get(f"{ACE_SERVER}/props", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _poll_job(job_id, timeout=600, progress_cb=None, cancel_check=None):
    """Poll a job until done/error/timeout/cancelled. Returns (status, elapsed, data)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cancel_check and cancel_check():
            return "cancelled", time.time() - t0, None
        try:
            r = requests.get(f"{ACE_SERVER}/job", params={"id": job_id}, timeout=5)
            data = r.json()
            status = data.get("status", "unknown")
            if progress_cb:
                progress_cb(status, data)
            if status in ("done", "error"):
                return status, time.time() - t0, data
        except Exception:
            pass
        time.sleep(1)
    return "timeout", time.time() - t0, None


def _fetch_result(job_id, timeout=60):
    """Fetch result bytes/json for a completed job."""
    r = requests.get(
        f"{ACE_SERVER}/job",
        params={"id": job_id, "result": 1},
        timeout=timeout,
    )
    return r



def _caption_via_understand(audio_path, timeout=600, cancel_check=None):
    """Call ace-server /understand for a rich caption. Returns dict or None."""
    fname = os.path.basename(audio_path)
    try:
        with open(audio_path, "rb") as f:
            r = requests.post(
                f"{ACE_SERVER}/understand",
                files={"audio": (fname, f, "audio/mpeg")},
                timeout=30,
            )
        if r.status_code != 200:
            logger.warning("[Caption] %s: /understand %d: %s", fname, r.status_code, r.text[:200])
            return None
        job_id = r.json().get("id")
        if not job_id:
            return None
    except Exception as exc:
        logger.warning("[Caption] %s: /understand submit failed: %s", fname, exc)
        return None

    status, elapsed, poll_data = _poll_job(job_id, timeout=timeout, cancel_check=cancel_check)
    if status != "done":
        logger.warning("[Caption] %s: /understand -> %s (%.0fs)", fname, status, elapsed)
        return None

    # Fetch result — /understand returns multipart/mixed (JSON + latents)
    try:
        r = _fetch_result(job_id, timeout=120)
        if r.status_code != 200:
            logger.warning("[Caption] %s: result fetch HTTP %d", fname, r.status_code)
            return None

        content_type = r.headers.get("Content-Type", "")

        # multipart/mixed: extract JSON part (caption metadata)
        if "multipart" in content_type:
            boundary = None
            for part in content_type.split(";"):
                part = part.strip()
                if part.startswith("boundary="):
                    boundary = part.split("=", 1)[1].strip('"')
            if boundary:
                import re
                parts = r.content.split(f"--{boundary}".encode())
                for part in parts:
                    if b"application/json" in part:
                        json_start = part.find(b"{")
                        json_end = part.rfind(b"}") + 1
                        if json_start >= 0 and json_end > json_start:
                            data = json.loads(part[json_start:json_end])
                            if isinstance(data, dict) and data.get("caption"):
                                logger.info("[Caption] %s: got caption (%d chars)",
                                            fname, len(data["caption"]))
                                return data

        # Plain JSON fallback
        if r.text.strip():
            data = r.json()
            if isinstance(data, dict) and data.get("caption"):
                return data

    except Exception as exc:
        logger.warning("[Caption] %s: result parse failed: %s", fname, exc)

    logger.warning("[Caption] %s: no caption extracted from result", fname)
    return None


def _run_pipeline(caption, lyrics, bpm, duration, seed, steps, output_format,
                  adapter=None, lm_model=None, progress_cb=None):
    """Run full LM -> synth pipeline. Returns (audio_path, status_msg) or raises."""
    t0 = time.time()

    # -- Build LM request --
    req = {"caption": caption or "upbeat electronic dance music"}
    req["lyrics"] = lyrics if lyrics and lyrics.strip() else "[Instrumental]"

    try:
        if bpm and int(float(bpm)) > 0:
            req["bpm"] = int(float(bpm))
        if duration and float(duration) > 0:
            req["duration"] = min(float(duration), 300)
        if seed is not None and int(float(seed)) >= 0:
            req["seed"] = int(float(seed))
        if steps and int(float(steps)) > 0:
            req["inference_steps"] = int(float(steps))
    except (ValueError, TypeError):
        pass
    if adapter:
        req["adapter"] = adapter
    if lm_model:
        req["model"] = lm_model

    fmt = output_format if output_format in ("wav", "mp3") else "mp3"
    synth_fmt = "wav16" if fmt == "wav" else "mp3"
    suffix = f".{fmt}"

    # -- LM phase --
    if progress_cb:
        progress_cb("lm_submit", None)
    r = requests.post(f"{ACE_SERVER}/lm", json=req, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"LM submit failed: {r.status_code} {r.text}")
    lm_job_id = r.json().get("id")

    if progress_cb:
        progress_cb("lm_poll", {"job_id": lm_job_id})
    lm_status, lm_elapsed, _ = _poll_job(lm_job_id, timeout=900)
    if lm_status != "done":
        raise RuntimeError(f"LM {lm_status} after {lm_elapsed:.0f}s")

    # Fetch LM result
    r = _fetch_result(lm_job_id)
    lm_results = r.json()
    if not isinstance(lm_results, list) or len(lm_results) == 0:
        raise RuntimeError(f"LM returned no results: {lm_results}")
    synth_request = lm_results[0]

    # -- Synth phase --
    synth_request["output_format"] = synth_fmt
    if adapter:
        synth_request["adapter"] = adapter
        synth_request["synth_model"] = "acestep-v15-turbo-Q4_K_M.gguf"
    if progress_cb:
        progress_cb("synth_submit", None)
    r = requests.post(f"{ACE_SERVER}/synth", json=synth_request, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Synth submit failed: {r.status_code} {r.text}")
    synth_job_id = r.json().get("id")

    if progress_cb:
        progress_cb("synth_poll", {"job_id": synth_job_id})
    synth_status, synth_elapsed, _ = _poll_job(synth_job_id, timeout=600)
    if synth_status != "done":
        raise RuntimeError(f"Synth {synth_status} after {synth_elapsed:.0f}s")

    # Fetch audio
    if progress_cb:
        progress_cb("fetch", None)
    r = _fetch_result(synth_job_id, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Audio fetch failed: {r.status_code}")

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, dir=OUTPUT_DIR, delete=False)
    tmp.write(r.content)
    tmp.close()

    elapsed = time.time() - t0
    msg = f"Done in {elapsed:.0f}s | {duration}s audio, {steps} steps, {fmt}"
    return tmp.name, msg


# ---------------------------------------------------------------------------
# LM model scanning & on-demand download
# ---------------------------------------------------------------------------

DEFAULT_LM = "acestep-5Hz-lm-1.7B-Q8_0.gguf"

AVAILABLE_LM_MODELS = [
    "acestep-5Hz-lm-1.7B-Q8_0.gguf",
    "acestep-5Hz-lm-0.6B-Q8_0.gguf",
    "acestep-5Hz-lm-4B-Q5_K_M.gguf",
]

def _scan_lm_models():
    """Return LM model choices. Installed shown as-is, others need download."""
    installed = set()
    if os.path.isdir(MODELS_DIR):
        for f in os.listdir(MODELS_DIR):
            if "-lm-" in f and f.endswith(".gguf"):
                installed.add(f)
    choices = []
    for m in AVAILABLE_LM_MODELS:
        if m in installed:
            choices.append(m)
        else:
            choices.append(f"{m} [not installed]")
    return choices


def _download_lm_model(filename):
    """Download a GGUF LM model from HF if not already present."""
    dest = os.path.join(MODELS_DIR, filename)
    if os.path.isfile(dest):
        return dest
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(
            repo_id=GGUF_HF_REPO,
            filename=filename,
            local_dir=MODELS_DIR,
        )
        return path
    except Exception as exc:
        logger.error("Failed to download %s: %s", filename, exc)
        return None


# ---------------------------------------------------------------------------
# LoRA listing for UI dropdowns
# ---------------------------------------------------------------------------

def _list_lora_choices():
    """Return list of LoRA choices for dropdown, including 'None'."""
    choices = ["None (no LoRA)"]
    if os.path.isdir(ADAPTER_DIR):
        for d in os.listdir(ADAPTER_DIR):
            if os.path.isdir(os.path.join(ADAPTER_DIR, d)):
                choices.append(d)
    return choices


# ---------------------------------------------------------------------------
# ace-server stop/start helpers
# ---------------------------------------------------------------------------

_ace_proc = None

def _stop_ace_server():
    """Stop ace-server process."""
    global _ace_proc
    logger.info("[ace-server] Stopping...")
    if _ace_proc and _ace_proc.poll() is None:
        _ace_proc.terminate()
        try:
            _ace_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ace_proc.kill()
        _ace_proc = None
        logger.info("[ace-server] Stopped (tracked PID)")
    else:
        try:
            subprocess.run(["pkill", "ace-server"],
                           stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           timeout=10)
            logger.info("[ace-server] Stopped (pkill)")
        except Exception:
            pass
    time.sleep(1)


def _start_ace_server(max_retries: int = 3, retry_delay: float = 5.0):
    """Start ace-server in background and wait for health.

    Retries up to max_retries times with retry_delay seconds between attempts.
    """
    global _ace_proc
    for attempt in range(1, max_retries + 1):
        logger.info(
            "[ace-server] Starting (attempt %d/%d) with --adapters %s",
            attempt, max_retries, ADAPTER_DIR,
        )
        try:
            _ace_proc = subprocess.Popen(
                [ACE_SERVER_BIN, "--host", "127.0.0.1", "--port", "8085",
                 "--models", MODELS_DIR, "--adapters", ADAPTER_DIR, "--max-batch", "1"],
            )
        except Exception as exc:
            logger.error("[ace-server] Failed to start: %s", exc)
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue
            return False

        for _ in range(30):
            if _server_ok():
                logger.info("[ace-server] Healthy")
                return True
            time.sleep(2)

        logger.warning("[ace-server] Health check timeout on attempt %d/%d", attempt, max_retries)
        # Kill the failed process before retrying
        if _ace_proc and _ace_proc.poll() is None:
            _ace_proc.kill()
            try:
                _ace_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if attempt < max_retries:
            time.sleep(retry_delay)

    logger.error("[ace-server] Failed to start after %d attempts", max_retries)
    return False



# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

def cli_main():
    parser = argparse.ArgumentParser(
        description="ACE-Step 1.5 XL (CPU) - CLI inference via ace-server",
    )
    parser.add_argument("caption", nargs="?", default="upbeat electronic dance music",
                        help="Music description / caption")
    parser.add_argument("--lyrics", "-l", default="[Instrumental]",
                        help="Lyrics text (use '[Instrumental]' for no vocals)")
    parser.add_argument("--bpm", type=int, default=120, help="Beats per minute")
    parser.add_argument("--duration", "-d", type=float, default=10,
                        help="Duration in seconds (max 300)")
    parser.add_argument("--steps", "-s", type=int, default=8,
                        help="Inference steps (1-32)")
    parser.add_argument("--seed", type=int, default=-1,
                        help="Random seed (-1 for random)")
    parser.add_argument("--format", "-f", choices=["wav", "mp3"], default="wav",
                        help="Output audio format")
    parser.add_argument("--adapter", "-a", default=None,
                        help="LoRA adapter name")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file path (default: auto in outputs dir)")
    parser.add_argument("--server", default=None,
                        help="ace-server URL (default: http://127.0.0.1:8085)")

    args = parser.parse_args()

    if args.server:
        global ACE_SERVER
        ACE_SERVER = args.server

    if not _server_ok():
        print(f"ERROR: ace-server not reachable at {ACE_SERVER}", file=sys.stderr)
        sys.exit(1)

    seed = args.seed if args.seed >= 0 else None

    def cli_progress(phase, data):
        phases = {
            "lm_submit": "Submitting LM job...",
            "lm_poll": f"LM generating (job {data['job_id']})..." if data else "LM generating...",
            "synth_submit": "Submitting synth job...",
            "synth_poll": f"Synthesizing (job {data['job_id']})..." if data else "Synthesizing...",
            "fetch": "Fetching audio...",
        }
        msg = phases.get(phase, phase)
        print(f"  [{phase}] {msg}")

    print(f"ACE-Step CLI | caption: {args.caption}")
    print(f"  lyrics: {args.lyrics} | bpm: {args.bpm} | duration: {args.duration}s "
          f"| steps: {args.steps} | seed: {args.seed} | format: {args.format}")

    try:
        audio_path, status = _run_pipeline(
            caption=args.caption,
            lyrics=args.lyrics,
            bpm=args.bpm,
            duration=args.duration,
            seed=seed,
            steps=args.steps,
            output_format=args.format,
            adapter=args.adapter,
            progress_cb=cli_progress,
        )
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Move to requested output path if specified
    if args.output:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(out_dir, exist_ok=True)
        shutil.move(audio_path, args.output)
        audio_path = args.output

    print(f"  {status}")
    print(f"  Output: {audio_path}")


# ---------------------------------------------------------------------------
# Gradio UI mode
# ---------------------------------------------------------------------------

def gradio_main():
    import gradio as gr
    import gc

    # -- Persistent training log buffer (survives across yields) --
    _train_log_lines = []

    # -- Generate tab handler --
    def generate_music(caption, lyrics, bpm, duration, seed,
                       steps, lora_select, lm_model_select,
                       progress=gr.Progress(track_tqdm=True)):
        if not _training_lock.acquire(blocking=False):
            return None, "Training in progress. Inference unavailable until training completes. Press Cancel to stop training."
        _training_lock.release()
        if not _server_ok():
            return None, "ace-server not running. Check logs."

        if not lyrics or lyrics.strip() == "":
            lyrics = "[Instrumental]"

        actual_seed = None if seed is None or int(seed) < 0 else int(seed)
        adapter = None if lora_select == "None (no LoRA)" else lora_select
        lm_model_file = lm_model_select.replace(" [not installed]", "") if lm_model_select else None
        if lm_model_file and "[not installed]" in (lm_model_select or ""):
            _download_lm_model(lm_model_file)
        lm_model = lm_model_file

        progress_map = {
            "lm_submit": (0.05, "Submitting LM job..."),
            "lm_poll": (0.10, "LM generating..."),
            "synth_submit": (0.40, "Submitting synth job..."),
            "synth_poll": (0.50, "Synthesizing audio..."),
            "fetch": (0.90, "Fetching audio..."),
        }

        def gr_progress(phase, data):
            pct, desc = progress_map.get(phase, (0.5, phase))
            if data and "job_id" in data:
                desc += f" (job {data['job_id']})"
            progress(pct, desc=desc)

        try:
            audio_path, status = _run_pipeline(
                caption=caption,
                lyrics=lyrics,
                bpm=bpm,
                duration=duration,
                seed=actual_seed,
                steps=steps,
                output_format="mp3",
                adapter=adapter,
                lm_model=lm_model,
                progress_cb=gr_progress,
            )
            return audio_path, status
        except RuntimeError as e:
            return None, str(e)
        except Exception as e:
            return None, f"Unexpected error: {e}"

    # -- Server info helper --
    def get_server_status():
        if not _server_ok():
            return "ace-server: OFFLINE"
        props = _get_props()
        lines = ["ace-server: ONLINE"]
        if props:
            lines.append(json.dumps(props, indent=2))
        return "\n".join(lines)

    # -- Training generator (direct integration, no subprocess) --
    def train_lora_ui(audio_files, lora_name, epochs, lr, rank, use_lm_caption):
        """Generator that yields (train_log, train_btn_update, cancel_btn_update)."""
        import gc as _gc

        _train_log_lines.clear()
        train_start = time.time()

        def _log(msg):
            elapsed = int(time.time() - train_start)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            ts = f"+{h}:{m:02d}:{s:02d}" if h else f"+{m:02d}:{s:02d}"
            line = f"[{ts}] {msg}"
            _train_log_lines.append(line)
            logger.info(msg)
            if len(_train_log_lines) > 2000:
                _train_log_lines[:] = _train_log_lines[-1000:]

        def _log_text():
            return "\n".join(_train_log_lines)

        # -- Validation --
        if not audio_files:
            _log("[FAIL] No audio files uploaded.")
            yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File()
            return

        if len(audio_files) > MAX_AUDIO_FILES:
            _log(f"[FAIL] Too many files ({len(audio_files)}). Max: {MAX_AUDIO_FILES}")
            yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File()
            return

        lora_name = (lora_name or "").strip() or "my-lora"
        lora_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in lora_name)

        epochs = max(1, min(int(epochs), 1000))
        lr = float(lr)
        rank = max(1, min(int(rank), 128))

        work_dir = os.path.join(OUTPUT_DIR, "train_workspace", lora_name)
        os.makedirs(work_dir, exist_ok=True)
        audio_dir = os.path.join(work_dir, "audio_input")
        if os.path.exists(audio_dir):
            shutil.rmtree(audio_dir)
        os.makedirs(audio_dir)
        adapter_out = os.path.join(ADAPTER_DIR, lora_name)
        os.makedirs(adapter_out, exist_ok=True)

        # Copy uploaded audio files + check total duration
        _log(f"[INFO] Preparing {len(audio_files)} audio files...")
        yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

        import librosa as _lr
        total_dur = 0.0
        accepted = 0
        skipped_names = []
        truncated_names = []
        for f in audio_files:
            src = f.name if hasattr(f, "name") else str(f)
            fname = os.path.basename(src)
            # .txt/.json sidecars: copy as caption files, skip duration check
            if fname.lower().endswith((".txt", ".json")):
                shutil.copy2(src, os.path.join(audio_dir, fname))
                continue
            try:
                dur = _lr.get_duration(path=src)
            except Exception:
                dur = 0.0
            if dur <= 0:
                skipped_names.append(f"{fname} (invalid/empty)")
                continue
            remaining = MAX_TOTAL_AUDIO - total_dur
            if remaining <= 0:
                skipped_names.append(fname)
                continue
            if dur > remaining:
                # Truncate this file to fit
                import soundfile as _sf
                y, sr = _lr.load(src, sr=None, mono=False)
                max_samples = int(remaining * sr)
                if y.ndim == 1:
                    y = y[:max_samples]
                else:
                    y = y[:, :max_samples]
                dst = os.path.join(audio_dir, fname)
                _sf.write(dst, y.T if y.ndim > 1 else y, sr)
                truncated_names.append(f"{fname} ({dur:.0f}s -> {remaining:.0f}s)")
                total_dur += remaining
                accepted += 1
            else:
                shutil.copy2(src, os.path.join(audio_dir, fname))
                total_dur += dur
                accepted += 1

        if truncated_names:
            _log(f"[WARN] Truncated: {', '.join(truncated_names)}")
        if skipped_names:
            _log(f"[WARN] Skipped (over {MAX_TOTAL_AUDIO/60:.0f} min cap): {', '.join(skipped_names)}")
        _log(f"[INFO] Total audio: {total_dur:.0f}s ({total_dur/60:.1f} min), {accepted} files")

        _log(f"[INFO] LoRA: '{lora_name}' | Files: {len(audio_files)} | "
             f"Epochs: {epochs} | LR: {lr} | Rank: {rank}")
        yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

        # Caption audio files without user-provided sidecars
        audio_to_caption = []
        for audio_fname in sorted(os.listdir(audio_dir)):
            full_path = os.path.join(audio_dir, audio_fname)
            if not os.path.isfile(full_path):
                continue
            ext = audio_fname.lower().rsplit(".", 1)[-1] if "." in audio_fname else ""
            if ext in ("json", "txt"):
                continue
            stem = audio_fname.rsplit(".", 1)[0] if "." in audio_fname else audio_fname
            sidecar_json = os.path.join(audio_dir, stem + ".json")
            sidecar_txt = os.path.join(audio_dir, stem + ".txt")
            if os.path.isfile(sidecar_json) or os.path.isfile(sidecar_txt):
                _log(f"  {audio_fname}: using caption file")
                continue
            audio_to_caption.append((audio_fname, full_path, sidecar_json))
        yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

        if audio_to_caption and use_lm_caption and _server_ok():
            # --- Mode: GGUF LM captioning (best quality, 5h timeout per file) ---
            LM_TIMEOUT = 18000  # 5h per file
            est_total = int(total_dur * 7 + len(audio_to_caption) * 600)
            if est_total > LM_TIMEOUT:
                _log(f"[WARN] Estimated {est_total // 60} min exceeds 5h, switching to fast captioning")
                use_lm_caption = False
                yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
            else:
                _log(f"[INFO] LM captioning {len(audio_to_caption)} files (5h timeout per file)...")
                yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
                for audio_fname, full_path, sidecar_json in audio_to_caption:
                    if _training_cancel.is_set():
                        break
                    _log(f"  {audio_fname}: LM captioning...")
                    yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
                    caption_data = _caption_via_understand(
                        full_path, timeout=LM_TIMEOUT,
                        cancel_check=lambda: _training_cancel.is_set(),
                    )
                    if caption_data:
                        bpm_s = caption_data.get("bpm", "?")
                        key_s = caption_data.get("keyscale", caption_data.get("key", "?"))
                        _log(f"  {audio_fname}: OK (BPM={bpm_s}, key={key_s})")
                        with open(sidecar_json, "w") as cj:
                            json.dump(caption_data, cj)
                    else:
                        _log(f"  {audio_fname}: LM failed")
                    yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

        if audio_to_caption and not use_lm_caption:
            # --- Mode: Fast captioning (CLAP + Whisper + librosa) ---
            _log(f"[INFO] Fast captioning {len(audio_to_caption)} files "
                 f"(CLAP tags + lyrics + BPM)...")
            yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
            try:
                from caption_fast import caption_audio, unload_caption_models
                for audio_fname, full_path, sidecar_json in audio_to_caption:
                    if _training_cancel.is_set():
                        break
                    _log(f"  {audio_fname}: analyzing...")
                    yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
                    try:
                        result = caption_audio(full_path)
                        _log(f"  {audio_fname}: {result.get('caption', '')[:60]}")
                        if result.get("lyrics") and result["lyrics"] != "[Instrumental]":
                            _log(f"  {audio_fname}: lyrics extracted ({len(result['lyrics'])} chars)")
                        with open(sidecar_json, "w") as cj:
                            json.dump(result, cj)
                    except Exception as cap_exc:
                        _log(f"  {audio_fname}: fast caption failed: {cap_exc}")
                    yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
                unload_caption_models()
                _gc.collect()
            except ImportError:
                _log("[WARN] Fast captioning not available, using librosa fallback")
                for audio_fname, full_path, sidecar_json in audio_to_caption:
                    try:
                        y_cap, sr_cap = _lr.load(full_path, sr=None, mono=True)
                        tempo_arr, _ = _lr.beat.beat_track(y=y_cap, sr=sr_cap)
                        bpm_val = int(round(float(
                            tempo_arr.item() if hasattr(tempo_arr, 'item') else tempo_arr)))
                        fallback = {"caption": audio_fname.rsplit(".", 1)[0],
                                    "bpm": str(bpm_val), "key": "", "signature": "4/4",
                                    "lyrics": "[Instrumental]"}
                        with open(sidecar_json, "w") as cj:
                            json.dump(fallback, cj)
                        _log(f"  {audio_fname}: librosa BPM={bpm_val}")
                    except Exception as exc:
                        _log(f"  {audio_fname}: failed: {exc}")
                yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

        if _training_cancel.is_set():
            _training_cancel.clear()
            _log("[CANCELLED] Stopped")
            yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File()
            shutil.rmtree(work_dir, ignore_errors=True)
            return

        # Stop ace-server before training (frees memory)
        _training_lock.acquire()
        _log("[INFO] Stopping ace-server for training...")
        yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
        _stop_ace_server()
        _gc.collect()

        _cleanup_done = False
        try:
            # -- Phase 1: Preprocessing (runs in thread for live progress) --
            preprocessed_dir = os.path.join(work_dir, "preprocessed_tensors")
            _preprocess_log_len = len(_train_log_lines)

            def preprocess_progress(current, total, desc):
                _log(f"  {desc} ({current}/{total})")

            _preprocess_result = [None]
            _preprocess_error = [None]

            def _run_preprocess():
                try:
                    _preprocess_result[0] = preprocess_audio(
                        audio_dir=audio_dir,
                        output_dir=preprocessed_dir,
                        checkpoint_dir=ACE_CHECKPOINT_DIR,
                        device="cpu",
                        variant="turbo",
                        max_duration=float(MAX_TOTAL_AUDIO),
                        progress_callback=preprocess_progress,
                        cancel_check=lambda: _training_cancel.is_set(),
                    )
                except Exception as exc:
                    _preprocess_error[0] = exc

            _log("[Step 1/2] Encoding audio → training data (VAE + text encoder)...")
            yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

            t = threading.Thread(target=_run_preprocess, daemon=True)
            t.start()
            while t.is_alive():
                t.join(timeout=3)
                if _training_cancel.is_set():
                    _training_cancel.clear()
                    _log("[CANCELLED] Stopped during preprocessing")
                    yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File()
                    return
                if len(_train_log_lines) > _preprocess_log_len:
                    _preprocess_log_len = len(_train_log_lines)
                    yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

            if _preprocess_error[0]:
                raise _preprocess_error[0]
            result = _preprocess_result[0]

            processed = result.get("processed", 0)
            failed = result.get("failed", 0)
            total = result.get("total", 0)
            _log(f"[OK] Preprocessed: {processed}/{total} files (failed: {failed})")
            yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

            if processed == 0:
                _log("[FAIL] No files preprocessed successfully. Cannot train.")
                yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File()
                return

            _gc.collect()

            # -- Phase 2: Training (random 60s crops for speed + augmentation) --
            _log("[Step 2/2] Training LoRA...")
            yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

            for msg in train_lora_generator(
                dataset_dir=preprocessed_dir,
                output_dir=adapter_out,
                checkpoint_dir=ACE_CHECKPOINT_DIR,
                epochs=epochs,
                lr=lr,
                rank=rank,
                alpha=rank * 2,
                dropout=0.0,
                batch_size=1,
                gradient_accumulation_steps=4,
                warmup_steps=100,
                weight_decay=0.01,
                max_grad_norm=1.0,
                save_every_n_epochs=0,
                seed=42,
                variant="turbo",
                device="cpu",
                chunk_duration=60,
                log_every=5,
            ):
                elapsed = time.time() - train_start
                if elapsed > MAX_TRAINING_TIME:
                    _log(f"[WARN] Training timed out after {int(elapsed)}s")
                    cancel_training()
                    break

                _log(msg)
                yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

                if msg.strip() == "[DONE]":
                    break

            _log(f"[INFO] Total time: {time.time() - train_start:.0f}s")
            yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()

        except GeneratorExit:
            _training_cancel.set()
            logger.info("Generator closed by Gradio, cleaning up")
            _cleanup_done = True
            _training_lock.release()
            _gc.collect()
            _start_ace_server()
            shutil.rmtree(work_dir, ignore_errors=True)
            return

        except Exception as exc:
            _log(f"[FAIL] Training error: {exc}")
            import traceback
            _log(traceback.format_exc())
            yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File()

        finally:
            if not _cleanup_done:
                _training_lock.release()
                _log("[INFO] Restarting ace-server...")
                yield _log_text(), gr.Button(visible=False), gr.Button(visible=True), gr.File()
                _gc.collect()
                ok = _start_ace_server()
                if ok:
                    _log("[OK] ace-server restarted successfully")
                else:
                    _log("[WARN] ace-server may not have restarted -- check logs")
                adapter_safetensors = os.path.join(adapter_out, "adapter_model.safetensors")
                if os.path.isfile(adapter_safetensors):
                    import zipfile
                    tmp_zip = tempfile.NamedTemporaryFile(
                        suffix=".zip",
                        prefix=f"{lora_name}_",
                        delete=False,
                    )
                    tmp_zip.close()
                    with zipfile.ZipFile(tmp_zip.name, "w", zipfile.ZIP_DEFLATED) as zf:
                        zf.write(adapter_safetensors, f"{lora_name}/adapter_model.safetensors")
                        adapter_config = os.path.join(adapter_out, "adapter_config.json")
                        if os.path.isfile(adapter_config):
                            zf.write(adapter_config, f"{lora_name}/adapter_config.json")
                        # Include generated captions if they exist
                        caption_count = 0
                        if os.path.isdir(audio_dir):
                            for cf in sorted(os.listdir(audio_dir)):
                                if cf.endswith(".json"):
                                    zf.write(os.path.join(audio_dir, cf),
                                             f"{lora_name}/captions/{cf}")
                                    caption_count += 1
                    _log(f"[OK] LoRA saved: {lora_name}" +
                         (f" ({caption_count} captions included)" if caption_count else ""))
                    yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File(value=tmp_zip.name, visible=True)
                else:
                    yield _log_text(), gr.Button(visible=True), gr.Button(visible=False), gr.File()
                shutil.rmtree(work_dir, ignore_errors=True)

    # -- Cancel handler --
    def _on_cancel():
        cancel_training()
        logger.info("Cancel requested by user")
        return "Cancelling..."

    # -- Build LM model choices --
    def _lm_model_choices():
        return _scan_lm_models()

    # -- Build UI --
    CSS = """
    .compact-row { gap: 8px !important; }
    .status-box textarea { font-family: monospace; font-size: 13px; overflow-y: auto !important; }
    """

    with gr.Blocks(title="ACE-Step 1.5 XL (CPU)") as demo:

        with gr.Tabs():
            # ============================================================
            # Tab 1: Generate Music
            # ============================================================
            with gr.Tab("Generate Music"):
                gr.Markdown("**[ACE-Step 1.5 XL](https://github.com/ace-step/ACE-Step-1.5)** GGUF Q4_K_M via [acestep.cpp](https://github.com/ServeurpersoCom/acestep.cpp) | ~5 min for 10s audio")
                with gr.Row(elem_classes="compact-row"):
                    with gr.Column(scale=3):
                        audio_out = gr.Audio(label="Output", type="filepath")
                        status = gr.Textbox(
                            label="Status",
                            interactive=False,
                            lines=1,
                            elem_classes="status-box",
                        )
                        caption = gr.Textbox(
                            label="Music Description",
                            lines=2,
                            value="upbeat electronic dance music, energetic synth leads",
                        )
                        lyrics = gr.Textbox(
                            label="Lyrics",
                            lines=3,
                            value="[Instrumental]",
                            placeholder="Enter lyrics here, or leave empty for instrumental (no vocals)",
                        )
                    with gr.Column(scale=2):
                        gen_btn = gr.Button("Generate Music", variant="primary")
                        with gr.Row(elem_classes="compact-row"):
                            bpm = gr.Number(label="BPM", value=120, minimum=0, maximum=300)
                            seed = gr.Number(label="Seed (-1=random)", value=-1)
                        with gr.Row(elem_classes="compact-row"):
                            duration = gr.Slider(
                                label="Duration (s)", minimum=10, maximum=120,
                                value=10, step=5,
                            )
                            steps = gr.Slider(
                                label="Steps (8 for turbo)", minimum=1, maximum=32,
                                value=8, step=1, interactive=False,
                            )
                        with gr.Row(elem_classes="compact-row"):
                            lora_select = gr.Dropdown(
                                label="LoRA", choices=_list_lora_choices(),
                                value="None (no LoRA)",
                                allow_custom_value=True,
                            )
                            lm_model_select = gr.Dropdown(
                                label="LM Model", choices=_lm_model_choices(),
                                value=DEFAULT_LM,
                            )

                gen_btn.click(
                    fn=generate_music,
                    inputs=[caption, lyrics, bpm, duration,
                            seed, steps, lora_select, lm_model_select],
                    outputs=[audio_out, status],
                    api_name="generate",
                )

            # ============================================================
            # Tab 2: Train LoRA
            # ============================================================
            with gr.Tab("Train LoRA"):
                gr.Markdown("LoRA training ported from [Side-Step](https://github.com/koda-dernet/Side-Step) | Model: [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) | ~8h for 3 files @ 200 epochs")
                with gr.Row(elem_classes="compact-row"):
                    with gr.Column(scale=3):
                        train_log = gr.Textbox(
                            label="Training Log",
                            interactive=False,
                            lines=12,
                            max_lines=50,
                            autoscroll=True,
                            elem_classes="status-box",
                        )
                        train_output_file = gr.File(label="Trained LoRA (download)", visible=False)
                        train_audio = gr.File(
                            label="Training Audio — max 30 min total, ~2 min/epoch on CPU (optional caption .txt)",
                            file_count="multiple",
                            file_types=["audio", ".txt", ".json"],
                            height=120,
                        )
                    with gr.Column(scale=2):
                        with gr.Row(elem_classes="compact-row"):
                            train_btn = gr.Button("Train", variant="primary", scale=2)
                            cancel_btn = gr.Button("Cancel Training", variant="stop", visible=False, scale=1)
                        lora_name = gr.Textbox(label="LoRA Name", value="my-lora")
                        train_epochs = gr.Slider(
                            label="Epochs (200 recommended ~6h on CPU, best 500)",
                            minimum=1, maximum=1000,
                            value=200, step=1,
                        )
                        train_lr = gr.Number(label="Learning Rate", value=3e-4)
                        train_rank = gr.Slider(
                            label="Rank (r)", minimum=1, maximum=128,
                            value=16, step=1,
                        )
                        use_lm_caption = gr.Checkbox(
                            label="Use LM captioning (best quality, ~30 min/file)",
                            value=False,
                        )

                # Button swap on click (separate handler, like rvc-beatrice)
                # This fires immediately so user sees Cancel even if training
                # queues behind concurrency_limit=1
                train_btn.click(
                    lambda: (gr.Button(visible=False), gr.Button(visible=True)),
                    outputs=[train_btn, cancel_btn],
                )

                # Training generator -- yields (log, train_btn, cancel_btn, output_file)
                train_event = train_btn.click(
                    train_lora_ui,
                    inputs=[train_audio, lora_name, train_epochs, train_lr, train_rank, use_lm_caption],
                    outputs=[train_log, train_btn, cancel_btn, train_output_file],
                    api_name="train_lora",
                    concurrency_limit=1,
                )

                # After training completes, restore buttons and refresh LoRA dropdown
                # This ensures cleanup even if the user navigated away
                def _post_training():
                    return (
                        gr.Button(visible=True),
                        gr.Button(visible=False),
                        gr.Dropdown(choices=_list_lora_choices()),
                    )

                train_event.then(
                    _post_training,
                    outputs=[train_btn, cancel_btn, lora_select],
                )

                # Cancel: set the flag, update status
                cancel_btn.click(
                    _on_cancel,
                    outputs=[train_log],
                )

        demo.launch(
            server_name="0.0.0.0",
            server_port=7860,
            mcp_server=True,
            css=CSS,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # If any CLI arguments besides the script name, run CLI mode
    # (Gradio sets no extra args; start.sh calls `python3 /app/app.py`)
    if len(sys.argv) > 1:
        cli_main()
    else:
        gradio_main()
