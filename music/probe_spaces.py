#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测公开 ACE-Step / 音乐生成 Gradio Space，找出仍可免费调用的推理端点。

背景：官方 ACE-Step Space 走 ZeroGPU，匿名配额与出口 IP 绑定，耗尽后所有
zero-a10g Space 都会立刻返回 `event: error / data: null`。但由 Space 拥有者
付费的「专属 GPU / CPU 升级」实例不消耗匿名配额，仍可匿名调用。

本脚本：
  1. 读取 tmp/spaces_*.json（由 hf-mirror.com/api/spaces 取得）里的候选 Space
  2. 对每条出口探测 https://<owner>-<name>.hf.space/gradio_api/info
  3. 记录端点名、参数个数、疑似 ACE-Step v1（22 参）还是 v1.5（49 参）
  4. 结果写 tmp/space_probe.json
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import ssl
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"

PATHS = [
    ("direct", {}),
    ("17890", {"http": "http://127.0.0.1:17890", "https": "http://127.0.0.1:17890"}),
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def opener(proxy: dict):
    return urllib.request.build_opener(
        urllib.request.ProxyHandler(proxy),
        urllib.request.HTTPSHandler(context=CTX),
    )


def host_of(space_id: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", space_id.lower().replace("/", "-"))
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"https://{slug}.hf.space"


def info(base: str, name: str, proxy: dict, timeout: int = 7) -> dict:
    op = opener(proxy)
    u = base + "/gradio_api/info"
    try:
        r = op.open(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}),
                    timeout=timeout)
        d = json.loads(r.read().decode("utf-8"))
        eps = []
        for group in ("named_endpoints", "unnamed_endpoints"):
            for path, spec in (d.get(group) or {}).items():
                # /gradio_api/info 里每个端点是 dict，也可能被写成 list
                if isinstance(spec, list):
                    spec = spec[0] if spec else {}
                if not isinstance(spec, dict):
                    spec = {}
                n = len(spec.get("parameters") or [])
                eps.append([str(path), n])
        return {"ok": True, "via": name, "endpoints": eps}
    except Exception as e:
        return {"ok": False, "via": name, "err": f"{type(e).__name__}: {str(e)[:90]}"}


def probe_one(space_id: str) -> dict:
    base = host_of(space_id)
    out = {"id": space_id, "host": base, "probes": []}
    for name, proxy in PATHS:
        out["probes"].append(info(base, name, proxy))
        if out["probes"][-1]["ok"]:
            break
    return out


def main():
    ids = []
    for f in TMP.glob("spaces_*.json"):
        try:
            for s in json.loads(f.read_text(encoding="utf-8")):
                if s.get("id"):
                    ids.append(s["id"])
        except Exception:
            pass
    # 补充官方 / 已知候选
    ids += ["ACE-Step/ACE-Step", "ACE-Step/Ace-Step-v1.5", "facebook/MusicGen",
            "LububMusicAi/ACE-Step-Custom", "Gamahea/ACE-Step-Custom",
            "guysss/ACE-Step", "haoheliu/audioldm2-text2audio-text2music",
            "fffiloni/text-2-music", "fffiloni/audioldm2-text2audio-text2music-API"]
    # 只保留可能与音乐生成相关的名字，避免探测分类/训练类 Space 浪费时间
    keys = ("ace", "step", "music", "song", "audio", "suno", "bgm", "lyric")
    ids = [i for i in dict.fromkeys(ids)
           if any(k in i.lower() for k in keys)][:90]

    print(f"probing {len(ids)} spaces ...", flush=True)
    results = []
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for r in ex.map(probe_one, ids):
            results.append(r)
            ok = next((p for p in r["probes"] if p["ok"]), None)
            if ok:
                eps = [f"{p[0]}({p[1]})" for p in ok["endpoints"]][:6]
                print(f"  OK  {r['id']:<48} via {ok['via']:<7} eps={eps}", flush=True)
            else:
                print(f"  --  {r['id']:<48} {r['probes'][-1].get('err','')[:60]}", flush=True)

    (TMP / "space_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    usable = [r for r in results if any(p["ok"] and p["endpoints"] for p in r["probes"])]
    print(f"\n{len(usable)} spaces expose API endpoints -> tmp/space_probe.json", flush=True)


if __name__ == "__main__":
    main()
