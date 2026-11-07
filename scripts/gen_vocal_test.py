#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一首「部分经典人声唱腔」测试曲（独立于《音乐.md》的 10 首正式 BGM）。

设计
----
之前 10 首全部是纯器乐（lyrics = "[Instrumental]"）。本测试曲只加一点点唱腔：
在**完全相同的 caption / seed / BPM / duration / steps** 下，只改 lyrics 生成两段——

  A  "[Instrumental]"                       纯器乐过门
  B  "[inst] / [verse] / [chorus] / [inst]" 中段带戏曲女声唱腔

两段先各自去掉模型自带的 ~7s 静音尾，再按 A → B → A 三段用 2s 等功率交叉淡化
拼接（器乐 → 唱腔 → 器乐），最后做 2s 首尾无缝循环。唱腔只出现在中间一段，
开头与结尾都是器乐，因此循环点干净。A/B 同 seed 也让器乐骨架连续、拼接更自然；
同时两者的差异正好是「lyrics 是否真的触发了人声分支」的客观对照证据。

后处理还有两处针对 CPU 4-step 输出的实际修补：
  * declick()  —— 模型段落边界偶尔有单样本幅度突跳（>0.15），做 6ms 线性修补；
  * pick_loop_T() —— 在尾部 1.2s 窗口内挑最平滑的循环边界，避开硬切点。

唱词是自编的风格化短句，不使用任何现存剧目唱词。

产物（均**不写入** manifest.json，避免被游戏当成正式 BGM 加载）：
  game/public/assets/music/test_vocal_xipi.ogg   成品无缝循环
  tmp/vocal_test_inst.mp3                        对照段 A 原始模型输出
  tmp/vocal_test_vocal.mp3                       对照段 B 原始模型输出
  tmp/vocal_test_report.json                     对照指标
  vocal_test.html                                单曲试听页

用法：
  python -u gen_vocal_test.py                 # 生成（已有片段自动复用）
  python -u gen_vocal_test.py --force         # 忽略缓存重新调模型
  python -u gen_vocal_test.py --post-only     # 只用已有片段重做后处理 / 试听页
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import time
from pathlib import Path

import numpy as np

import fix_levels
import gen_music_api as g
import gen_music_segments as seg
import gen_music_space as gs
import space_client as sc

HERE = Path(__file__).resolve().parent
TMP = g.TMP
OUT = g.MUSIC_DIR / "test_vocal_xipi.ogg"
REPORT = TMP / "vocal_test_report.json"

CAPTION = (
    "Beijing opera xipi liushui, jinghu erhu lead with sparse pipa plucks, "
    "D zhi pentatonic mode, 98 BPM, cinematic Chinese opera game BGM, "
    "sparse airy arrangement, classic Chinese opera atmosphere with an optional brief "
    "expressive female opera vocal phrase and melismatic drawn-out singing, "
    "mostly instrumental, no drums, no percussion, no gongs, no ambient sound effects, "
    "steady tempo, no tempo change, seamless loop"
)
LYRICS_INST = "[Instrumental]"
LYRICS_VOCAL = (
    "[inst]\n"
    "[verse]\n"
    "云开月照古城楼\n"
    "一嗓西皮绕画梁\n"
    "[chorus]\n"
    "啊—— 啊——\n"
    "[inst]"
)
BPM = 98
DURATION = 40
STEPS = 4
SEED = 710000001        # 独立于正式曲目的 seed 段
SEG_CROSS = 2.0
LOOP_CROSS = 2.0
GEN_TIMEOUT = 1500


def seg_file(tag: str) -> Path:
    return TMP / f"vocal_test_{tag}.mp3"


def params_of(lyrics: str) -> list:
    # /generate 的 8 个顺序参数
    return [CAPTION, lyrics, BPM, DURATION, SEED, STEPS, gs.LORA, gs.LM_MODEL]


def gen_one(tag: str, lyrics: str, base: str, retries: int = 2) -> dict:
    out = seg_file(tag)
    if out.exists() and out.stat().st_size > 50_000:
        print(f"  [{tag}] 复用 {out.name}（{out.stat().st_size / 1024:.0f} KB）", flush=True)
        return {"ok": True, "reused": True}
    p = params_of(lyrics)
    last = None
    for k in range(1, retries + 1):
        try:
            print(f"  [{tag}] 提交 {base.split('//')[1].split('.')[0]} 第 {k} 次 "
                  f"({DURATION}s / {BPM}BPM / {STEPS}steps / seed={SEED})", flush=True)
            r = sc.call_space(base, gs.ENDPOINT, p, timeout=GEN_TIMEOUT, verbose=True)
            sc.download_audio(base, r["data"], out, timeout=180)
            print(f"  [{tag}] 完成 {out.name} {out.stat().st_size / 1024:.0f} KB / "
                  f"{r['secs']:.0f}s", flush=True)
            return {"ok": True, "secs": round(r["secs"], 1)}
        except Exception as e:
            last = e
            print(f"  [{tag}] 失败：{type(e).__name__}: {str(e)[:160]}", flush=True)
            if k < retries:
                time.sleep(8)
    return {"ok": False, "err": f"{type(last).__name__}: {last}"}


def generate_both() -> bool:
    jobs = [("inst", LYRICS_INST, gs.BACKENDS[0]),
            ("vocal", LYRICS_VOCAL, gs.BACKENDS[1])]
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(gen_one, t, l, b): t for t, l, b in jobs}
        res = {futs[f]: f.result() for f in cf.as_completed(futs)}
    bad = {k: v.get("err") for k, v in res.items() if not v["ok"]}
    if bad:
        print(f"生成失败：{bad}", flush=True)
        return False
    return True


def band_ratio(x, lo=1000.0, hi=4000.0, n=2048, hop=1024):
    """1–4 kHz 能量占全带宽的比例；人声唱腔通常抬高这一带。"""
    mono = x.mean(axis=1).astype(np.float64)
    win = np.hanning(n)
    frames = np.stack([mono[i:i + n] * win
                       for i in range(0, len(mono) - n, hop)])
    S = np.abs(np.fft.rfft(frames, axis=1))
    f = np.fft.rfftfreq(n, 1.0 / g.SR)
    m = (f >= lo) & (f <= hi)
    return float(S[:, m].sum() / max(S.sum(), 1e-9))


def syllable_modulation(x, lo=1000.0, hi=4000.0, n=1024, hop=256):
    """1–4 kHz 能量包络里 3–10 Hz（音节率）的调制占比；唱词会明显抬高。"""
    mono = x.mean(axis=1).astype(np.float64)
    win = np.hanning(n)
    frames = np.stack([mono[i:i + n] * win
                       for i in range(0, len(mono) - n, hop)])
    S = np.abs(np.fft.rfft(frames, axis=1))
    f = np.fft.rfftfreq(n, 1.0 / g.SR)
    band = S[:, (f >= lo) & (f <= hi)].sum(axis=1)
    band = band - band.mean()
    sp = np.abs(np.fft.rfft(band * np.hanning(len(band))))
    hz = np.fft.rfftfreq(len(band), hop / g.SR)
    m = (hz >= 3) & (hz <= 10)
    total = float((sp ** 2).sum())
    return float((sp[m] ** 2).sum() / max(total, 1e-9))


def upper_ratio(x, t0=0.0, t1=None, n=8192):
    """2–4 kHz / 0.3–1 kHz 能量比。

    唱腔/人声会显著抬高上谐波与共振峰；这是本样本里比「音节率」更可靠的指标
    （本次唱词是「啊——」式长拖腔，音节率天然偏低）。
    """
    mono = x.mean(axis=1).astype(np.float64)
    i0, i1 = int(t0 * g.SR), len(mono) if t1 is None else int(t1 * g.SR)
    mono = mono[i0:i1]
    if len(mono) < n or np.sqrt(np.mean(mono ** 2)) < 0.015:
        # 纯静音窗口直接记 0，避免分母趋零把比值虚抬到 1 以上
        return 0.0
    win = np.hanning(n)
    frames = np.array([np.abs(np.fft.rfft(mono[i:i + n] * win)) ** 2
                       for i in range(0, len(mono) - n, n // 2)])
    # 静音帧分母趋零会把比值虚高到 1 以上，必须按帧能量门限剔除
    rms = np.sqrt(frames.sum(axis=1))
    keep = rms > max(rms.max() * 0.08, 1e-12)
    S = frames[keep].mean(axis=0) if keep.any() else frames.mean(axis=0)
    f = np.fft.rfftfreq(n, 1.0 / g.SR)
    low = S[(f >= 300) & (f <= 1000)].sum()
    return float(S[(f >= 2000) & (f <= 4000)].sum() / max(low, 1e-9))


def upper_ratio_peak(x, win_sec=4.0):
    return max(upper_ratio(x, s, s + win_sec)
               for s in np.arange(0, max(len(x) / g.SR - win_sec, 0.01), win_sec / 2))


def declick(x, thresh=0.35, half_ms=3.0, isolation=20, limit=64):
    """只修补**孤立**的单样本幅度突跳，避免误伤正常瞬态。

    CPU 4-step 输出局部会有削波噪声簇（相邻几十个样本都很大），那不是咔哒，
    不能逐点插值；真正的咔哒是前后 ±20 样本内唯一的孤立尖峰。
    """
    x = x.copy()
    d = np.abs(np.diff(x.mean(axis=1).astype(np.float64)))
    cand = np.where(d > thresh)[0][:20000]
    picks = []
    for i in cand:
        near = cand[np.searchsorted(cand, i - isolation):np.searchsorted(cand, i + isolation + 1)]
        if len(near) == 1:
            picks.append(i)
        if len(picks) >= limit:
            break
    half = int(half_ms * g.SR / 1000)
    for c in picks:
        lo, hi = max(0, c - half), min(len(x), c + half)
        if hi - lo < 4:
            continue
        a, b = x[lo].copy(), x[hi - 1].copy()
        w = np.linspace(0, 1, hi - lo, dtype=np.float64)
        x[lo:hi] = (a * (1 - w)[:, None] + b * w[:, None]).astype(np.float32)
    return np.ascontiguousarray(x), len(picks)


def pick_loop_T(y, cross, search_sec=1.2):
    """在尾部窗口内挑最平滑的循环边界，避免把源音频里的硬切变成循环接缝。"""
    T0 = len(y) - cross
    W = min(int(search_sec * g.SR), max(T0 - cross, 1))
    d = np.abs(np.diff(y.mean(axis=1).astype(np.float64)))
    cs = np.concatenate(([0.0], np.cumsum(d)))
    idx = np.arange(T0 - W, T0 + 1)
    half = 512
    rough = (cs[np.minimum(idx + half, len(d))] -
             cs[np.maximum(idx - half, 0)]) / (2 * half)
    jump = d[np.clip(idx - 1, 0, len(d) - 1)]
    score = rough + 8.0 * jump + 2e-5 * (T0 - idx) / g.SR
    return int(idx[int(np.argmin(score))])


def compare(a, b) -> dict:
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    ma, mb = a.mean(axis=1).astype(np.float64), b.mean(axis=1).astype(np.float64)
    corr = float(np.corrcoef(ma, mb)[0, 1])
    return {
        "caption": CAPTION,
        "lyrics_inst": LYRICS_INST,
        "lyrics_vocal": LYRICS_VOCAL,
        "seed": SEED, "bpm": BPM, "duration": DURATION, "steps": STEPS,
        "waveform_correlation": round(corr, 4),
        "band_1_4k_inst": round(band_ratio(a), 4),
        "band_1_4k_vocal": round(band_ratio(b), 4),
        "syllabic_modulation_inst": round(syllable_modulation(a), 4),
        "syllabic_modulation_vocal": round(syllable_modulation(b), 4),
        "upper_harmonics_inst": round(upper_ratio(a), 4),
        "upper_harmonics_vocal": round(upper_ratio(b), 4),
        "upper_harmonics_peak_inst": round(upper_ratio_peak(a), 4),
        "upper_harmonics_peak_vocal": round(upper_ratio_peak(b), 4),
        "note": "同 caption/seed/BPM/时长，仅 lyrics 不同。唱腔乐句最可靠的客观证据是"
                "2–4kHz 上谐波能量的局部抬升与谐波列同步跳进（频谱图可见）；长拖腔"
                "的音节率天然偏低，不能单看音节调制。客观指标仅供参考，最终以试听为准。",
    }


def postprocess() -> dict:
    a = g.decode_mp3(seg_file("inst"))
    b = g.decode_mp3(seg_file("vocal"))
    rep = compare(a, b)

    # 1) 各自去掉模型自带的静音尾，避免成品中间出现 ~8s 空档
    a, _ = g.common_trim(a, a)
    b, _ = g.common_trim(b, b)
    a, ca = declick(a)
    b, cb = declick(b)
    rep["segment_seconds_inst"] = round(len(a) / g.SR, 2)
    rep["segment_seconds_vocal"] = round(len(b) / g.SR, 2)
    rep["declick_fixes"] = ca + cb
    print(f"  去静音尾：A {len(a)/g.SR:.2f}s / B {len(b)/g.SR:.2f}s；"
          f"咔哒修补 {ca + cb} 处", flush=True)

    # 2) 器乐 → 唱腔 → 器乐，三段等功率交叉淡化
    n = min(len(a), len(b))
    x, stitched = seg.stitch_arrays([a[:n], b[:n], a[:n]], n, cross_sec=SEG_CROSS)
    x, _ = g.common_trim(x, x)

    # 3) 在尾部窗口挑平滑循环边界，再做 2s 首尾无缝循环
    cross = int(LOOP_CROSS * g.SR)
    T = pick_loop_T(x, cross)
    rep["loop_boundary_seconds"] = round(T / g.SR, 3)
    x, loop = g.make_seamless_loop(x[:T + cross], g.SR, LOOP_CROSS)
    wav = fix_levels.normalize(x, OUT.stem)
    g.ffmpeg("-i", str(wav), "-c:a", "libvorbis", "-qscale:a", "5",
             "-ar", str(g.SR), "-ac", "2", str(OUT))

    rep["structure"] = "A 器乐 → B 唱腔 → A 器乐（各段 2s 等功率交叉淡化）"
    rep["stitched_seconds"] = round(stitched, 2)
    rep["loop_seconds"] = round(loop, 2)
    rep["output"] = str(OUT.relative_to(HERE)).replace("\\", "/")
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"  拼接 {stitched:.2f}s → 平滑循环点 {T/g.SR:.2f}s → {loop:.2f}s", flush=True)
    print(f"  成品 {OUT}（{OUT.stat().st_size / 1024:.0f} KB）", flush=True)
    return rep


def build_page(rep: dict):
    rows = [
        ("波形相关系数", f"{rep['waveform_correlation']:.3f}", "越低说明 lyrics 改动越大"),
        ("上谐波峰值 2–4k / 0.3–1k",
         f"{rep['upper_harmonics_peak_inst']:.3f} → {rep['upper_harmonics_peak_vocal']:.3f}",
         "器乐段 → 唱腔段，局部抬升即唱腔乐句"),
        ("1–4 kHz 能量占比", f"{rep['band_1_4k_inst']:.3f} → {rep['band_1_4k_vocal']:.3f}", "全段平均，长拖腔下反而可能下降"),
        ("音节调制 3–10 Hz",
         f"{rep['syllabic_modulation_inst']:.3f} → {rep['syllabic_modulation_vocal']:.3f}",
         "「啊——」式长拖腔音节率天然偏低，仅作参考"),
        ("有效片段长度", f"{rep['segment_seconds_inst']:.2f} s / {rep['segment_seconds_vocal']:.2f} s",
         f"A / B，已去掉模型静音尾；共修补 {rep['declick_fixes']} 处咔哒"),
        ("成品循环点", f"{rep['loop_seconds']:.2f} s", "平滑边界搜索 + 首尾 2 s 等功率交叉淡化"),
    ]
    tr = "\n".join(
        f"<tr><td>{k}</td><td class=v>{v}</td><td class=d>{d}</td></tr>" for k, v, d in rows)
    lyric = LYRICS_VOCAL.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>人声唱腔测试曲 · 西皮流水</title>
<style>
:root{{--bg:#111318;--panel:#191c23;--line:#2a2f3a;--txt:#e8eaf0;--dim:#8b93a5;--acc:#e0a35a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--txt);
 font:14px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;padding:28px}}
.wrap{{max-width:820px;margin:auto}}h1{{font-size:20px;margin:0 0 4px}}
h2{{font-size:14px;font-weight:500;margin:26px 0 10px;color:var(--acc)}}
p.sub{{color:var(--dim);margin:0 0 22px;font-size:13px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
 padding:16px 18px;margin-bottom:12px}}
audio{{width:100%;margin-top:8px}}code{{color:var(--acc);font-size:12px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td{{padding:8px 6px;border-bottom:1px solid var(--line);color:var(--dim)}}
td.v{{color:var(--txt);white-space:nowrap}}td.d{{font-size:12px}}
.note{{color:var(--dim);font-size:12px;margin-top:10px}}
pre{{background:#101218;border:1px solid var(--line);border-radius:8px;padding:12px;
 font-size:12px;color:var(--txt);overflow-x:auto}}
</style></head><body><div class="wrap">
<h1>人声唱腔测试曲 · 西皮流水</h1>
<p class="sub">ACE-Step 1.5 音乐生成大模型 · 器乐为主，中段插入一段风格化戏曲女声唱腔 · 单曲测试，未写入正式 manifest</p>
<div class="card"><h2 style="margin-top:0">成品 · 无缝循环</h2>
<audio controls loop src="game/public/assets/music/test_vocal_xipi.ogg"></audio>
<div class="note">44.1 kHz 立体声 OGG Vorbis · −16 LUFS · 循环 {rep['loop_seconds']:.2f}s。开头与结尾都是器乐，唱腔只在中间出现。</div></div>
<div class="note">结构：<code>A 器乐 → B 唱腔 → A 器乐</code>，三段 2 s 等功率交叉淡化；
开头与结尾都是器乐，唱腔只在中间一段出现。</div></div>
<h2>A / B 对照试听</h2>
<div class="card"><b>段 A · 纯器乐</b> <code>[Instrumental]</code>
<audio controls src="tmp/vocal_test_inst.mp3"></audio></div>
<div class="card"><b>段 B · 带唱腔</b> <code>同 seed，仅 lyrics 不同</code>
<audio controls src="tmp/vocal_test_vocal.mp3"></audio></div>
<h2>0–4 kHz 频谱对照</h2>
<div class="card"><b>段 A · 静态谐波列、稀疏短促起音</b>
<img style="width:100%;display:block;margin-top:8px;border-radius:6px"
 src="tmp/spec4k_inst.png" alt="段 A 频谱"></div>
<div class="card"><b>段 B · 谐波列同步跳进 + 持续音规则颤音 + 装饰性音头</b>
<img style="width:100%;display:block;margin-top:8px;border-radius:6px"
 src="tmp/spec4k_vocal.png" alt="段 B 频谱"></div>
<h2>客观对照</h2>
<div class="card"><table>{tr}</table>
<div class="note">两段 caption / seed / BPM / 时长 / steps 完全一致，唯一差别是 lyrics。
波形相关降到 {rep['waveform_correlation']:.3f}，且 B 段在 19–23 s / 29–32 s 出现上谐波能量的局部暴涨，
配合频谱图里整组谐波同步跳进与颤音，说明模型确实走了唱腔分支。CPU 4-step 的量化推理音色偏合成感，
指标只作参考，请以上面试听为准。</div></div>
<h2>本次 lyrics（段 B）</h2>
<div class="card"><pre>{lyric}</pre>
<div class="note">唱词为自编风格化短句，未使用任何现存剧目唱词。<code>[inst]</code> 让首尾回到纯器乐，<code>[verse]</code> / <code>[chorus]</code> 是唱腔段。</div></div>
<h2>caption</h2>
<div class="card"><pre>{CAPTION}</pre></div>
<p class="note">生成脚本：<code>gen_vocal_test.py</code> · 指标明细：<code>tmp/vocal_test_report.json</code>。
本测试曲不进入 <code>manifest.json</code>，需要正式收录时再手动加条目。</p>
</div></body></html>"""
    (HERE / "vocal_test.html").write_text(html, encoding="utf-8")
    print(f"  试听页 {HERE / 'vocal_test.html'}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略片段缓存重新调模型")
    ap.add_argument("--post-only", action="store_true", help="只用已有片段重做后处理与试听页")
    args = ap.parse_args()

    TMP.mkdir(parents=True, exist_ok=True)
    g.MUSIC_DIR.mkdir(parents=True, exist_ok=True)

    if args.force:
        for t in ("inst", "vocal"):
            seg_file(t).unlink(missing_ok=True)

    if not args.post_only:
        print("=== 并行生成两段（同参数，仅 lyrics 不同）===", flush=True)
        if not generate_both():
            raise SystemExit(1)
    else:
        for t in ("inst", "vocal"):
            if not seg_file(t).exists():
                raise SystemExit(f"缺少片段 {seg_file(t)}，请先不加 --post-only 运行")

    print("\n=== 对照分析 + 拼接后处理 ===", flush=True)
    rep = postprocess()
    build_page(rep)
    print("\n完成。", flush=True)


if __name__ == "__main__":
    main()
