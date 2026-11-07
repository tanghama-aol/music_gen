#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已生成的曲目重新做「静态峰值整形 → -16 LUFS → 峰值余量」后处理。

背景：CPU ACE-Step 1.5 输出的 mp3 本身已削波到 0 dBFS。旧版 normalize_layer()
直接按 -1 dBFS 峰值天花板衰减，导致：
  * 平静层被压到 -18.2 LUFS（离 -16 差 2.2 LU）
  * WAV 峰值 -1.00 dBFS，但 Vorbis 有损编码过冲到 -0.8 dBFS，违反 <= -1 dBFS

本模块用**无记忆（memoryless）静态峰值整形**：只对超过膝点的极少数样本做
tanh 软压缩，不改变相位/节拍、不引入状态，因此对无缝循环绝对安全；
压低波峰因数后即可同时满足 -16 LUFS 与峰值余量，无需整体衰减。

用法：
    python fix_levels.py            # 重处理所有带 *_stitched.wav 缓存的曲目
    python fix_levels.py --only 2   # 只处理某一编号
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

import gen_music_api as g

TARGET_LUFS = -16.0
WAV_CEILING_DB = -2.0          # Vorbis 实测过冲约 +0.5 dB，留足余量保证成品 <= -1 dBFS
WAV_CEILING = 10 ** (WAV_CEILING_DB / 20)


def shave(x, cap: float):
    """无记忆 tanh 软削波：把 |x| 的峰值压到 cap 附近，膝点 = 0.75*cap。"""
    cap = float(np.clip(cap, 0.35, 0.95))
    knee = cap * 0.75
    a = np.abs(x).astype(np.float64)
    y = a.copy()
    over = a > knee
    if over.any():
        y[over] = knee + (cap - knee) * np.tanh((a[over] - knee) / (cap - knee))
    return (np.sign(x) * y).astype(np.float32)


def normalize(x, tag: str) -> Path:
    stage = g.TMP / (tag + "_stage.wav")
    final = g.TMP / (tag + "_final.wav")
    g.write_wav(stage, x)
    measured = g.measure_i(stage)
    gain = 10 ** ((TARGET_LUFS - measured) / 20.0)
    # 增益后的峰值必须 <= WAV_CEILING，所以先把源峰值压到 WAV_CEILING/gain
    x = shave(x, WAV_CEILING / gain)
    x = x * gain
    pk = float(np.max(np.abs(x)))
    if pk > WAV_CEILING:
        x = x * (WAV_CEILING / pk)
        pk = WAV_CEILING
    g.write_wav(final, x)
    got = g.measure_i(final)
    print(f"    {tag}: 原始 {measured:.1f} → 成品 {got:.1f} LUFS | "
          f"WAV 峰值 {20*math.log10(max(pk,1e-9)):.2f} dBFS", flush=True)
    return final


def process_pair_v2(calm_src: Path, fight_src: Path,
                    calm_ogg: Path, fight_ogg: Path, *, cross_sec=2.0) -> float:
    a, b = g.decode_mp3(calm_src), g.decode_mp3(fight_src)
    n = min(len(a), len(b))
    a, b = g.common_trim(a[:n], b[:n])
    a, loop_a = g.make_seamless_loop(a, g.SR, cross_sec)
    b, loop_b = g.make_seamless_loop(b, g.SR, cross_sec)
    if abs(loop_a - loop_b) > 1e-6 or len(a) != len(b):
        raise RuntimeError(f"两层循环点不一致：{loop_a} / {loop_b}")
    fa = normalize(a, calm_ogg.stem)
    fb = normalize(b, fight_ogg.stem)
    for wav, ogg in ((fa, calm_ogg), (fb, fight_ogg)):
        g.ffmpeg("-i", str(wav), "-c:a", "libvorbis", "-qscale:a", "5",
                 "-ar", str(g.SR), "-ac", "2", str(ogg))
    print(f"    共同循环点 {loop_a:.2f}s（{len(a)} 样本，两层完全一致）", flush=True)
    return loop_a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=0)
    args = ap.parse_args()

    m = g.load_manifest()
    targets = g.STYLES if not args.only else [s for s in g.STYLES if s["no"] == args.only]
    done = 0
    for st in targets:
        slug = st["slug"]
        cw = g.TMP / f"{slug}_calm_stitched.wav"
        fw = g.TMP / f"{slug}_fight_stitched.wav"
        co = g.MUSIC_DIR / f"{slug}_calm.ogg"
        fo = g.MUSIC_DIR / f"{slug}_fight.ogg"
        if not (cw.exists() and fw.exists() and co.exists() and fo.exists()):
            print(f"跳过 #{st['no']} {st['name']}：缺少缓存或成品", flush=True)
            continue
        print(f"=== #{st['no']} {st['name']} 重新归一化 ===", flush=True)
        loop = round(process_pair_v2(cw, fw, co, fo, cross_sec=2.0), 2)
        for e in m["music"]:
            if e["calm"] == f"music/{slug}_calm.ogg":
                e["loop"] = [0, loop]
        g.save_manifest(m)
        done += 1
    g.build_preview(g.preview_entries(m))
    print(f"\n完成 {done} 首；manifest / preview 已刷新", flush=True)


if __name__ == "__main__":
    main()
