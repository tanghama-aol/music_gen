# game-bgm-generation

一个 [WorkBuddy](https://www.workbuddy.ai) Skill：用**音乐生成大模型**产出可直接入游戏的外部 BGM 资产 —— `calm` / `fight` 双层、无缝循环、`manifest.json`、−16 LUFS 归一化与逐项验收。

> **Generate game-ready BGM with music-generation models.** Two synchronized layers (calm / fight), seamless loops, a game manifest, loudness normalization and automated verification. No procedural synthesis: every sound comes from model inference.

## 这是什么

游戏里 `calm` 层常驻循环，`fight` 层同时播放、靠音量交叉淡化切换，所以两层必须**同速、同调、同小节数、同 loop 点**。这个 skill 把整条链路固化下来：

音乐生成大模型推理 → 同 seed 双层对齐 → 短片段等功率交叉淡化拼接 → 首尾无缝循环 → `tanh` 峰值整形 + −16 LUFS → OGG Vorbis 编码 → `manifest.json` / 试听页 → 客观验收。

**硬性约束：不程序化合成。** 本地脚本只做解码、去静音、交叉淡化、循环、增益、编码和验收；不写音符、MIDI、振荡器、鼓机。模型接口不可用时如实报错，不会退化成本地"造"音乐。本地交叉淡化只是把**模型已生成的音频**接起来，不产生新音色。

实测交付记录见 [`references/case-study.md`](references/case-study.md)：10 首 × 2 层 = 20 个 OGG，`verify_music.py` 10/10 通过，成品 66.8–74.3 s。

## 安装

把本仓库克隆到 skills 目录（目录名必须是 skill 名）：

```bash
git clone https://github.com/tanghama-aol/music_gen.git \
  ~/.workbuddy-ai/skills/game-bgm-generation
```

或下载 [`dist/game-bgm-generation.zip`](dist/game-bgm-generation.zip) 解压到同一位置。
新装的 skill 通常需要**新开一个会话**才会出现在技能列表里。

仓库根目录就是 skill 根目录（标准结构：`SKILL.md` + `scripts/` + `references/`），
因此也可以直接 `git clone` 到任意 Agent 的 skills 路径下使用。

## 快速开始

```bash
# 1. 环境自检 + 把管线部署到目标工作区的 music/ 目录
python <skill>/scripts/bootstrap.py --check-only
python <skill>/scripts/bootstrap.py --target /path/to/workspace

# 2. 改 scripts/gen_music_api.py 里的 STYLES（曲目、BPM、中英文提示词）
cd /path/to/workspace/music
python gen_music_api.py --prompts-only          # 只刷新提示词与试听页，不调模型

# 3. 生成（每层 2 段 × 40s / 4 steps，带断点续跑；耗时数小时，建议后台跑）
python -u gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4

# 4. 响度 / 峰值修复（不耗模型算力）
python fix_levels.py

# 5. 验收 + 试听
python verify_music.py                          # 必须 N/N 通过
python -m http.server 8765 --bind 127.0.0.1    # 打开 preview.html，file:// 会被 CORS 拦
```

最后把 `music/game/` 整个目录拷进游戏仓库即可，游戏端不用改代码。
单首重做 `--only N --force`，看进度 `--status`，超时后**不要从头重跑**——
`tmp/*_seg{i}.mp3` 是唯一的推理缓存，只补缺的那一段即可（见 `references/troubleshooting.md`）。

## 产物契约

| 项 | 要求 |
| --- | --- |
| 文件 | `game/public/assets/music/<slug>_calm.ogg` / `<slug>_fight.ogg` |
| 清单 | `game/public/assets/manifest.json` 的 `music[]`：`name` / `calm` / `fight?` / `loop:[0,end]` |
| 时长 | 60–120 s；`loop[1]` 与实测时长一致 |
| 编码 | OGG Vorbis，44.1 kHz，立体声 |
| 响度 | 约 −16 LUFS（±1.2 LU），峰值 ≤ −1 dBFS |
| 循环 | 首→尾接缝指标 < 4，无淡入淡出 |
| 双层 | 同 seed / BPM / duration / 小节数 / 调 / loop 点；同一样本数 |
| 风格 | `calm` 抒情无鼓点；`fight` 中国大鼓板鼓每拍重击、密集锣鼓处于最前景 |

详细的字段说明、对齐原理和换项目改哪里，见 [`references/spec.md`](references/spec.md)。

## 目录结构

仓库分两部分：根目录是**可直接安装的 skill**，`music/` 是**实跑管线的真源与成品资产**。
两者脚本同源；`scripts/` 是便携快照，`music/` 还额外含诊断脚本、提示词、试听页和已生成的 OGG。

```
音乐.md                          原始配乐规格文档（10 首风格、清单 schema、响度规范）
SKILL.md                        触发条件 + 6 步工作流 + 命令速查
scripts/
  bootstrap.py                 环境自检 / 部署 / 反向同步
  space_client.py              通用 Gradio queue API 客户端（SSE 轮询 + 音频下载）
  gen_music_api.py             风格表、双层提示词、解码/裁剪/循环/编码、清单与试听页
  gen_music_space.py           CPU Space 后端常量与 /generate 8 参数组装
  gen_music_segments.py        ★ 主脚本：短片段推理 + 拼接 + 归一化 + 清单
  fix_levels.py                静态峰值整形 → −16 LUFS → 峰值余量（可重跑）
  verify_music.py              ★ 按契约逐项验收，输出 JSON 报告
  gen_vocal_test.py            可选：部分人声唱腔测试曲
  verify_vocal_test.py         可选：A/B 对照与唱腔定位验收
references/
  spec.md                      资产契约与验收口径
  model-api.md                 后端选路、API 参数、600s 限制、人声分支、官方 API
  troubleshooting.md           超时 / 配额 / 削波 / 接缝 / 静音尾的恢复手法
  case-study.md                10 首 × 2 层完整实跑记录
dist/game-bgm-generation.zip   可直接安装的打包版本
music/
  README.md                    完整实跑记录（契约对照、提示词改版实测、历史坑）
  *.py                         8 个管线脚本 + 8 个 probe_* 诊断脚本
  prompts.md / preview.html    10 首中英文提示词 / 双层叠放试听页
  vocal_test.html              人声唱腔测试曲 A/B 对照页
  local_src/                   第三方 Space 的 app.py 参考快照（用于反推接口参数）
  game/public/assets/
    manifest.json              10 首正式曲目的清单与循环点
    music/*.ogg                20 个正式层 + 1 个测试曲（共 23 个，约 27 MB）
  tmp/*.json, tmp/spec4k_*.png 验收报告与人声对照频谱图
```

`tmp/` 里 148 个 wav / 51 个 mp3 / 各类日志是 1.6 GB 的推理中间缓存，**未入库**；
用管线重新生成即可。`music/README.md` §7 记录了最终 10 首的循环点，
`music/tmp/verify_report.json` 是 `verify_music.py` 的 10/10 通过明细。

## 模型后端

默认**无需任何凭据**：走两个公开的 ACE-Step 1.5 GGUF CPU Space（`cpu-basic`，由 Space 拥有者承担算力），端点 `/generate`，8 个顺序参数为 `caption / lyrics / bpm / duration / seed / steps / lora_select / lm_model_select`。

官方 ACE-Step v1 的 ZeroGPU 匿名配额已实测全局耗尽（21 个 Space × 3 条出口 = 63 次最小任务全部失败），不要再花时间轮换出口。若用户自备 Hugging Face token 或火山引擎 GenBGM 等官方 API 凭据，只需替换「拿模型原始音频」这一步，后处理整条链路不动。

> 公开 Space 由第三方维护，可用性与推理耗时不保证；本项目不代注册、不代付费，也不存储任何密钥。

## 依赖

Python 3.10+、`numpy`、`scipy`、`ffmpeg`（须带 `libvorbis`）、`ffprobe`。
HTTP 客户端只用标准库 `urllib`。`scripts/bootstrap.py --check-only` 会逐项检查。

## 许可

本仓库暂未指定开源许可证。模型输出音频与所用第三方 Space 的授权请以各自服务条款为准。
