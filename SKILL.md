---
name: game-bgm-generation
description: 用音乐生成大模型产出可直接入游戏的外部 BGM 资产（calm / fight 双层、无缝循环、manifest.json、响度与验收）。当用户要求生成游戏配乐、BGM、背景音乐、外部音频资产，或提到 ACE-Step / MusicGen / GenBGM / Gradio Space / 平静层紧张层 / 双层交叉淡化 / ogg 无缝循环 / LUFS 验收时使用。Also use for English requests such as "generate game BGM", "AI music for a game", "loopable battle music", or "external audio assets with a manifest". 明确禁止程序化合成：声音必须来自模型推理，本地只做解码、拼接、循环、归一化与编码。
agent_created: true
---

# 游戏配乐（BGM）生成管线

## 概述

把「音乐生成大模型推理 → 双层对齐 → 无缝循环 → 响度归一化 → 清单与验收」
这条完整链路固化成可复用的管线，产出满足游戏 `manifest.json` 契约的
OGG Vorbis 资产。附带一套已实跑通过的 Python 脚本、契约文档、后端接口说明
与故障排查手册。

**核心原则：不程序化合成。** 所有声音都由音乐生成大模型推理产生；
本地脚本只做解码、等功率交叉淡化、去静音、循环、LUFS 归一化、OGG 编码和验收。
接口不可用时如实报告阻塞，绝不退化成本地写音符 / MIDI / 鼓机。

## 何时使用

- 用户要求「生成配乐 / 做 BGM / 生成音乐」，或给出一份配乐规格文档（`音乐.md` 等）。
- 需要给游戏补 `calm`（常驻循环）与 `fight`（交战叠放）双层、同速同调同 loop 点的音频。
- 需要生成 / 刷新 `manifest.json`、`preview.html` 试听页、或按 LUFS / 峰值 / 循环接缝验收已有资产。
- 用户明确说「不用程序化合成，调用音乐生成大模型接口」。
- 需要免凭据调用公开模型 Space，或把管线切到用户自备凭据的官方音乐 API。

不用于：单曲欣赏型音乐创作、音效 SFX、语音、已有音频的剪辑混音（那些不需要双层对齐契约）。

## 快速决策

```
拿到需求
 ├─ 有规格文档？→ 先读，提取时长/编码/响度/清单字段；与 references/spec.md 对照
 ├─ 有官方 API 凭据？→ 只替换「拿模型原始音频」这一步，后处理整条复用
 ├─ 无凭据 → 用内置 CPU Space 路线 B（默认，免注册）
 ├─ ZeroGPU 报错 error: null → 配额耗尽，别换代理死等，直接走路线 B
 └─ 只要人声唱腔测试曲 → 走 scripts/gen_vocal_test.py（独立产物，不写清单）
```

## 标准工作流

### 第 0 步：读契约

读取目标项目的配乐规格文档。没有文档就采用 `references/spec.md` 的默认契约：
60–120 s、44.1 kHz 立体声 OGG Vorbis、约 −16 LUFS、峰值 ≤ −1 dBFS、
首尾无缝循环、`calm` / `fight` 同速同调同 loop 点。

### 第 1 步：检查环境并部署脚本

```bash
python <skill>/scripts/bootstrap.py --check-only
python <skill>/scripts/bootstrap.py --target <工作区根目录>
```

`bootstrap.py` 会检查 Python 3.10+ / numpy / scipy / ffmpeg（含 `libvorbis`）/ ffprobe，
并把管线脚本放进 `<工作区>/music/`、建好 `game/public/assets/music/` 与 `tmp/`。
**脚本必须同目录**——它们用 `Path(__file__).parent` 互相 import 并定位产物路径。
已有同名脚本默认保留，避免覆盖用户改过的风格表；确认要覆盖时加 `--force`。

### 第 2 步：配置风格表

编辑 `music/gen_music_api.py` 的 `STYLES`（10 首中国戏曲/民歌示例），字段含义见
`references/spec.md` §5。改 `slug` / `name` / `bpm` / `en` / `cn` / `perc` 即可换曲目，
改 `CALM_SUFFIX` / `FIGHT_SUFFIX` / `COMMON` 换整体风格口径。
先跑 `python gen_music_api.py --prompts-only` 生成 `prompts.md` 与 `preview.html`，不耗算力。

平静层必须显式排除鼓点并剔除风格描述里的锣鼓词；交战层必须把「每拍重击、
密集锣鼓、打击乐最前景」写进 caption。这是双层听感差异的关键。

### 第 3 步：生成（耗时最长，用断点续跑）

```bash
cd <工作区>/music
python -u gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4
```

每层 2 段 × 40 s / 4 steps，两个 CPU Space 并行，段间 2 s 等功率交叉淡化，
最后 2 s 首尾循环交叉淡化，成品约 66–74 s。
段号 `i` 的 calm 与 fight **共用 seed / bpm / duration**，只改 caption，这是对齐的保证。

单段推理 8–25 分钟，整批可能跑数小时：用后台任务执行、定期汇报进度，
务必带 `--skip-existing`。`tmp/{slug}_{layer}_seg{i}.mp3` 是唯一推理缓存，不要删。
单首重做用 `--only N --force`，看进度用 `--status`。

### 第 4 步：修复响度与峰值（不调模型）

```bash
python fix_levels.py            # 或 --only N
```

CPU Space 输出的 mp3 已削波到 0 dBFS，且 Vorbis 编码会过冲约 +0.5 dB。
`fix_levels.py` 用无记忆 `tanh` 峰值整形（对循环点安全）把 WAV 峰值压到
−2 dBFS，再做到 −16 LUFS，最后编码 OGG。首次批量必跑。

### 第 5 步：验收与试听

```bash
python verify_music.py                       # 必须 N/N 通过，明细 tmp/verify_report.json
python -m http.server 8765 --bind 127.0.0.1 # 打开 http://127.0.0.1:8765/preview.html
```

`file://` 会被 CORS 拦住 fetch，必须走本地 HTTP。拖动滑块 0→1 检查等功率交叉淡化，
并试听循环点有无咔哒。验收不过 → 查 `references/troubleshooting.md`，
多数情况用 `fix_levels.py` 或只补一个缺失片段即可，不要重跑整批。

### 第 6 步：交付

把 `music/game/` 整个目录拷进游戏仓库即可，游戏端无需改代码。
确认 `manifest.json` 条目数与 ogg 文件数匹配、测试曲没有混进清单、
`preview.html` 已刷新。

## 命令速查

| 目的 | 命令 |
| --- | --- |
| 环境自检 / 部署 | `bootstrap.py --check-only` / `bootstrap.py --target <dir>` |
| 刷新提示词与试听页（不调模型） | `python gen_music_api.py --prompts-only` |
| 批量生成（断点续跑） | `python -u gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4` |
| 单首 / 强制重做 / 看进度 | `--only N` / `--only N --force` / `--status` |
| 响度峰值修复 | `python fix_levels.py [--only N]` |
| 验收 | `python verify_music.py` |
| 人声唱腔测试曲 | `python -u gen_vocal_test.py [--post-only \| --force]`；`python verify_vocal_test.py` |
| 维护：把实跑管线同步回 skill | `bootstrap.py --sync-from <实跑 music 目录>` |

## 附带脚本

| 文件 | 作用 |
| --- | --- |
| `scripts/bootstrap.py` | 环境自检、部署管线、反向同步维护 |
| `scripts/space_client.py` | 通用 Gradio queue API 客户端（SSE 轮询 + 音频下载） |
| `scripts/gen_music_api.py` | 风格表、双层提示词、解码/裁剪/循环/编码、清单与试听页 |
| `scripts/gen_music_space.py` | CPU Space 后端常量与 `/generate` 8 参数组装 |
| `scripts/gen_music_segments.py` | ★ 主脚本：短片段推理 + 拼接 + 归一化 + 清单 |
| `scripts/fix_levels.py` | 静态峰值整形 → −16 LUFS → 峰值余量（可重跑） |
| `scripts/verify_music.py` | ★ 按契约逐项验收，输出报告 JSON |
| `scripts/gen_vocal_test.py` / `verify_vocal_test.py` | 可选：部分人声唱腔测试曲及 A/B 验收 |

## 参考文件

- `references/spec.md` — 资产契约、清单 schema、数值验收口径、双层对齐原理、换项目改哪里
- `references/model-api.md` — 后端选路、Gradio API、CPU Space 参数与 600 s 限制、
  人声分支、有凭据时的官方 API、依赖
- `references/troubleshooting.md` — 超时 / 配额 / 削波 / 接缝 / 静音尾 / 只补缺失片段的恢复手法
- `references/case-study.md` — 10 首 × 2 层的完整实跑记录（提示词改版实测、最终循环点、历史坑）

## 关键提醒

- 默认**无需任何凭据**；不代注册、不代付费。用户有凭据时只替换取音频那一步。
- ZeroGPU 匿名配额已实测全局耗尽（21 个 Space × 3 出口 = 63 次全失败），
  不要再花时间轮换出口，直接用 CPU Space 路线。
- 接口全挂时如实报告阻塞，绝不用本地合成冒充「模型生成」。
- 测试曲、实验产物是独立文件，永远不写进正式 `manifest.json`。
- 修改 skill 内的脚本后，用 `bootstrap.py --sync-from` 或反向复制保持与实跑管线一致。
