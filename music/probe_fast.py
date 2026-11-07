#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测更快的无凭据音乐生成后端：
1) timefractal/ACE-Step-Turbo-Music-Gen (cpu-basic, turbo 8 steps)
2) 标准 ACE-Step v1.5 UI 的 /generation_wrapper (cpu-basic)
3) ACE-Step v1.5 官方 ZeroGPU 是否恢复配额
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import time
from pathlib import Path

import space_client as sc
from probe_generate import build_params, fetch_json

HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"
TMP.mkdir(exist_ok=True)

PROMPT = ("Chinese folk instrumental BGM, gentle erhu melody, dizi flute, "
          "slow tempo, no drums, seamless loop, instrumental")

TASKS = [
    ("turbo-30s", "https://timefractal-ace-step-turbo-music-gen.hf.space",
     "/generate_music", [PROMPT, "[Instrumental]", 30, 12345, 8], 900),
    ("v15ui-baseta", "https://baseta-ace-step-v1-5.hf.space",
     "/generation_wrapper", None, 900),
    ("zero-15s", "https://ace-step-ace-step-v1-5.hf.space",
     "/generation_wrapper", None, 180),
]


def run(t):
    name, base, ep, params, timeout = t
    t0 = time.time()
    try:
        if params is None and ep == "/generation_wrapper":
            info = fetch_json(base + "/gradio_api/info", timeout=20)
            spec = (info.get("named_endpoints") or {}).get(ep)
            if isinstance(spec, list):
                spec = spec[0] if spec else {}
            params = build_params(spec)
        if params is None:
            return name, "skip", "no params", 0
        r = sc.call_space(base, ep, params, timeout=timeout, verbose=False)
        out = TMP / ("probe_" + name + ".mp3")
        sc.download_audio(base, r["data"], out, timeout=120)
        return name, "OK", f"{out.stat().st_size} bytes", time.time() - t0
    except Exception as e:
        return name, "FAIL", str(e)[:220], time.time() - t0


if __name__ == "__main__":
    print("fast backend probe", flush=True)
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for name, st, msg, secs in ex.map(run, TASKS):
            print(f"{st:5s} {name:20s} {secs:7.1f}s  {msg}", flush=True)
