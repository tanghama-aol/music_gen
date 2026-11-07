#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""穷举 21 个 RUNNING 的 ZeroGPU 音乐 Space × 3 条网络出口，用 10s/8steps 最小任务
确认匿名配额是否真的全局耗尽；只要有一个能用，就比 CPU 路线快一个数量级。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import time
from pathlib import Path

import gen_music_api as g
import probe_generate as pg
import space_client as sc

HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"

PATHS = [
    ("direct", None),
    ("17890", {"http": "http://127.0.0.1:17890", "https": "http://127.0.0.1:17890"}),
    ("62893", {"http": "http://127.0.0.1:62893", "https": "http://127.0.0.1:62893"}),
]

PROMPT = "traditional Chinese instrumental BGM, calm erhu melody, no drums, instrumental"


def get_info(base, proxy):
    import urllib.request
    op = sc.opener(proxy)
    return json.loads(op.open(urllib.request.Request(
        base + "/gradio_api/info", headers=sc.UA), timeout=20).read().decode("utf-8", "replace"))


def params_for(ep, spec, base):
    if ep == "/__call__":
        return g.build_params(PROMPT, "[inst]", 10, "123456", steps=8)
    return pg.build_params(spec)


def one(sid, sub, pname, proxy):
    base = "https://" + sub + ".hf.space"
    t0 = time.time()
    try:
        info = get_info(base, proxy)
        eps = {k: (v[0] if isinstance(v, list) and v else ({} if isinstance(v, list) else (v or {})))
               for k, v in (info.get("named_endpoints") or {}).items()}
        info["named_endpoints"] = eps
        ep, spec = pg.pick_endpoint(info)
        if not ep:
            return (sid, pname, "no-endpoint", "", 0)
        if isinstance(spec, list):
            spec = spec[0] if spec else {}
        params = params_for(ep, spec or {}, base)
        r = sc.call_space(base, ep, params, timeout=70, proxy=proxy, verbose=False)
        return (sid, pname, "OK", str(r["data"])[:120], time.time() - t0)
    except Exception as e:
        return (sid, pname, "FAIL", str(e)[:170], time.time() - t0)


def main():
    d = json.loads((TMP / "space_hardware.json").read_text(encoding="utf-8"))
    zs = [x for x in d if x.get("stage") == "RUNNING" and x.get("hardware") == "zero-a10g"]
    jobs = [(x["id"], x["subdomain"], pn, px) for x in zs for pn, px in PATHS]
    print(f"probing {len(zs)} zero-gpu spaces x {len(PATHS)} paths = {len(jobs)}", flush=True)
    out = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for sid, pn, st, msg, secs in ex.map(lambda j: one(*j), jobs):
            out.append(dict(id=sid, path=pn, status=st, msg=msg, secs=round(secs, 1)))
            if st != "FAIL" or "quota" in msg.lower():
                print(f"  {st:12s} {pn:7s} {sid:52s} {secs:6.1f}s {msg[:110]}", flush=True)
    (TMP / "zerogpu_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    oks = [r for r in out if r["status"] == "OK"]
    print(f"\nOK={len(oks)} / {len(out)}", flush=True)
    for r in oks:
        print("  WORKING:", r["id"], r["path"], r["msg"][:90], flush=True)
    print("sample errors:", flush=True)
    for r in out[:8]:
        print("  ", r["path"], r["id"][:40], r["msg"][:110], flush=True)


if __name__ == "__main__":
    main()
