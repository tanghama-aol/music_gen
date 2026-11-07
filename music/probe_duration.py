#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测量 ACE-Step-CPU 在更低步数下能稳定生成的最长片段。"""
from __future__ import annotations

import concurrent.futures as cf
import sys
import time
from pathlib import Path

import space_client as sc
import gen_music_space as gm

TMP = Path(__file__).resolve().parent / "tmp"
TMP.mkdir(exist_ok=True)

PROMPT = ("Chinese Qinqiang opera instrumental, erhu and dizi, slow 80 BPM, "
          "gentle and sparse, no drums, instrumental, seamless loop")


def run(job):
    name, base, dur, steps, seed = job
    t0 = time.time()
    try:
        p = [PROMPT, gm.LYRICS, 80, dur, seed, steps, gm.LORA, gm.LM_MODEL]
        r = sc.call_space(base, gm.ENDPOINT, p, timeout=1500, verbose=True)
        out = TMP / f"dur_{name}.mp3"
        try:
            sc.download_audio(base, r["data"], out, timeout=120)
            import subprocess
            p2 = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration", "-of", "csv=p=0", str(out)],
                                capture_output=True, text=True)
            size = f"{out.stat().st_size}B/{p2.stdout.strip()}s"
        except Exception:
            size = "-1"
        return (name, "OK", f"audio={size} result={str(r['data'])[-90:]}",
                time.time() - t0)
    except Exception as e:
        return (name, "FAIL", str(e)[:180], time.time() - t0)


if __name__ == "__main__":
    B = gm.BACKENDS
    jobs = [
        ("A_40s_4step", B[0], 40, 4, 700000001),
        ("B_40s_4step", B[1], 40, 4, 700000002),
    ]
    if len(sys.argv) > 1:
        d, s = int(sys.argv[1]), int(sys.argv[2])
        jobs = [(f"A_{d}s_{s}step", B[0], d, s, 700000011),
                (f"B_{d}s_{s}step", B[1], d, s, 700000012)]
    print("jobs:", [(j[0], j[2], j[3]) for j in jobs], flush=True)
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        for name, st, msg, secs in ex.map(run, jobs):
            print(f"{st:5s} {name:16s} {secs:7.1f}s {msg}", flush=True)
