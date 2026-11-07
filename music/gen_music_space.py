#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调用公开的 ACE-Step-CPU Gradio 大模型推理接口，补齐《音乐.md》剩余曲目。

背景
----
官方 ACE-Step / ACE-Step-v1.5 / MusicGen 等 ZeroGPU Space 共用同一份匿名配额，
配额耗尽后服务端会明确返回：
    "You have exceeded your ZeroGPU quota (90s requested vs 0s left)"
    "You have exceeded your ZeroGPU runs limit. Authenticate with a HF token"
因此改用由 Space 拥有者承担算力的 cpu-basic 实例（不消耗匿名 ZeroGPU 配额）：
    https://werecooking-ace-step-cpu.hf.space            /generate
    https://rawdripcollective-codec-ace-step-cpu.hf.space /generate
这两个是真正的 ACE-Step 1.5 扩散音乐大模型（GGUF 量化、CPU 推理），
且 /generate 暴露 caption / lyrics / bpm / duration / seed / steps，
正好满足《音乐.md》「calm 与 fight 同速、同小节数、同调、同 loop 点」的要求：
两层用【同一个 seed + 同一个 bpm + 同一个 duration】独立生成，
只在 caption 里区分「舒缓无鼓」与「紧张锣鼓」，再用 process_pair() 做样本级对齐。

注意：这不是程序化合成——音频全部由音乐生成大模型推理产出；
本地只做解码 / 去静音 / 无缝循环交叉淡化 / 响度归一化 / ogg 编码。

用法：
    python gen_music_space.py --all --skip-existing --duration 65
    python gen_music_space.py --only 2 --duration 65
    python gen_music_space.py --all --status
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
from pathlib import Path

import gen_music_api as g
import space_client as sc

HERE = Path(__file__).resolve().parent

# cpu-basic，不受 ZeroGPU 匿名配额限制；两个实例可并行跑不同曲目。
BACKENDS = [
    "https://werecooking-ace-step-cpu.hf.space",
    "https://rawdripcollective-codec-ace-step-cpu.hf.space",
]
ENDPOINT = "/generate"
LORA = "None (no LoRA)"
LM_MODEL = "acestep-5Hz-lm-1.7B-Q8_0.gguf"
LYRICS = "[Instrumental]"          # 纯器乐，不出现人声
GEN_TIMEOUT = 3600                  # CPU 推理慢，单任务最长 1 小时


def caption_of(st: dict, layer: str) -> str:
    """沿用 prompts.md 的双层提示词，去掉 v1 专用的标签写法。"""
    p = g.prompt_of(st, layer)
    # v1.5 的 caption 是自然语言描述；保留 BPM / 调式 / 乐器与风格约束即可
    return p.replace("[inst]", "").strip()


def params_of(st: dict, layer: str, duration: int, seed: int, steps: int) -> list:
    # /generate 的 8 个参数顺序（来自 /gradio_api/info）
    return [caption_of(st, layer), LYRICS, st["bpm"], duration, seed,
            steps, LORA, LM_MODEL]


def gen_layer(st: dict, layer: str, base: str, duration: int, seed: int,
              steps: int, out: Path, retries: int = 2) -> dict:
    """生成单层并落盘为 mp3；已存在则复用（断点续跑）。"""
    if out.exists() and out.stat().st_size > 100_000:
        print(f"    复用 {out.name}（{out.stat().st_size/1024:.0f} KB）", flush=True)
        return {"reused": True}
    p = params_of(st, layer, duration, seed, steps)
    last = None
    for i in range(1, retries + 1):
        try:
            print(f"    [{layer}] 提交 {base.split('//')[1].split('.')[0]} "
                  f"（第 {i} 次，{duration}s / {st['bpm']}BPM / seed={seed}）…", flush=True)
            r = sc.call_space(base, ENDPOINT, p, timeout=GEN_TIMEOUT, verbose=True)
            sc.download_audio(base, r["data"], out, timeout=180)
            print(f"    [{layer}] 完成 {out.name}（{out.stat().st_size/1024:.0f} KB）", flush=True)
            return {"secs": round(r["secs"], 1)}
        except Exception as e:
            last = e
            print(f"    [{layer}] 失败：{type(e).__name__}: {str(e)[:160]}", flush=True)
            if i < retries:
                time.sleep(10)
    raise RuntimeError(f"{st['slug']}/{layer} 生成失败：{last}")


def do_track(st: dict, duration: int, steps: int, m: dict, skip_existing: bool,
             force: bool, cross: float) -> str:
    no = st["no"]
    seed = 700000000 + no * 123457
    calm_mp3 = g.TMP / f"{st['slug']}_calm.mp3"
    fight_mp3 = g.TMP / f"{st['slug']}_fight.mp3"
    calm_ogg = g.MUSIC_DIR / f"{st['slug']}_calm.ogg"
    fight_ogg = g.MUSIC_DIR / f"{st['slug']}_fight.ogg"
    already = any(e.get("calm", "").startswith(f"music/{st['slug']}_")
                  for e in m["music"])

    print(f"\n=== #{no} {st['name']}（{st['opera']}）===", flush=True)
    if (skip_existing and not force and calm_ogg.exists() and fight_ogg.exists()
            and already):
        print("  跳过：两层 ogg 与 manifest 条目都已存在", flush=True)
        return "skip"

    # 两层分别交给两个 CPU Space 并行推理
    jobs = [(calm_mp3, "calm", BACKENDS[0]), (fight_mp3, "fight", BACKENDS[1])]
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(gen_layer, st, layer, base, duration, seed,
                          steps, out) for out, layer, base in jobs]
        for f in futs:
            f.result()

    loop = round(g.process_pair(calm_mp3, fight_mp3, calm_ogg, fight_ogg,
                                cross_sec=cross), 2)
    g.upsert_entry(m, st, loop)
    g.save_manifest(m)
    g.build_preview(g.preview_entries(m))
    print(f"  ✓ #{no} 完成：共同循环点 {loop:.2f}s，manifest / preview 已更新", flush=True)
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", type=int, default=0)
    ap.add_argument("--duration", type=int, default=65, help="生成秒数，60-120")
    ap.add_argument("--steps", type=int, default=8, help="扩散步数（CPU 用 turbo 8 步）")
    ap.add_argument("--cross", type=float, default=2.0)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    g.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    g.TMP.mkdir(parents=True, exist_ok=True)
    g.build_prompts_md()
    m = g.load_manifest()

    if args.status:
        print("manifest tracks:", len(m["music"]))
        print("ogg files:", len(list(g.MUSIC_DIR.glob("*.ogg"))))
        for e in m["music"]:
            print("  ", e["name"], e["loop"])
        return

    targets = g.STYLES if args.all else [s for s in g.STYLES if s["no"] == args.only]
    if not targets:
        sys.exit("请用 --all 或 --only N 指定曲目")

    done = 0
    for st in targets:
        try:
            if do_track(st, args.duration, args.steps, m,
                        args.skip_existing, args.force, args.cross) == "ok":
                done += 1
        except Exception as e:
            print(f"  ! #{st['no']} 未完成：{type(e).__name__}: {str(e)[:200]}", flush=True)
            # 单曲失败不中断整批，继续下一首
            continue
    print(f"\n本轮完成 {done} 首；manifest 共 {len(g.load_manifest()['music'])} 首", flush=True)


if __name__ == "__main__":
    main()
