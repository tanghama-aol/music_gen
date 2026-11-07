#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用 Gradio 音乐生成 Space 客户端。

提交 /gradio_api/call/<endpoint> -> SSE 轮询 -> 从返回的 FileData 下载音频。
对 ZeroGPU 配额耗尽（event: error / data: null）会如实抛出，由上层切换后端。
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.request
from pathlib import Path

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def opener(proxy: dict | None = None):
    return urllib.request.build_opener(
        urllib.request.ProxyHandler(proxy or {}),
        urllib.request.HTTPSHandler(context=CTX),
    )


UA = {"User-Agent": "Mozilla/5.0"}


def _find_audio_url(obj) -> str | None:
    """递归找返回值里的第一个音频 FileData url/path。"""
    if isinstance(obj, dict):
        u = obj.get("url") or obj.get("path")
        name = (obj.get("orig_name") or str(u or "")).lower()
        if u and re.search(r"\.(wav|mp3|flac|ogg|m4a)(\?|$)", name):
            if str(u).startswith("/"):
                return None  # 需要 base 才能拼，交给调用方
            return str(u)
        for v in obj.values():
            r = _find_audio_url(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_audio_url(v)
            if r:
                return r
    return None


def call_space(base: str, endpoint: str, params: list, *, timeout: int = 900,
               proxy: dict | None = None, verbose: bool = True) -> dict:
    """返回 {data, secs, event_id}；data 是 complete 事件解析后的 list。"""
    op = opener(proxy)
    call = f"{base}/gradio_api/call/{endpoint.lstrip('/')}"
    body = json.dumps({"data": params}, ensure_ascii=False).encode("utf-8")
    hdr = dict(UA, **{"Content-Type": "application/json"})
    t0 = time.time()
    r = op.open(urllib.request.Request(call, data=body, headers=hdr), timeout=60)
    eid = (json.loads(r.read().decode("utf-8")) or {}).get("event_id")
    if not eid:
        raise RuntimeError("未拿到 event_id")

    event, last = None, None
    last_phase = None
    with op.open(urllib.request.Request(call + "/" + eid, headers=UA), timeout=timeout) as s:
        for raw in s:
            if time.time() - t0 > timeout:
                raise TimeoutError(f"SSE 超过 {timeout}s")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                last = line[5:].strip()
            elif line == "":
                if event == "progress" and verbose:
                    try:
                        pd = json.loads(last)
                        desc = ""
                        if isinstance(pd, list) and pd and isinstance(pd[0], dict):
                            desc = str(pd[0].get("desc") or "")
                        phase = desc.split(" (job")[0]
                        if phase and phase != last_phase:
                            print(f"      · {time.time()-t0:6.0f}s {phase}", flush=True)
                            last_phase = phase
                    except Exception:
                        pass
                elif event == "error":
                    raise RuntimeError(f"模型返回 error: {str(last)[:300]}")
                elif event == "complete":
                    if verbose:
                        print(f"    生成完成，耗时 {time.time()-t0:.1f}s", flush=True)
                    return {"data": json.loads(last), "secs": time.time() - t0,
                            "event_id": eid}
                event, last = None, None
    raise RuntimeError("SSE 流提前结束，未收到 complete")


def download_audio(base: str, data, out: Path, *, proxy: dict | None = None,
                   timeout: int = 180) -> Path:
    """从 complete 的 data 里取出音频并落盘。"""
    op = opener(proxy)
    url = _find_audio_url(data)
    if url is None:
        # 尝试找任意 gradio file= 路径
        blob = json.dumps(data, ensure_ascii=False)
        m = re.search(r'"(?:url|path)"\s*:\s*"([^"]+\.(?:wav|mp3|flac|ogg)[^"]*)"', blob)
        if not m:
            raise RuntimeError("返回值里找不到音频文件：" + blob[:300])
        url = m.group(1)
    if url.startswith("/"):
        url = base + "/gradio_api/file=" + url
    elif not url.startswith("http"):
        url = base + "/gradio_api/file=" + url
    b = op.open(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    if len(b) < 10_000:
        raise RuntimeError(f"音频过小：{len(b)} bytes (url={url[:120]})")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b)
    return out
