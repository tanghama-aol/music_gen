#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收「部分经典人声唱腔」测试曲。

除常规资产契约（ogg Vorbis / 44.1kHz 立体声 / 约 -16 LUFS / 峰值 <= -1 dBFS /
无缝循环）外，重点验证两件事：

1. lyrics 是否真的触发了人声分支：段 B（带唱词）相对段 A（[Instrumental]）
   在 1–4 kHz 人声频段与 3–10 Hz 音节调制上有明显抬升，且波形相关下降。
2. 唱腔是否只是「部分」：把成品按时间切成四等份，人声指标应当集中在
   中段/后半（段 B 的 [verse]/[chorus]），而曲首与曲尾仍接近纯器乐。

客观指标只作参考，最终以试听为准。
"""
from __future__ import annotations

import json
from pathlib import Path

import gen_music_api as g
import gen_vocal_test as vt
import verify_music as vm

HERE = Path(__file__).resolve().parent
REPORT = vt.REPORT
OUT = vt.OUT


def bands(x):
    return {"band14": round(vt.band_ratio(x), 4),
            "syll": round(vt.syllable_modulation(x), 4),
            "upper": round(vt.upper_ratio(x), 4)}


def main():
    if not OUT.exists():
        raise SystemExit(f"缺少成品 {OUT}，请先运行 gen_vocal_test.py")
    rep = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}

    p = vm.probe(OUT)
    x = vm.decode(OUT)
    lufs = vm.loudness(OUT)
    f = vm.features(x)

    # 成品四等份：定位唱腔出现的时间段
    q = []
    for i in range(4):
        part = x[i * len(x) // 4:(i + 1) * len(x) // 4]
        d = bands(part)
        d["quarter"] = f"Q{i + 1} {i * 25}-{(i + 1) * 25}%"
        q.append(d)

    # A/B 原始片段对照
    a = g.decode_mp3(vt.seg_file("inst"))
    b = g.decode_mp3(vt.seg_file("vocal"))
    ab_a, ab_b = bands(a), bands(b)

    band_gain = ab_b["band14"] - ab_a["band14"]
    syll_gain = ab_b["syll"] - ab_a["syll"]
    upper_gain = ab_b["upper"] - ab_a["upper"]
    peak_q = max(q, key=lambda d: d["upper"])
    edge = (q[0]["upper"] + q[-1]["upper"]) / 2

    contract_ok = (
        p["codec"] == "vorbis" and p["sr"] == 44100 and p["ch"] == 2 and
        abs(p["dur"] - rep.get("loop_seconds", p["dur"])) < 0.06 and
        abs(lufs + 16) < 1.2 and f["peak_db"] <= -1.0 and f["seam"] < 4
    )
    # 「触发人声」不作硬性 PASS：4 steps 的 CPU 推理不保证每次都出清晰唱腔，
    # 只用指标给出提示，结论交给试听。
    vocal_hint = (rep.get("upper_harmonics_peak_vocal", 0) >
                  rep.get("upper_harmonics_peak_inst", 0) * 1.5 or
                  rep.get("waveform_correlation", 1.0) < 0.5)
    partial_hint = peak_q["upper"] > edge * 1.3

    result = {
        "file": str(OUT), "probe": p, "lufs": round(lufs, 2),
        "peak_db": f["peak_db"], "seam": f["seam"],
        "loop_seconds": rep.get("loop_seconds"),
        "loop_boundary_seconds": rep.get("loop_boundary_seconds"),
        "structure": rep.get("structure"),
        "segments": [rep.get("segment_seconds_inst"), rep.get("segment_seconds_vocal")],
        "declick_fixes": rep.get("declick_fixes"),
        "ab_inst": ab_a, "ab_vocal": ab_b,
        "band_gain": round(band_gain, 4), "syll_gain": round(syll_gain, 4),
        "upper_gain": round(upper_gain, 4),
        "waveform_correlation": rep.get("waveform_correlation"),
        "quarters": q, "vocal_peak_quarter": peak_q["quarter"],
        "contract_pass": contract_ok,
        "vocal_hint": vocal_hint, "partial_hint": partial_hint,
    }
    (g.TMP / "vocal_test_verify.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"成品 {p['dur']:.2f}s | {p['codec']} {p['sr']}Hz {p['ch']}ch | "
          f"{lufs:.1f} LUFS | 峰值 {f['peak_db']:.2f} dBFS | 接缝×{f['seam']:.2f}")
    print(f"契约验收：{'PASS' if contract_ok else 'CHECK'}")
    print(f"\nA/B 对照（同 seed，仅 lyrics 不同）")
    print(f"  1–4kHz    {ab_a['band14']:.4f} → {ab_b['band14']:.4f}  ({band_gain:+.4f})")
    print(f"  音节调制  {ab_a['syll']:.4f} → {ab_b['syll']:.4f}  ({syll_gain:+.4f})")
    print(f"  上谐波比  {ab_a['upper']:.4f} → {ab_b['upper']:.4f}  ({upper_gain:+.4f})")
    print(f"  上谐波峰值 {rep.get('upper_harmonics_peak_inst')} → "
          f"{rep.get('upper_harmonics_peak_vocal')}")
    print(f"  波形相关  {rep.get('waveform_correlation')}")
    print(f"  人声分支提示：{'有' if vocal_hint else '弱（需试听确认）'}")
    print(f"\n成品四等份（上谐波比 / 音节调制）")
    for d in q:
        print(f"  {d['quarter']:<14} upper={d['upper']:.4f}  "
              f"band14={d['band14']:.4f}  syll={d['syll']:.4f}")
    print(f"  唱腔峰值段：{peak_q['quarter']} | 首尾均值 {edge:.4f} | "
          f"部分唱腔提示：{'是' if partial_hint else '否（需试听确认）'}")
    print(f"\n明细 {g.TMP / 'vocal_test_verify.json'}")


if __name__ == "__main__":
    main()
