#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用「短片段多次推理 + 等功率交叉淡化拼接」绕过 ACE-Step-CPU 的 600s 合成上限。

为什么需要
----------
公开、免凭据的 ZeroGPU Space 匿名配额已全局耗尽（21 个 Space × 3 条出口 = 63 次
最小任务全部失败，服务端明确返回 "You have exceeded your ZeroGPU quota"）。
唯一可用的模型接口是两个 cpu-basic 的 ACE-Step 1.5 GGUF 实例：
    https://werecooking-ace-step-cpu.hf.space            /generate
    https://rawdripcollective-codec-ace-step-cpu.hf.space /generate
但其 app.py 里 `_poll_job(synth_job_id, timeout=600)` 是硬上限，
实测 65s / 8steps 返回 "Synth timeout after 600s"。
因此改成每段 30~40s、4 步推理，再用本地交叉淡化拼成 60~120s。

仍然符合「不程序化合成」
------------------------
所有声音都由音乐生成大模型推理产生；本地只做
解码 / 片段交叉淡化 / 去静音 / 无缝循环 / 响度归一化 / ogg 编码。

对齐保证
--------
* 每个片段编号 i 的 calm 与 fight 使用【同一个 seed】+ 同一个 bpm + 同一个时长；
  只改 caption（舒缓无鼓 / 紧张锣鼓）。
* 所有片段统一裁到全局最短长度，两层拼接后样本数完全一致。
* 最后复用 gen_music_api.process_pair() 做样本级共同裁剪与同一 loop 点。

用法：
    python gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4
    python gen_music_segments.py --only 2 --duration 30 --segments 3 --steps 4
    python gen_music_segments.py --status
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import math
import sys
import threading
import time
from pathlib import Path

import gen_music_api as g
import gen_music_space as gs
import space_client as sc

HERE = Path(__file__).resolve().parent

SEG_CROSS = 2.0          # 片段之间的等功率交叉淡化秒数
LOOP_CROSS = 2.0         # 首尾无缝循环交叉淡化秒数
GEN_TIMEOUT = 1500       # 单段推理最长等待（含 LM + synth + 排队）


def seg_path(st: dict, layer: str, i: int) -> Path:
    return g.TMP / f"{st['slug']}_{layer}_seg{i}.mp3"


def gen_one(st: dict, layer: str, i: int, base: str, duration: int,
            steps: int, seed: int, retries: int = 2) -> dict:
    out = seg_path(st, layer, i)
    if out.exists() and out.stat().st_size > 50_000:
        print(f"    复用 {out.name}（{out.stat().st_size/1024:.0f} KB）", flush=True)
        return {"ok": True, "reused": True}
    p = gs.params_of(st, layer, duration, seed, steps)
    last = None
    for k in range(1, retries + 1):
        try:
            tag = base.split("//")[1].split(".")[0]
            print(f"    [{layer}#{i}] 提交 {tag} 第{k}次 "
                  f"({duration}s / {st['bpm']}BPM / {steps}steps / seed={seed})", flush=True)
            r = sc.call_space(base, gs.ENDPOINT, p, timeout=GEN_TIMEOUT, verbose=True)
            sc.download_audio(base, r["data"], out, timeout=180)
            print(f"    [{layer}#{i}] 完成 {out.name} "
                  f"{out.stat().st_size/1024:.0f} KB / {r['secs']:.0f}s", flush=True)
            return {"ok": True, "secs": round(r["secs"], 1)}
        except Exception as e:
            last = e
            print(f"    [{layer}#{i}] 失败：{type(e).__name__}: {str(e)[:140]}", flush=True)
            if k < retries:
                time.sleep(8)
    return {"ok": False, "err": f"{type(last).__name__}: {last}"}


def stitch_arrays(arrays: list, n: int, cross_sec: float = SEG_CROSS):
    """把多个模型生成的片段等功率交叉淡化拼成一条长音频（44.1k 立体声 float32）。
    n 是所有片段（含另一层）统一裁到的样本数，保证两层拼接位置完全一致。"""
    import numpy as np
    arrays = [x[:n] for x in arrays]
    cross = min(int(cross_sec * g.SR), n // 4)
    a = np.linspace(0, math.pi / 2, cross, dtype=np.float64)
    fi, fo = np.sin(a) ** 2, np.cos(a) ** 2
    out = arrays[0]
    for x in arrays[1:]:
        blend = (out[-cross:].astype(np.float64) * fo[:, None] +
                 x[:cross].astype(np.float64) * fi[:, None])
        out = np.concatenate(
            [out[:-cross], blend.astype(np.float32), x[cross:]], axis=0)
    return np.ascontiguousarray(out), len(out) / g.SR


def stitch(paths: list[Path], cross_sec: float = SEG_CROSS):
    arrays = [g.decode_mp3(p) for p in paths]
    return stitch_arrays(arrays, min(len(x) for x in arrays), cross_sec)


def do_track(st: dict, duration: int, segments: int, steps: int,
             m: dict, skip_existing: bool, force: bool) -> str:
    import numpy as np
    no = st["no"]
    base_seed = 700000000 + no * 123457
    calm_ogg = g.MUSIC_DIR / f"{st['slug']}_calm.ogg"
    fight_ogg = g.MUSIC_DIR / f"{st['slug']}_fight.ogg"
    already = any(e.get("calm", "").startswith(f"music/{st['slug']}_")
                  for e in m["music"])

    print(f"\n=== #{no} {st['name']}（{st['opera']}）===", flush=True)
    if (skip_existing and not force and calm_ogg.exists() and fight_ogg.exists()
            and already):
        print("  跳过：两层 ogg 与 manifest 条目都已存在", flush=True)
        return "skip"

    jobs = []
    for i in range(segments):
        seed = base_seed + i * 7919
        for layer in ("calm", "fight"):
            jobs.append((layer, i, seed))

    q = collections.deque(jobs)
    lock = threading.Lock()
    results = []

    def worker(base: str):
        while True:
            with lock:
                if not q:
                    return
                layer, i, seed = q.popleft()
            r = gen_one(st, layer, i, base, duration, steps, seed)
            with lock:
                results.append((layer, i, r))

    with cf.ThreadPoolExecutor(max_workers=len(gs.BACKENDS)) as ex:
        list(ex.map(worker, gs.BACKENDS))

    bad = [r for r in results if not r[2]["ok"]]
    missing = [(la, i, seed) for la, i, seed in jobs
               if not seg_path(st, la, i).exists()
               or seg_path(st, la, i).stat().st_size < 50_000]
    if bad or missing:
        raise RuntimeError(f"缺少片段：bad={[(b[0], b[1], b[2].get('err')) for b in bad]} "
                           f"missing={missing}")

    calm_wav = g.TMP / f"{st['slug']}_calm_stitched.wav"
    fight_wav = g.TMP / f"{st['slug']}_fight_stitched.wav"
    all_paths = [seg_path(st, la, i) for la in ("calm", "fight")
                 for i in range(segments)]
    all_arrays = [g.decode_mp3(p) for p in all_paths]
    n = min(len(x) for x in all_arrays)          # 两层所有片段统一样本数
    half = len(all_arrays) // 2
    a, la = stitch_arrays(all_arrays[:half], n)
    b, lb = stitch_arrays(all_arrays[half:], n)
    g.write_wav(calm_wav, a)
    g.write_wav(fight_wav, b)
    print(f"  拼接完成：{segments} 段 × {duration}s → {la:.2f}s "
          f"（两段统一裁到 {n/g.SR:.2f}s，calm/fight 完全一致）", flush=True)

    # 用 v2 归一化：先做无记忆峰值整形，保证 -16 LUFS 与 OGG 峰值余量同时成立
    import fix_levels
    loop = round(fix_levels.process_pair_v2(calm_wav, fight_wav, calm_ogg, fight_ogg,
                                            cross_sec=LOOP_CROSS), 2)
    g.upsert_entry(m, st, loop)
    g.save_manifest(m)
    g.build_preview(g.preview_entries(m))
    print(f"  ✓ #{no} 完成：共同循环点 {loop:.2f}s，manifest / preview 已更新", flush=True)
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", type=int, default=0)
    ap.add_argument("--duration", type=int, default=40, help="单段模型生成秒数")
    ap.add_argument("--segments", type=int, default=2, help="每层片段数")
    ap.add_argument("--steps", type=int, default=4, help="扩散步数（turbo 4~8）")
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

    # 注意：Space 返回的 mp3 头里码率不对，ffprobe 会虚报 ~1.38 倍时长；
    # ffmpeg 实际解码出的音频就是请求的秒数（60s→60.0s、40s→39.6s）。
    actual = args.duration
    total = actual * args.segments - SEG_CROSS * (args.segments - 1) - LOOP_CROSS
    print(f"预计成品 {total:.1f}s（单段实际约 {actual:.1f}s × {args.segments} 段，"
          f"再扣去静音裁剪）", flush=True)
    if not 60 <= total <= 120:
        print("警告：预计成品不在 60~120s 区间，实际以 process_pair 输出为准", flush=True)

    targets = g.STYLES if args.all else [s for s in g.STYLES if s["no"] == args.only]
    if not targets:
        sys.exit("请用 --all 或 --only N 指定曲目")

    done = 0
    for st in targets:
        try:
            if do_track(st, args.duration, args.segments, args.steps, m,
                        args.skip_existing, args.force) == "ok":
                done += 1
        except Exception as e:
            print(f"  ! #{st['no']} 未完成：{type(e).__name__}: {str(e)[:240]}", flush=True)
            continue
    print(f"\n本轮完成 {done} 首；manifest 共 {len(g.load_manifest()['music'])} 首", flush=True)


if __name__ == "__main__":
    main()
