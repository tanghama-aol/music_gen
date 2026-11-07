#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按《音乐.md》调用音乐生成大模型，产出可直接入游戏的外部音频包。

模型接口（免注册、免密钥）：
    Hugging Face 官方 ACE-Step Space 的 Gradio 推理接口
    https://ace-step-ace-step.hf.space/gradio_api/call/__call__
    这是 ACE-Step v1 3.5B 音乐生成大模型的公开推理端点，匿名可用。
    *.hf.space 默认直连即可；huggingface.co 主站直连会 502（只查 Space 状态时才需要）。
    注意：本机 127.0.0.1:17890 代理的出口 IP 已耗尽 ZeroGPU 匿名配额，
    走该代理会立刻 `event: error / data: null`。如确需代理请用 MUSIC_PROXY 指定。

流程（当前生产链路见 gen_music_segments.py，本文件提供公共函数与旧路线 A 客户端）：
    1. 对每个片段编号 i，用【同一 seed + 同一 BPM + 同一时长】分别提交 calm / fight 的 caption
       —— 两层共享结构骨架，游戏里同时播放、平滑切音量才不会变成两首歌
    2. 后处理：44.1kHz 立体声 → 片段等功率交叉淡化 → 去头尾静音 → 无缝循环交叉淡化
       → 峰值整形 + -16 LUFS / 峰值 <= -1 dBFS → ogg Vorbis
    3. 写 manifest.json（calm/fight 的 loop 点完全相同）、prompts.md、preview.html

注：路线 A（本文件的 ZeroGPU 客户端）在匿名 ZeroGPU 配额耗尽后已不可用；
    最终 10 首全部由 gen_music_segments.py 走 CPU ACE-Step Space 生成。

用法：
    python gen_music_api.py --only 1              # 只做第 1 首（默认）
    python gen_music_api.py --all --skip-existing # 10 首全做，断点续跑
    python gen_music_api.py --only 3 --duration 90
    python gen_music_api.py --prompts-only        # 只刷新提示词与试听页
    python gen_music_api.py --only 1 --vocals     # 交战层加女声高音衬腔
    python gen_music_api.py --all --skip-existing --retries 5 --retry-wait 300
                                                  # ZeroGPU 配额恢复后补齐

ZeroGPU 匿名配额耗尽时服务端会在 2 秒内回 `error: null`，用较大的 --retry-wait 等恢复，
详见 README.md 第 5 节。切火山引擎 GenBGM 的中文提示词与签名说明见 README.md 第 6 节
（需你本人实名开通并配 AK/SK，本脚本不代注册、不代付费）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

SR = 44100
HERE = Path(__file__).resolve().parent
ASSETS = HERE / "game" / "public" / "assets"
MUSIC_DIR = ASSETS / "music"
TMP = HERE / "tmp"
SPACE = "https://ace-step-ace-step.hf.space"
CALL_URL = SPACE + "/gradio_api/call/__call__"
UPLOAD_URL = SPACE + "/gradio_api/upload"
# *.hf.space 可直连；17890 那个代理的出口 IP 已被 ZeroGPU 匿名配额拉黑，
# 走它会立刻返回 `event: error / data: null`。默认直连，需要时可用 MUSIC_PROXY 覆盖。
PROXY = os.environ.get("MUSIC_PROXY", "")

# ---------------------------------------------------------------------------
# 10 首风格：完全对应 音乐.md 第一节表格 + 第三节提示词
# ---------------------------------------------------------------------------
STYLES = [
    dict(no=1, slug="xipiliushui", name="西皮流水", opera="京剧", root=74, key="D 徵调",
         scale=[0, 2, 5, 7, 9], bpm=98, fight_bpm=132,
         lead="京胡 / 京胡", pluck="琵琶", perc="板鼓、大锣、小锣、钹（急急风）",
         cn="京剧西皮流水过门，京胡领奏，板鼓与大锣小锣点子紧密，节奏明快，D 徵调，带戏曲锣鼓经「急急风」气质",
         en="Chinese Peking opera xipi liushui, jinghu fiddle lead, pipa plucked strings, bangu drum, daluo and xiaoluo gongs, D zhi pentatonic mode"),
    dict(no=2, slug="qinqiang", name="秦腔苦音", opera="秦腔", root=69, key="A 苦音",
         scale=[0, 2, 4, 6, 7, 9, 10], bpm=80, fight_bpm=118,
         lead="板胡 / 唢呐", pluck="三弦", perc="大鼓、大锣、梆子",
         cn="秦腔苦音，板胡高亢苍凉领奏，唢呐助阵，大鼓与大锣沉重有力，节奏如黄土高原上的呐喊，A 调带升四降七的苦音色彩",
         en="Chinese Qinqiang opera kuyin mode, banhu fiddle lead, suona, heavy Chinese bass drum and big gong, A kuyin scale with raised fourth and flat seventh"),
    dict(no=3, slug="huagu", name="花鼓小调", opera="花鼓戏", root=71, key="B 宫五声",
         scale=[0, 2, 4, 7, 9], bpm=106, fight_bpm=138,
         lead="竹笛 / 唢呐", pluck="三弦", perc="小锣、木鱼（带摇摆）",
         cn="湖南花鼓戏小调，欢快俏皮，竹笛与唢呐问答，小锣木鱼点缀，带轻微摇摆的节奏，B 宫五声调",
         en="Chinese Huagu opera folk tune, dizi bamboo flute and suona call and response, small gong and woodblock, swung rhythm, B gong pentatonic"),
    dict(no=4, slug="huangmei", name="黄梅采茶", opera="黄梅戏", root=67, key="G 大调七声",
         scale=[0, 2, 4, 5, 7, 9, 11], bpm=78, fight_bpm=108,
         lead="二胡 / 竹笛", pluck="古筝", perc="板鼓、小锣",
         cn="安徽黄梅戏，二胡抒情领奏，竹笛和古筝伴奏，节奏舒缓委婉，如《打猪草》般清新，G 大调七声音阶",
         en="Chinese Huangmei opera, erhu lyrical lead, dizi flute and guzheng zither accompaniment, fresh and gentle, G major heptatonic"),
    dict(no=5, slug="chuanjiang", name="川江号子", opera="四川民谣", root=67, key="G 宫五声",
         scale=[0, 2, 4, 7, 9], bpm=94, fight_bpm=126,
         lead="竹笛 / 唢呐", pluck="三弦", perc="大鼓、梆子（明显摇摆）",
         cn="四川民谣，竹笛与三弦弹拨，节奏带明显摇摆，川江号子般的呼应感，轻松诙谐，G 宫五声调",
         en="Sichuan Chuanjiang haozi folk work song, dizi flute and sanxian lute, call and response, strongly swung rhythm, G gong pentatonic"),
    dict(no=6, slug="dongting", name="洞庭渔歌", opera="湖南民谣", root=64, key="E 徵调",
         scale=[0, 2, 5, 7, 9], bpm=70, fight_bpm=104,
         lead="二胡 / 唢呐", pluck="古筝", perc="大鼓、大锣（沉稳）",
         cn="湖南民谣，如《浏阳河》般悠长宽广，二胡与古筝，徵调，鼓点沉稳，带江水般流动的分解和弦，E 徵调",
         en="Hunan Dongting fishing folk song, broad and flowing like Liuyang River, erhu and guzheng arpeggios, E zhi pentatonic, steady drum"),
    dict(no=7, slug="minnan", name="闽南采茶", opera="福建民谣", root=69, key="A 羽调",
         scale=[0, 3, 5, 7, 10], bpm=82, fight_bpm=114,
         lead="竹笛 / 二胡", pluck="琵琶", perc="木鱼、小锣（灵动）",
         cn="福建闽南民谣，琵琶轮指与竹笛，如《采茶舞曲》般灵动，羽调，木鱼与小锣轻点节奏，A 羽调",
         en="Fujian Minnan tea-picking folk tune, pipa tremolo and dizi flute, agile, A yu pentatonic, woodblock and small gong"),
    dict(no=8, slug="xintianyou", name="信天游", opera="陕北", root=62, key="D 羽调",
         scale=[0, 3, 5, 7, 10], bpm=62, fight_bpm=100,
         lead="唢呐 / 板胡", pluck="三弦", perc="大鼓、大锣（极简、大跳长音）",
         cn="陕北信天游，唢呐低吟高亢的长音，音域宽、大跳，节奏自由舒展，如黄土高原上的呼喊，D 羽调，鼓点极简",
         en="Northern Shaanxi Xintianyou folk song, suona long soaring notes with wide leaps, free expansive rhythm, D yu pentatonic, minimal drum"),
    dict(no=9, slug="jiangnan", name="江南小调", opera="江南", root=74, key="D 宫五声",
         scale=[0, 2, 4, 7, 9], bpm=76, fight_bpm=108,
         lead="竹笛 / 二胡", pluck="古筝", perc="梆子、小锣（轻盈）",
         cn="江南丝竹小调，如《茉莉花》般柔美，竹笛和古筝琵琶，水乡的轻盈与烟雨，D 宫五声调，节奏舒缓",
         en="Jiangnan sizhu silk and bamboo folk tune, dizi flute, guzheng and pipa, soft like Jasmine Flower, D gong pentatonic"),
    dict(no=10, slug="errenzhuan", name="二人转", opera="东北", root=69, key="A 宫五声",
         scale=[0, 2, 4, 7, 9], bpm=116, fight_bpm=146,
         lead="唢呐 / 唢呐", pluck="三弦", perc="大鼓、钹（咚恰两拍子）",
         cn="东北二人转，唢呐与板胡对答，欢快泼辣，节奏强烈的「咚恰」两拍子，手绢翻飞般的热闹，A 宫五声调",
         en="Northeast Chinese Errenzhuan folk duet, suona and banhu call and response, lively, strong dong-qia two-beat rhythm, A gong pentatonic"),
]

CALM_SUFFIX = (
    "slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, "
    "soft sustained strings and solo melodic instrument, absolutely NO drums, "
    "NO percussion, NO gongs, NO rhythmic hits, quiet and floating, "
    "calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects")
FIGHT_SUFFIX = (
    "tense urgent and threatening, prominent heavy Chinese war drums, "
    "loud bangu drum and deep low drum pounding on every beat, "
    "dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, "
    "relentless driving battle rhythm, aggressive martial percussion, "
    "drums and percussion are the dominant foreground layer, "
    "same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects")
COMMON = ("game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, "
          "instrumental, no lyrics, no vocals, no ambience SFX, no field recording, "
          "steady tempo, no tempo change")

# 火山引擎 GenBGM 只吃中文，另存一份中文提示词
CN_CALM = ("，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，"
           "完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，"
           "安静飘逸，可无缝循环，无淡入淡出，不要环境音效")
CN_FIGHT = ("，紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，"
            "锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，"
            "同调同小节数，可无缝循环，无淡入淡出，不要环境音效")

# 风格描述里本来就写了锣鼓，平静层要把这部分剔掉，否则模型照样给你加鼓
PERC_WORDS = ("drum", "gong", "percussion", "woodblock", "cymbal", "bangu",
              "daluo", "xiaoluo", "bangzi", "beat", "rhythm", "steady drum")


def strip_percussion(en: str) -> str:
    parts = [p for p in en.split(", ")
             if not any(w in p.lower() for w in PERC_WORDS)]
    return ", ".join(parts) or en


# 中文风格描述同样会带锣鼓，平静层按分句整句剔除（只用于 prompts.md / 火山引擎）
CN_PERC_WORDS = ("鼓", "锣", "钹", "梆子", "木鱼", "点子", "打击乐", "咚恰")


def strip_percussion_cn(cn: str) -> str:
    parts = [p for p in cn.split("，")
             if not any(w in p for w in CN_PERC_WORDS)]
    return "，".join(parts) or cn


def prompt_of(st: dict, layer: str, cn: bool = False) -> str:
    if cn:
        desc = strip_percussion_cn(st["cn"]) if layer == "calm" else st["cn"]
        head = (f"{desc}。游戏配乐BGM，{st['key']}，约 {st['bpm']} BPM，"
                f"主奏{st['lead']}，弹拨{st['pluck']}，纯器乐无人声")
        if layer == "fight":
            head += f"，打击乐{st['perc']}"
        return head + (CN_CALM if layer == "calm" else CN_FIGHT)
    base = (strip_percussion(st["en"]) if layer == "calm" else st["en"])
    instr = f"{st['lead']}, {st['pluck']}"
    if layer == "fight":
        instr += f", {st['perc']}"
    return (f"{base}, {st['key']}, {st['bpm']} BPM, {instr}, {COMMON}, "
            f"{CALM_SUFFIX if layer == 'calm' else FIGHT_SUFFIX}")


# ---------------------------------------------------------------------------
# HTTP / Gradio 客户端（stdlib，无额外依赖）
# ---------------------------------------------------------------------------
def make_opener(proxies=None):
    if proxies is None:
        proxies = {"http": PROXY, "https": PROXY} if PROXY else {}
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))


# ZeroGPU 匿名配额按出口 IP 计算，三条路径各自独立且轮流恢复。
# 某条路径返回 `event: error / data: null` 就立刻切到下一条，不必干等。
PATHS = [
    ("17890", {"http": "http://127.0.0.1:17890", "https": "http://127.0.0.1:17890"}),
    ("direct", {}),
    ("62893", {"http": "http://127.0.0.1:62893", "https": "http://127.0.0.1:62893"}),
]
OPENER = None
_path_idx = 0


def set_path(i: int):
    global _path_idx, OPENER
    _path_idx = i % len(PATHS)
    OPENER = make_opener(PATHS[_path_idx][1])
    print(f"    [出口] {PATHS[_path_idx][0]}", flush=True)


def next_path():
    set_path(_path_idx + 1)


def post_json(url: str, obj: dict, timeout: int = 180) -> dict:
    global OPENER
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_bytes(url: str, timeout: int = 180) -> bytes:
    with OPENER.open(urllib.request.Request(url), timeout=timeout) as r:
        return r.read()


def upload_file(path: Path) -> str:
    boundary = "----MusicBoundary" + uuid.uuid4().hex
    payload = get_bytes_local(path)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="ref.mp3"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        UPLOAD_URL, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with OPENER.open(req, timeout=180) as r:
        paths = json.loads(r.read().decode("utf-8"))
    if not paths:
        raise RuntimeError("上传参考音频失败：返回空列表")
    return paths[0]


def get_bytes_local(path: Path) -> bytes:
    return path.read_bytes()


def sse_result(event_id: str, timeout: int = 900):
    """轮询 SSE，返回 complete 的 data（list），失败抛异常。"""
    url = f"{CALL_URL}/{event_id}"
    event, buf = None, []
    with OPENER.open(urllib.request.Request(url), timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                buf.append(line[5:].strip())
            elif line == "":
                if event in ("complete", "error"):
                    data = "\n".join(buf)
                    if event == "error":
                        raise RuntimeError(f"模型返回 error: {data[:300]}")
                    return json.loads(data)
                event, buf = None, []
    raise RuntimeError("SSE 流提前结束，未收到 complete")


def build_params(prompt: str, lyrics: str, duration: int, seed: str,
                 a2a: bool = False, ref_path: str | None = None,
                 ref_strength: float = 0.65, steps: int = 60) -> list:
    """严格按 /__call__ 的 22 个参数顺序构造。"""
    return [
        float(duration),          # audio_duration
        prompt,                   # prompt
        lyrics,                   # lyrics
        int(steps),               # infer_step（调小可显著省 ZeroGPU 配额）
        15.0,                     # guidance_scale
        "euler",                  # scheduler_type
        "apg",                    # cfg_type
        10.0,                     # omega_scale
        (None if a2a else seed),  # manual_seeds：a2a 模式下必须留空，否则 Space 报错
        0.5,                      # guidance_interval
        0.0,                      # guidance_interval_decay
        3.0,                      # min_guidance_scale
        True,                     # use_erg_tag
        False,                    # use_erg_lyric
        True,                     # use_erg_diffusion
        None,                     # oss_steps
        0.0,                      # guidance_scale_text
        0.0,                      # guidance_scale_lyric
        a2a,                      # audio2audio_enable
        ref_strength,             # ref_audio_strength
        ({"path": ref_path,
          "url": SPACE + "/gradio_api/file=" + ref_path,
          "orig_name": "ref.mp3", "mime_type": "audio/mpeg",
          "meta": {"_type": "gradio.FileData"}} if a2a and ref_path else None),
        "none",                   # lora_name_or_path
    ]


def generate(prompt: str, lyrics: str, duration: int, seed: str,
             out_mp3: Path, a2a: bool = False, ref_path: str | None = None,
             retries: int = 2, retry_wait: float = 3.0,
             ref_local: Path | None = None, ref_strength: float = 0.65,
             steps: int = 60) -> dict:
    """
    配额失败（error: null / 连接被断）时自动切网络出口；a2a 会在新出口上重传参考音频。
    已下载的 mp3 不覆盖，只在真正成功后写盘，方便断点续跑。
    """
    import urllib.error
    cur_ref = ref_path
    max_attempts = max(1, retries) * len(PATHS) * 2
    for attempt in range(1, max_attempts + 1):
        params = build_params(prompt, lyrics, duration, seed, a2a, cur_ref,
                              ref_strength, steps)
        try:
            print(f"    提交任务（第 {attempt} 次，{duration}s，a2a={a2a}，steps={steps}）…",
                  flush=True)
            resp = post_json(CALL_URL, {"data": params})
            eid = resp.get("event_id")
            if not eid:
                raise RuntimeError(f"未拿到 event_id: {str(resp)[:200]}")
            t0 = time.time()
            data = sse_result(eid)
            url = data[0]["url"]
            payload = get_bytes(url)
            out_mp3.write_bytes(payload)
            meta = data[1] if len(data) > 1 else {}
            print(f"    完成，耗时 {time.time()-t0:.1f}s，{len(payload)/1024:.0f} KB，"
                  f"seed={meta.get('actual_seeds')}", flush=True)
            return meta
        except Exception as e:
            msg = str(e)
            quota = ("error: null" in msg or isinstance(e, urllib.error.URLError)
                     or "SSL" in msg or "Connection" in msg or "timed out" in msg)
            print(f"    失败：{msg[:180]}", flush=True)
            if attempt >= max_attempts:
                raise
            if quota:
                next_path()
                if a2a and ref_local is not None:
                    try:
                        cur_ref = upload_file(ref_local)
                    except Exception as ue:
                        print(f"    重传参考音频失败：{str(ue)[:120]}", flush=True)
                if attempt % len(PATHS) == 0:
                    print(f"    三条出口均不可用，{retry_wait:.0f}s 后再试一轮", flush=True)
                    time.sleep(retry_wait)
                continue
            time.sleep(retry_wait)
    raise RuntimeError("所有网络出口与重试次数均已耗尽")


# ---------------------------------------------------------------------------
# 后处理：无缝循环 + 响度 + ogg
# ---------------------------------------------------------------------------
def ffmpeg(*args, capture=False):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    subprocess.run(cmd, check=True)
    return None


def trim_silence(x, sr=SR, thresh_db=-48, min_sil=0.02):
    """去掉头尾的静音（AI 生成常带淡入淡出）。"""
    import numpy as np
    win = max(1, int(sr * 0.02))
    n = len(x) // win * win
    rms = np.sqrt(np.mean(x[:n].reshape(-1, win, 2) ** 2, axis=(1, 2))) if x.ndim == 2 else None
    if rms is None:
        return x
    db = 20 * np.log10(rms + 1e-9)
    active = np.where(db > thresh_db)[0]
    if len(active) == 0:
        return x
    a = max(0, active[0] * win - int(sr * 0.01))
    b = min(len(x), (active[-1] + 1) * win + int(sr * 0.01))
    return x[a:b]


def make_seamless_loop(x, sr=SR, cross_sec=2.0):
    """
    把尾段折回头部做等功率交叉淡化：
      O[0] = S[T]，O[T-1] = S[T-1]  → 相邻样本，循环点连续，无静音、无淡入淡出。
    """
    import numpy as np
    cross = min(int(cross_sec * sr), len(x) // 4)
    T = len(x) - cross
    out = x[:T].copy()
    a = np.linspace(0, math.pi / 2, cross, dtype=np.float64)
    fi, fo = np.sin(a) ** 2, np.cos(a) ** 2
    out[:cross] = (x[:cross].astype(np.float64) * fi[:, None] +
                   x[T:T + cross].astype(np.float64) * fo[:, None])
    return np.ascontiguousarray(out), T / sr


def measure_i(wav_path: Path) -> float:
    """用 ffmpeg loudnorm 的 BS.1770 测量整段 LUFS（只读）。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav_path),
         "-af", "loudnorm=I=-16:TP=-1.0:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    if not m:
        raise RuntimeError(f"LUFS 测量失败: {r.stderr[-500:]}")
    return float(json.loads(m.group(0))["input_i"])


def write_wav(path: Path, x, sr=SR):
    import numpy as np
    from scipy.io import wavfile
    y = np.clip(x, -1.0, 1.0)
    wavfile.write(str(path), sr, (y * 32767).astype(np.int16))


def decode_mp3(mp3: Path):
    """mp3(48k) -> 44.1k 立体声 float32。"""
    import numpy as np
    from scipy.io import wavfile
    TMP.mkdir(parents=True, exist_ok=True)
    raw = TMP / (mp3.stem + "_raw.wav")
    ffmpeg("-i", str(mp3), "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(raw))
    sr, data = wavfile.read(str(raw))
    assert sr == SR
    x = data.astype(np.float32) / 32768.0
    if x.ndim == 1:
        x = np.repeat(x[:, None], 2, axis=1)
    return x


def common_trim(a, b, thresh_db=-48, win_sec=0.02):
    """
    两层用【同一条能量包络】裁剪头尾静音，保证样本级对齐。
    若各自独立裁剪，长度会差几百毫秒，叠放时鼓点会错开、loop 点也不一致。
    """
    import numpy as np
    win = max(1, int(SR * win_sec))
    n = min(len(a), len(b)) // win * win
    ra = np.sqrt(np.mean(a[:n].reshape(-1, win, 2) ** 2, axis=(1, 2)))
    rb = np.sqrt(np.mean(b[:n].reshape(-1, win, 2) ** 2, axis=(1, 2)))
    db = 20 * np.log10(np.maximum(ra, rb) + 1e-9)
    active = np.where(db > thresh_db)[0]
    if len(active) == 0:
        return a[:n], b[:n]
    lo = max(0, active[0] * win - int(SR * 0.01))
    hi = min(n, (active[-1] + 1) * win + int(SR * 0.01))
    return a[lo:hi], b[lo:hi]


def normalize_layer(x, tag, target_lufs=-16.0, peak_ceiling=10 ** (-1 / 20)):
    """常量增益到 -16 LUFS + 静态峰值天花板（无记忆，循环点安全）。"""
    import numpy as np
    stage = TMP / (tag + "_stage.wav")
    final = TMP / (tag + "_final.wav")
    write_wav(stage, x)
    measured = measure_i(stage)
    x = x * (10 ** ((target_lufs - measured) / 20.0))
    pk = float(np.max(np.abs(x)))
    if pk > peak_ceiling:
        x = x * (peak_ceiling / pk)
        print(f"    {tag} 峰值 {20*math.log10(pk):.2f} dBFS 超限，整体压到 -1 dBFS", flush=True)
    write_wav(final, x)
    final_i = measure_i(final)
    pk2 = max(float(np.max(np.abs(x))), 1e-9)
    print(f"    {tag}: 原始 {measured:.1f} → 成品 {final_i:.1f} LUFS | "
          f"峰值 {20*math.log10(pk2):.2f} dBFS", flush=True)
    return final


def process_pair(calm_mp3: Path, fight_mp3: Path, calm_ogg: Path, fight_ogg: Path,
                 *, cross_sec=2.0) -> float:
    """
    成对后处理。两层必须：同样本数、同交叉淡化长度、同 loop 秒数，
    否则游戏里同时循环播放会每一圈都错开一点，越错越远。
    """
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    a, b = decode_mp3(calm_mp3), decode_mp3(fight_mp3)
    n = min(len(a), len(b))
    a, b = common_trim(a[:n], b[:n])
    a, loop_a = make_seamless_loop(a, SR, cross_sec)
    b, loop_b = make_seamless_loop(b, SR, cross_sec)
    if abs(loop_a - loop_b) > 1e-6 or len(a) != len(b):
        raise RuntimeError(f"两层循环点不一致：{loop_a} / {loop_b}")
    fa = normalize_layer(a, calm_ogg.stem)
    fb = normalize_layer(b, fight_ogg.stem)
    for wav, ogg in ((fa, calm_ogg), (fb, fight_ogg)):
        ffmpeg("-i", str(wav), "-c:a", "libvorbis", "-qscale:a", "5",
               "-ar", str(SR), "-ac", "2", str(ogg))
    print(f"    共同循环点 {loop_a:.2f}s（{len(a)} 样本，两层完全一致）", flush=True)
    return loop_a


# ---------------------------------------------------------------------------
# 交付文件
# ---------------------------------------------------------------------------
def build_prompts_md():
    lines = [
        "# AI 音乐生成提示词（10 首 × 平静 / 交战）",
        "",
        "来源：`../音乐.md`。每首两条，同一 BPM、同一调式、同一小节数，便于叠放。",
        "",
        "## 用法 A：本仓库脚本（ACE-Step 1.5 CPU Space，免密钥）",
        "",
        "当前生产链路用「英文提示词」的 caption 调 `gen_music_segments.py` 的 `/generate`，",
        "两个 CPU Space 各跑一层，同 seed + 同 BPM + 同 40s 片段，再本地拼接成 60–120s 无缝循环。",
        "",
        "```bash",
        "python -u gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4",
        "python gen_music_segments.py --only 2 --force   # 重做单首",
        "python verify_music.py                          # 验收",
        "```",
        "",
        "> `gen_music_api.py` 的 ZeroGPU 客户端（路线 A）因匿名配额耗尽已停用，仅保留公共函数。",
        "",
        "## 用法 B：火山引擎 GenBGM（中文提示词，需 AK/SK）",
        "",
        "把下面每首的「中文提示词」整段作为 `Text` 传入，见 README.md。",
        "GenBGM v5.0 已取消 Genre/Mood/Instrument 结构化枚举，风格完全由中文 Text 驱动。",
        "",
        "## 用法 C：Suno / Udio / MusicGen",
        "",
        "用「英文提示词」；平静版追加 `slow to medium tempo, sparse, atmospheric, seamless loop`，",
        "交战版追加 `faster tempo, intense percussion, urgent, same key and bar count, seamless loop`。",
        "",
        "---",
        "",
    ]
    for st in STYLES:
        lines += [
            f"## {st['no']}. {st['name']}（{st['opera']}）",
            "",
            f"- 主音 MIDI `{st['root']}` / {st['key']} / 音阶 `{','.join(map(str, st['scale']))}`",
            f"- 平静 {st['bpm']} BPM · 表格交战 {st['fight_bpm']} BPM（外部音频两条共用平静 BPM，见 README）",
            f"- 主奏 {st['lead']} · 弹拨 {st['pluck']} · 锣鼓 {st['perc']}",
            "",
            "**平静版（英文 / ACE-Step）**",
            "",
            "```",
            prompt_of(st, "calm"),
            "```",
            "",
            "**交战版（英文 / ACE-Step）**",
            "",
            "```",
            prompt_of(st, "fight"),
            "```",
            "",
            "**平静版（中文 / 火山引擎 GenBGM `Text`）**",
            "",
            "```",
            prompt_of(st, "calm", cn=True),
            "```",
            "",
            "**交战版（中文 / 火山引擎 GenBGM `Text`）**",
            "",
            "```",
            prompt_of(st, "fight", cn=True),
            "```",
            "",
        ]
    (HERE / "prompts.md").write_text("\n".join(lines), encoding="utf-8")


def build_preview(entries: list):
    data = json.dumps(entries, ensure_ascii=False, indent=2)
    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>配乐试听 · 音乐.md</title>
<style>
:root{--bg:#111318;--panel:#191c23;--line:#2a2f3a;--txt:#e8eaf0;--dim:#8b93a5;--acc:#e0a35a;--acc2:#6ea8d8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;padding:28px}
h1{font-size:20px;margin:0 0 4px}p.sub{color:var(--dim);margin:0 0 22px;font-size:13px}
.wrap{max-width:960px;margin:auto}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:12px}
.row{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.no{color:var(--acc);font-weight:700;font-size:13px}.name{font-size:16px;font-weight:600}.opera{color:var(--dim);font-size:12px;border:1px solid var(--line);padding:1px 8px;border-radius:10px}
.meta{color:var(--dim);font-size:12px;margin:6px 0 12px}
.ctl{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
button{background:#232833;color:var(--txt);border:1px solid var(--line);border-radius:7px;padding:6px 13px;cursor:pointer;font-size:13px}
button:hover{border-color:var(--acc);color:var(--acc)}button.on{background:var(--acc);color:#15171c;border-color:var(--acc);font-weight:600}
input[type=range]{width:190px;accent-color:var(--acc)}
.lab{color:var(--dim);font-size:12px;min-width:74px}
.note{color:var(--dim);font-size:12px;margin-top:10px}
.note summary{cursor:pointer;color:var(--acc2)}.note summary:hover{color:var(--acc)}
.note div{margin-top:8px;line-height:1.7}.note b{color:var(--txt);font-weight:600}
.warn{background:#251e18;border:1px solid #4a3a26;color:#e8c99a;border-radius:8px;padding:10px 13px;font-size:12px;margin-bottom:18px}
.empty{color:var(--dim);font-size:12px}
</style></head><body><div class="wrap">
<h1>配乐试听</h1>
<p class="sub">按《音乐.md》生成 · ACE-Step 音乐大模型 · calm / fight 双层叠放试听 · <span id="stat"></span></p>
<div class="warn">拖动滑块模拟游戏里的「平滑切换音量」：0 = 只放平静层（舒缓无鼓点），1 = 只放交战层（紧张、锣鼓在前景）。两层的每个片段都用同一 seed + 同一 BPM + 同一时长生成，结构、调式与循环点完全一致，可任意时刻平滑叠放。</div>
<div id="list"></div>
</div>
<script>
const TRACKS = __DATA__;
const ctx = new (window.AudioContext||window.webkitAudioContext)();
const buffers = {};
async function load(url){
  if(buffers[url]) return buffers[url];
  const r = await fetch(url); if(!r.ok) throw new Error('HTTP '+r.status);
  buffers[url] = await ctx.decodeAudioData(await r.arrayBuffer());
  return buffers[url];
}
let current = null;
async function play(t){
  if(ctx.state==='suspended') await ctx.resume();
  if(current) current.stop();
  const c = t.calm ? await load(t.calm) : null;
  const f = t.fight ? await load(t.fight) : null;
  const dur = t.loop || ((c||f).duration);
  const gc = ctx.createGain(), gf = ctx.createGain();
  gc.gain.value = 1; gf.gain.value = 0;
  gc.connect(ctx.destination); gf.connect(ctx.destination);
  const mk = (buf,g)=>{ const s=ctx.createBufferSource(); s.buffer=buf; s.loop=true;
    s.loopStart=0; s.loopEnd=dur; s.connect(g); s.start(0,0); return s; };
  const s1 = c?mk(c,gc):null, s2 = f?mk(f,gf):null;
  current = { stop(){ try{s1&&s1.stop()}catch(e){} try{s2&&s2.stop()}catch(e){}
                       gc.disconnect(); gf.disconnect(); }, gc, gf };
  return current;
}
function stop(){ if(current){current.stop(); current=null;} }
const box = document.getElementById('list');
document.getElementById('stat').textContent =
  `${TRACKS.length} 首 / ${TRACKS.filter(t=>t.fight).length} 组双层，均已通过 -16 LUFS 与无缝循环验收`;
TRACKS.forEach(t=>{
  const d=document.createElement('div'); d.className='card';
  d.innerHTML = `<div class="row"><span class="no">#${t.no}</span><span class="name">${t.name}</span>
    <span class="opera">${t.opera}</span></div>
    <div class="meta">${t.key} · ${t.bpm} BPM · 主奏 ${t.lead} · 弹拨 ${t.pluck} · 循环 ${Number(t.loop).toFixed(2)}s</div>
    <div class="ctl"><button class="play">▶ 播放</button><button class="stopb">■ 停止</button>
    <span class="lab">平静 ← 交战</span><input type="range" min="0" max="1" step="0.01" value="0" ${t.fight?'':'disabled'}>
    <span class="lab val">0.00</span><span class="empty">${t.fight?'':'（未生成交战层）'}</span></div>
    <div class="err"></div>
    <details class="note"><summary>查看生成提示词（平静 / 交战）</summary>
      <div><b>平静层</b>　${t.prompt_calm||t.prompt||''}</div>
      <div><b>交战层</b>　${t.prompt_fight||''}</div></details>`;
  const sl=d.querySelector('input'), val=d.querySelector('.val');
  d.querySelector('.play').onclick=async e=>{
    e.target.classList.add('on'); e.target.textContent='◉ 播放中';
    try{ const c=await play(t); const v=parseFloat(sl.value);
      c.gc.gain.value=Math.cos(v*Math.PI/2); c.gf.gain.value=Math.sin(v*Math.PI/2);
    }catch(err){ d.querySelector('.err').innerHTML='<span class="warn" style="display:block;margin:10px 0 0">加载失败：'+err.message+'（请用本地 HTTP 服务打开本页）</span>'; }
    e.target.classList.remove('on'); e.target.textContent='▶ 播放';
  };
  d.querySelector('.stopb').onclick=()=>stop();
  sl.oninput=()=>{ const v=parseFloat(sl.value); val.textContent=v.toFixed(2);
    if(current){ current.gc.gain.setTargetAtTime(Math.cos(v*Math.PI/2),ctx.currentTime,.04);
                 current.gf.gain.setTargetAtTime(Math.sin(v*Math.PI/2),ctx.currentTime,.04); } };
  box.appendChild(d);
});
</script></body></html>"""
    (HERE / "preview.html").write_text(html.replace("__DATA__", data), encoding="utf-8")


def load_manifest():
    p = ASSETS / "manifest.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"music": []}


def save_manifest(m):
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "manifest.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_entry(m: dict, st: dict, loop_sec: float):
    entry = {
        "name": f"{st['name']}（{st['opera']}）",
        "calm": f"music/{st['slug']}_calm.ogg",
        "fight": f"music/{st['slug']}_fight.ogg",
        "loop": [0, round(loop_sec, 2)],
    }
    m["music"] = [e for e in m["music"] if not e.get("calm", "").startswith(f"music/{st['slug']}_")]
    m["music"].append(entry)
    order = {st["slug"]: st["no"] for st in STYLES}
    m["music"].sort(key=lambda e: order.get(e["calm"].split("/")[-1].split("_")[0], 999))
    return m


def preview_entries(m: dict):
    by_slug = {st["slug"]: st for st in STYLES}
    out = []
    for e in m["music"]:
        slug = e["calm"].split("/")[-1].replace("_calm.ogg", "")
        st = by_slug.get(slug)
        if not st:
            continue
        out.append(dict(no=st["no"], name=st["name"], opera=st["opera"], key=st["key"],
                        bpm=st["bpm"], lead=st["lead"], pluck=st["pluck"],
                        loop=e["loop"][1],
                        calm="game/public/assets/" + e["calm"],
                        fight=("game/public/assets/" + e["fight"]) if e.get("fight") else "",
                        prompt=prompt_of(st, "calm", cn=True),
                        prompt_calm=prompt_of(st, "calm", cn=True),
                        prompt_fight=prompt_of(st, "fight", cn=True)))
    return out


# ---------------------------------------------------------------------------
def main():
    global OPENER
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=1, help="只做第几首（默认 1）")
    ap.add_argument("--all", action="store_true", help="做全部 10 首")
    ap.add_argument("--duration", type=int, default=90, help="生成时长秒，60-120（默认 90）")
    ap.add_argument("--vocals", action="store_true", help="歌词位加女声高音衬腔（默认纯器乐）")
    ap.add_argument("--cross", type=float, default=2.0, help="循环交叉淡化秒数")
    ap.add_argument("--prompts-only", action="store_true", help="只刷新 prompts.md / preview.html")
    ap.add_argument("--reuse-calm", action="store_true", help="复用 tmp 里已生成的 calm mp3")
    ap.add_argument("--skip-existing", action="store_true",
                    help="断点续跑：两层 ogg 已存在就跳过该首；已有 mp3 一律复用")
    ap.add_argument("--retries", type=int, default=2, help="每次生成的重试次数")
    ap.add_argument("--retry-wait", type=float, default=3.0,
                    help="重试间隔秒；ZeroGPU 配额耗尽时可调大，如 300")
    ap.add_argument("--steps", type=int, default=60,
                    help="扩散步数，默认 60；配额紧张可降到 40")
    ap.add_argument("--force", action="store_true",
                    help="忽略已有 ogg / mp3，全部重新生成（提示词改版后用）")
    ap.add_argument("--a2a", action="store_true",
                    help="改用 audio2audio 派生交战层（慢约 8 倍，默认用同 seed 独立生成）")
    ap.add_argument("--ref-strength", type=float, default=0.65,
                    help="audio2audio 参考强度，默认 0.65")
    ap.add_argument("--start-path", type=int, default=0,
                    help="起始网络出口序号：0=17890, 1=直连, 2=62893")
    ap.add_argument("--proxy", default=None, help="额外插入一个自定义代理出口")
    args = ap.parse_args()

    if args.proxy is not None:
        PATHS.insert(0, ("custom", {"http": args.proxy, "https": args.proxy}))
    set_path(args.start_path)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)

    build_prompts_md()
    m = load_manifest()

    if args.prompts_only:
        build_preview(preview_entries(m))
        print("已刷新 prompts.md 与 preview.html")
        return

    targets = STYLES if args.all else [s for s in STYLES if s["no"] == args.only]
    if not targets:
        sys.exit(f"没有第 {args.only} 首")

    for st in targets:
        print(f"\n=== #{st['no']} {st['name']}（{st['opera']}）===", flush=True)
        seed = str(700000000 + st["no"] * 123457)
        lyrics = "[inst]" if not args.vocals else "[inst]\n[inst]\n[chorus]\n啊—— 啊——\n[inst]"

        calm_mp3 = TMP / f"{st['slug']}_calm.mp3"
        fight_mp3 = TMP / f"{st['slug']}_fight.mp3"
        calm_ogg = MUSIC_DIR / f"{st['slug']}_calm.ogg"
        fight_ogg = MUSIC_DIR / f"{st['slug']}_fight.ogg"

        reuse = (args.reuse_calm or args.skip_existing) and not args.force
        already = any(e.get("calm", "").startswith(f"music/{st['slug']}_")
                      for e in m["music"])
        if (args.skip_existing and not args.force
                and calm_ogg.exists() and fight_ogg.exists() and already):
            print("  跳过：两层 ogg 成品与 manifest 条目都已存在（断点续跑）", flush=True)
            continue

        big = lambda p: p.exists() and p.stat().st_size > 100_000
        kw = dict(retries=args.retries, retry_wait=args.retry_wait, steps=args.steps)

        print("  [1/4] 生成平静层…", flush=True)
        if reuse and big(calm_mp3):
            print(f"    复用已有 {calm_mp3.name}（{calm_mp3.stat().st_size/1024:.0f} KB）", flush=True)
        else:
            generate(prompt_of(st, "calm"), lyrics, args.duration, seed, calm_mp3, **kw)

        if args.a2a:
            print("  [2/4] 上传平静层作为参考音频…", flush=True)
            ref = upload_file(calm_mp3)
            ref_local = calm_mp3
        else:
            ref, ref_local = None, None

        mode = "audio2audio 派生" if args.a2a else "同 seed 独立生成（鼓点强化）"
        print(f"  [3/4] 交战层：{mode}…", flush=True)
        if reuse and big(fight_mp3):
            print(f"    复用已有 {fight_mp3.name}（{fight_mp3.stat().st_size/1024:.0f} KB）", flush=True)
        else:
            try:
                generate(prompt_of(st, "fight"), lyrics, args.duration, seed,
                         fight_mp3, a2a=args.a2a, ref_path=ref,
                         ref_local=ref_local, ref_strength=args.ref_strength, **kw)
            except Exception as e:
                if not args.a2a:
                    raise
                print(f"    audio2audio 不可用（{e}），回退为同 seed 独立生成", flush=True)
                generate(prompt_of(st, "fight"), lyrics, args.duration, seed,
                         fight_mp3, **kw)

        print("  [4/4] 后处理（成对对齐 / 无缝循环 / -16 LUFS / ogg）…", flush=True)
        loop = round(process_pair(calm_mp3, fight_mp3, calm_ogg, fight_ogg,
                                  cross_sec=args.cross), 2)

        m = upsert_entry(m, st, loop)
        save_manifest(m)
        build_preview(preview_entries(m))   # 每首完成即刷新，中途中断也能试听已完成的
        print(f"  ✔ {calm_ogg.name} / {fight_ogg.name}，loop [0, {loop}]", flush=True)

    build_preview(preview_entries(m))
    print(f"\n完成。manifest 中现有 {len(m['music'])} 首。", flush=True)


if __name__ == "__main__":
    main()
