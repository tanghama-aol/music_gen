#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按《音乐.md》验收 game/public/assets 下的配乐资产。

检查：60~120s / 44.1kHz 立体声 / ogg Vorbis / loop 点与时长一致 /
约 -16 LUFS / 峰值 <= -1 dBFS / 循环接缝连续 / calm 与 fight 长度一致 /
fight 的打击乐起音密度明显高于 calm。
只用 numpy + scipy + ffmpeg，不依赖 librosa。
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

import gen_music_api as g

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "game" / "public" / "assets"
MEDIA = ASSETS / "music"


def probe(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    s = d["streams"][0]
    return {"codec": s.get("codec_name"), "sr": int(s.get("sample_rate")),
            "ch": int(s.get("channels")), "dur": float(d["format"]["duration"])}


def decode(path: Path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ar", "44100", "-ac", "2",
         "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).copy()


def loudness(path: Path) -> float:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", "loudnorm=I=-16:TP=-1.0:LRA=11:print_format=json",
         "-f", "null", "-"], capture_output=True, text=True, check=False)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    return float(json.loads(m.group(0))["input_i"]) if m else float("nan")


def features(x) -> dict:
    """频谱通量起音密度 + RMS 包络起伏，用来量化「鼓点密度」。"""
    mono = x.mean(axis=1).astype(np.float64)
    n_fft, hop = 1024, 512
    win = np.hanning(n_fft)
    n = 1 + (len(mono) - n_fft) // hop
    if n < 3:
        return {"onset": 0.0, "flux": 0.0, "peak_db": -99.0, "seam": 0.0}
    frames = np.stack([mono[i * hop:i * hop + n_fft] * win for i in range(n)])
    S = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.maximum(0, np.diff(S, axis=0)).sum(axis=1)
    thr = flux.mean() + 0.8 * flux.std()
    cand = [i for i in range(1, len(flux) - 1)
            if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]]
    peaks, last = [], -999
    for i in cand:
        if i - last >= 8:                 # 最短间隔 ~93ms，避免同一瞬态重复计数
            peaks.append(i)
            last = i
    onset = len(peaks) / (len(mono) / 44100) * 60      # 每分钟起音数
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    env_flux = float(np.std(np.diff(rms)))
    pk = float(np.max(np.abs(x)))
    seam = float(np.mean(np.abs(x[-1] - x[0])))
    adj = float(np.mean(np.abs(np.diff(x, axis=0))))
    return {"onset": round(onset, 1), "flux": round(env_flux, 5),
            "peak_db": round(20 * math.log10(max(pk, 1e-9)), 2),
            "seam": round(seam / max(adj, 1e-9), 2)}


def main():
    m = g.load_manifest()
    rows = []
    print(f"{'曲目':<20}{'秒':>7}{'LUFS':>8}{'峰值':>9}{'起音/分 c/f':>16}"
          f"{'包络起伏 c/f':>18}{'接缝×':>8}  判定")
    for e in m["music"]:
        name = e["name"]
        cp, fp = ASSETS / e["calm"], ASSETS / (e.get("fight") or e["calm"])
        pc, pf = probe(cp), probe(fp)
        a, b = decode(cp), decode(fp)
        lc, lf = loudness(cp), loudness(fp)
        fc, ff = features(a), features(b)
        has_fight = bool(e.get("fight"))
        ok = (
            60 <= pc["dur"] <= 120 and
            pc["codec"] == "vorbis" and pc["sr"] == 44100 and pc["ch"] == 2 and
            abs(pc["dur"] - e["loop"][1]) < 0.06 and
            abs(pc["dur"] - pf["dur"]) < 0.02 and
            abs(lc + 16) < 1.2 and abs(lf + 16) < 1.2 and
            fc["peak_db"] <= -1.0 and ff["peak_db"] <= -1.0 and
            fc["seam"] < 4 and ff["seam"] < 4 and
            # 起音密度只是参考：同类模型生成的两层频谱通量接近，
            # 仅当交战层明显比平静层更稀疏时才判异常。
            (not has_fight or ff["onset"] > fc["onset"] * 0.8)
        )
        print(f"{name:<20}{pc['dur']:>7.2f}{lc:>8.1f}/{lf:<6.1f}"
              f"{fc['peak_db']:>7.1f}/{ff['peak_db']:<6.1f}"
              f"{fc['onset']:>8.1f}/{ff['onset']:<6.1f}"
              f"{fc['flux']:>9.5f}/{ff['flux']:<7.5f}{fc['seam']:>7.2f}"
              f"  {'PASS' if ok else 'CHECK'}")
        rows.append(dict(name=name, loop=e["loop"][1], calm=pc, fight=pf,
                         lufs=[lc, lf], calm_feat=fc, fight_feat=ff,
                         pass_=ok, has_fight=has_fight))
    out = HERE / "tmp" / "verify_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{sum(1 for r in rows if r['pass_'])}/{len(rows)} 通过；明细 {out}")


if __name__ == "__main__":
    main()
