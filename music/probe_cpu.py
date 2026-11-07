#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 cpu-basic（不消耗 ZeroGPU 匿名配额）Space 是否真能出音频。"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import ssl
import urllib.request
from pathlib import Path

import space_client as sc
from probe_generate import build_params, pick_endpoint

HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
OP = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=CTX))
UA = {"User-Agent": "Mozilla/5.0"}
PROMPT = "calm Chinese jinghu erhu instrumental melody, no drums, instrumental only"


def host_of(sid: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", sid.lower().replace("/", "-"))
    return "https://" + re.sub(r"-+", "-", slug).strip("-") + ".hf.space"


def work(r: dict):
    sid = r["id"]
    sub = r.get("subdomain")
    base = "https://" + sub + ".hf.space" if sub else host_of(sid)
    out = {"id": sid, "hardware": r.get("hardware"), "base": base}
    try:
        # 先唤醒（cpu-basic 休眠时第一次请求会 503）
        try:
            OP.open(urllib.request.Request(base + "/", headers=UA), timeout=8).read(200)
        except Exception:
            pass
        d = json.loads(OP.open(urllib.request.Request(base + "/gradio_api/info", headers=UA),
                               timeout=15).read())
        ep, spec = pick_endpoint(d)
        if not ep:
            out["status"] = "no-endpoint"
            out["eps"] = list((d.get("named_endpoints") or {}).keys())[:12]
            return out
        params = build_params(spec)
        out["ep"], out["nparams"] = ep, len(params)
        res = sc.call_space(base, ep, params, timeout=180, verbose=False)
        out["status"], out["secs"] = "complete", round(res["secs"], 1)
        out["preview"] = json.dumps(res["data"], ensure_ascii=False)[:260]
    except Exception as e:
        out["status"] = "fail"
        out["err"] = f"{type(e).__name__}: {str(e)[:150]}"
    return out


def main():
    hw = json.loads((TMP / "space_hardware.json").read_text(encoding="utf-8"))
    targets = [r for r in hw if r.get("hardware") and "zero" not in r["hardware"]]
    # 已知失败/无端点的 v1.5 壳子可以再试一次（唤醒后可能不同）
    print(f"testing {len(targets)} cpu-basic spaces ...", flush=True)
    out = []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for r in ex.map(work, targets):
            out.append(r)
            print(f"  {r['status']:<12} {r['id']:<48} ep={r.get('ep','-')} "
                  f"t={r.get('secs','-')} {str(r.get('err',r.get('preview','')))[:100]}",
                  flush=True)
    (TMP / "cpu_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    good = [r for r in out if r["status"] == "complete"]
    print(f"\n{len(good)} cpu-basic spaces can generate audio", flush=True)
    for r in good:
        print("  WORKING:", r["id"], r["ep"], r.get("secs"), flush=True)


if __name__ == "__main__":
    main()
