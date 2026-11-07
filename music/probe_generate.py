#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对候选公开音乐生成 Space 发起最小化生成任务，找出真正能出音频的端点。

从每个 Space 的 /gradio_api/info 自动读取参数 schema，用 parameter_default 构造
完整参数表，再覆盖提示词 / 时长 / 步数，避免因参数个数不对被拒。
结果写 tmp/generate_probe.json。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import ssl
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
OP = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=CTX))

PROMPT = "traditional Chinese jinghu erhu instrumental, calm, no drums, instrumental only"
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def fetch_json(url: str, timeout: int = 15):
    return json.loads(OP.open(urllib.request.Request(url, headers=UA), timeout=timeout).read())


def default_for(p: dict):
    if p.get("parameter_has_default"):
        return p.get("parameter_default")
    t = p.get("type")
    if isinstance(t, dict):
        if "enum" in t and t["enum"]:
            return t["enum"][0]
        t = t.get("type")
    if t == "string":
        return ""
    if t == "number":
        return 0
    if t == "boolean":
        return False
    if t == "array":
        return []
    return None


def pick_endpoint(info: dict):
    eps = info.get("named_endpoints") or {}
    for prefer in ("/generation_wrapper", "/generate_music", "/predict_full",
                   "/predict_batched", "/predict", "/__call__"):
        if prefer in eps:
            return prefer, eps[prefer]
    cand = [(k, v) for k, v in eps.items()
            if len(v.get("parameters") or []) >= 3
            and "capture" not in k and "training" not in k]
    if not cand:
        return None, None
    return max(cand, key=lambda kv: len(kv[1].get("parameters") or []))


def build_params(spec: dict) -> list:
    ps = spec.get("parameters") or []
    data = [default_for(p) for p in ps]
    names = [(p.get("parameter_name") or "").lower() for p in ps]

    def set_named(*keys, value):
        for i, n in enumerate(names):
            if any(k == n for k in keys):
                data[i] = value

    # 通用：按名字覆盖
    set_named("prompt", "text", "caption", "captions", "simple_query_input", value=PROMPT)
    set_named("lyrics", value="[inst]")
    set_named("duration", "audio_duration", value=15)
    set_named("inference_steps", "num_inference_steps", "infer_step", value=8)
    set_named("batch_size", value=1)

    # ACE-Step v1.5 clone 的 /generation_wrapper：参数名是 param_N，按位置覆盖
    if len(data) >= 45:
        data[0] = "acestep-v15-turbo"      # selected_model
        data[1] = "simple"                  # generation_mode
        data[2] = PROMPT                    # simple_query_input
        data[4] = PROMPT                    # captions
        data[5] = "[inst]"                  # lyrics
        data[13] = "-1"                     # seed
        data[15] = 15                       # duration
        data[16] = 1                        # batch size
        data[30] = "mp3"
    return data


def sse_wait(url: str, timeout: int = 150):
    event, buf = None, []
    t0 = time.time()
    with OP.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                 timeout=timeout) as r:
        for raw in r:
            if time.time() - t0 > timeout:
                return "timeout", "overall deadline"
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                buf.append(line[5:].strip())
            elif line == "" and event in ("complete", "error"):
                d = "\n".join(buf)
                return event, d[:400]
    return "eof", ""


def probe(entry: dict) -> dict:
    sid = entry["id"]
    okprobe = next((p for p in entry["probes"] if p["ok"]), None)
    if not okprobe:
        return {"id": sid, "status": "no-info"}
    base = entry["host"]
    try:
        info = fetch_json(base + "/gradio_api/info", timeout=15)
        ep, spec = pick_endpoint(info)
        if not ep:
            return {"id": sid, "status": "no-endpoint"}
        params = build_params(spec)
        call = f"{base}/gradio_api/call/{ep.lstrip('/')}"
        body = json.dumps({"data": params}, ensure_ascii=False).encode()
        t0 = time.time()
        r = OP.open(urllib.request.Request(call, data=body, headers=UA), timeout=30)
        eid = (json.loads(r.read().decode()) or {}).get("event_id")
        if not eid:
            return {"id": sid, "ep": ep, "status": "no-event-id"}
        ev, data = sse_wait(call + "/" + eid, timeout=150)
        return {"id": sid, "ep": ep, "nparams": len(params), "status": ev,
                "secs": round(time.time() - t0, 1), "data": data[:300]}
    except Exception as e:
        return {"id": sid, "status": "exception", "err": f"{type(e).__name__}: {str(e)[:120]}"}


def main():
    entries = json.loads((TMP / "space_probe.json").read_text(encoding="utf-8"))
    entries = [e for e in entries if any(p["ok"] for p in e["probes"])]
    print(f"testing generation on {len(entries)} live spaces ...", flush=True)
    out = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(probe, entries):
            out.append(r)
            print(f"  {r['status']:<12} {r['id']:<46} ep={r.get('ep','-')} "
                  f"n={r.get('nparams','-')} t={r.get('secs','-')} "
                  f"{str(r.get('data', r.get('err','')))[:110]}", flush=True)
    (TMP / "generate_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    good = [r for r in out if r["status"] == "complete"]
    print(f"\n{len(good)} spaces can actually generate audio", flush=True)
    for r in good:
        print("  WORKING:", r["id"], r["ep"], flush=True)


if __name__ == "__main__":
    main()
