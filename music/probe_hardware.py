#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查每个候选 Space 的 runtime.hardware，筛出不消耗 ZeroGPU 匿名配额的实例。

ZeroGPU（zero-a10g）匿名配额与出口 IP 绑定，耗尽后所有 zero-a10g Space 都
立刻返回 error:null。而 cpu-* / t4-* / a10g-* 等由 Space 拥有者付费的实例
不受该配额限制，仍可匿名调用。

结果写 tmp/space_hardware.json。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"
PROXY = "http://127.0.0.1:17890"


def query(sid: str):
    u = f"https://huggingface.co/api/spaces/{sid}"
    try:
        p = subprocess.run(
            ["curl", "-s", "--max-time", "12", "-x", PROXY, u],
            capture_output=True, timeout=15)
        d = json.loads(p.stdout.decode("utf-8", "replace"))
        rt = d.get("runtime") or {}
        hw = rt.get("hardware") or {}
        return {"id": sid, "stage": rt.get("stage"), "hardware": hw.get("current"),
                "requested": hw.get("requested"), "sdk": d.get("sdk"),
                "subdomain": d.get("subdomain")}
    except Exception as e:
        return {"id": sid, "err": type(e).__name__}


def main():
    allsp = json.loads((TMP / "spaces_all.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in allsp if s.get("id")]
    keys = ("ace", "step", "music", "song", "audio", "bgm", "suno", "udio",
            "composer", "instrument", "melod", "sound")
    ids = [i for i in dict.fromkeys(ids) if any(k in i.lower() for k in keys)]
    print(f"querying hardware for {len(ids)} spaces ...", flush=True)

    out = []
    with cf.ThreadPoolExecutor(max_workers=20) as ex:
        for r in ex.map(query, ids):
            out.append(r)
    (TMP / "space_hardware.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    from collections import Counter
    print("hardware distribution:", Counter(r.get("hardware") for r in out), flush=True)
    non_zero = [r for r in out if r.get("hardware") and "zero" not in r["hardware"]]
    print(f"\n{len(non_zero)} NON-ZeroGPU spaces:", flush=True)
    for r in non_zero:
        print(f"  {r['hardware']:<14} {r.get('stage',''):<10} {r['id']}", flush=True)


if __name__ == "__main__":
    main()
