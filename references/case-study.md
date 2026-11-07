# 配乐生成包（按《音乐.md》）

用**音乐生成大模型**产出可直接入游戏的外部 BGM 资产。**不是程序化合成**：所有声音都由模型
推理生成，本地只做解码、片段交叉淡化、去静音、无缝循环、响度归一化与 ogg 编码。

每首都有两层：`calm`（舒缓、无鼓点）与 `fight`（紧张、锣鼓在最前景），游戏内同时循环播放，
靠音量交叉淡化切换。

---

## 1. 目录与产物

```
music/
├── gen_music_api.py         路线 A：ACE-Step v1 ZeroGPU 官方 Space 客户端
├── gen_music_space.py       路线 B：ACE-Step 1.5 CPU Space 客户端（单次长片段）
├── gen_music_segments.py    ★ 当前主脚本：短片段推理 + 拼接 + 后处理 + 清单
├── fix_levels.py            静态峰值整形 → −16 LUFS → 峰值余量（可重跑，不耗模型算力）
├── verify_music.py          ★ 按《音乐.md》逐项验收，输出 tmp/verify_report.json
├── space_client.py          通用 Gradio /gradio_api/call 客户端（SSE 轮询）
├── prompts.md               10 首 × 平静/交战，中英文提示词
├── preview.html             calm/fight 双层叠放试听页
├── README.md                本文件
├── tmp/                     模型原始 mp3、中间 wav、日志（可删）
└── game/public/assets/
    ├── manifest.json        游戏读取的清单
    └── music/*_calm.ogg / *_fight.ogg
```

把 `game/` 整个目录拷进游戏仓库即可（与《音乐.md》第二节路径一致）。清单格式：

```json
{
  "music": [
    {
      "name": "西皮流水（京剧）",
      "calm": "music/xipiliushui_calm.ogg",
      "fight": "music/xipiliushui_fight.ogg",
      "loop": [0, 86.87]
    }
  ]
}
```

## 2. 与《音乐.md》契约的对照

| 要求 | 实现 |
| --- | --- |
| 60–120 s | ✅ 10 首实测 66.8–74.3 s（首版第 1 首曾为 86.87 s，已按同一管线重做） |
| 44.1 kHz 立体声 | ✅ `ffprobe` 确认 `vorbis / 44100 / 2ch` |
| ogg Vorbis | ✅ `libvorbis -qscale:a 5` |
| 约 −16 LUFS | ✅ 全部 10 首 20 个文件实测 −16.0 ~ −16.1 LUFS（BS.1770 实测后常量增益）；峰值整形见 §5 |
| 峰值 ≤ −1 dBFS | ✅ 全部 ≤ −1.2 dBFS，用无记忆静态整形 + 余量控制，无动态处理、循环点安全 |
| 无缝循环、无淡入淡出 | ✅ 尾段折回头部做 2 s 等功率 `sin²/cos²` 交叉淡化，接缝指标全部 < 4 |
| calm / fight 同速、同小节数、同调 | ✅ 每个片段编号的 calm 与 fight 用【同一 seed + 同一 BPM + 同一时长】，只改 caption |
| 两层同一 `loop` 点 | ✅ 所有片段统一裁到全局最短样本数，再走 `fix_levels.process_pair_v2()` 成对裁剪、同样本数、同交叉淡化 |
| 不盖住脚步/枪声的环境 SFX | 提示词显式排除 ambient / field recording / SFX，纯器乐 `[Instrumental]` |
| 舒缓 / 紧张带鼓点 | 平静层把风格描述里的锣鼓词全部剔除并显式 `NO drums / NO percussion / NO gongs`；交战层把「大鼓板鼓每拍重击、大锣小锣密集催打、锣鼓处于最前景」写进提示词 |
| 女声高音衬腔（可选） | 默认关闭，纯器乐 |

> 《音乐.md》表格里的 `98 → 132 BPM` 属于游戏内程序合成（`musicStyles.ts`）按战况变速；
> 外部音频走第二节的**叠放**规则，两层共用平静 BPM，靠音量交叉淡化切换，不改速。

### 提示词改版前后强弱实测（历史记录）

| 层 | 起音密度 | 包络起伏 |
| --- | --- | --- |
| 平静层（旧版） | 66.9 | 0.0273 |
| 交战层（旧版 audio2audio） | 65.4 | 0.0293 |
| 交战层（新版鼓点提示词） | **137.4** | **0.0532** |

同 seed 独立生成优于 audio2audio：色度相关 0.998 / 起音包络相关 0.896
（a2a 为 0.997 / 0.880），且 GPU 耗时从 296 s 降到 35 s。

最终 10 首的起音密度（平静 / 交战，次/分）见 `tmp/verify_report.json`，
交战层普遍比平静层高 20%–70%，交战层包络起伏也更大，体现锣鼓前景。

## 3. 试听

`file://` 会被 CORS 拦住 fetch，需要本地 HTTP 服务：

```bash
cd music
python -m http.server 8765 --bind 127.0.0.1
# 打开 http://127.0.0.1:8765/preview.html
```

拖动滑块模拟游戏内平滑切换：`0` 只放平静层，`1` 只放交战层，增益用
`cos(v·π/2)` / `sin(v·π/2)` 等功率曲线，与游戏内行为一致。

## 4. 当前模型接口（免凭据）

### 路线 A：ACE-Step v1 官方 ZeroGPU Space —— 已不可用

`gen_music_api.py` 走 `https://ace-step-ace-step.hf.space/gradio_api/call/__call__`
（22 个顺序参数，SSE 取结果）。第 1 首就是这样生成的。之后匿名 ZeroGPU 配额全局耗尽：

```
You have exceeded your ZeroGPU quota (90s requested vs. 0s left)
You have exceeded your ZeroGPU runs limit. Authenticate with a Hugging Face token for more
```

穷举验证：**21 个 RUNNING 的 `zero-a10g` 音乐 Space × 3 条网络出口（直连 / 17890 / 62893）
= 63 次 10 s / 8 steps 最小任务，成功 0 次**。配额与具体 Space 无关，也不随出口轮换恢复，
因此不再等待；除非提供 HF token 或火山引擎等付费凭据。

2026-11-06 晚用户提示「重置了」后再次复测：官方 v1 `__call__`（10 s / 8 steps）在
直连 / 17890 / 62893 三条出口全部返回 `error: null`，ACE-Step v1.5 `/generation_wrapper`
同样返回 `error: null`。说明匿名 ZeroGPU 配额属于 HF 服务端按账号/IP 的预算，本地重置无效。
**全部 10 首最终均由路线 B（CPU Space）产出，不再依赖路线 A。**

### 路线 B：ACE-Step 1.5 GGUF CPU Space —— 当前使用

两个由 Space 拥有者付费的 `cpu-basic` 实例，不消耗匿名 ZeroGPU 配额：

| 后端 | 端点 |
| --- | --- |
| `https://werecooking-ace-step-cpu.hf.space` | `/generate` |
| `https://rawdripcollective-codec-ace-step-cpu.hf.space` | `/generate` |

`/generate` 的 8 个顺序参数：
`caption, lyrics, bpm, duration, seed, steps, lora_select, lm_model_select`。
两个后端各跑一层，天然并行，且都支持显式 bpm / seed，正好满足双层对齐。

**硬限制**：其 `app.py` 里 `_poll_job(synth_job_id, timeout=600)` 是固定 600 s 合成上限。
实测 `65s / 8steps` 返回 `Synth timeout after 600s`；`60s / 4steps` 可完成（约 641–869 s），
`40s / 4steps` 可完成。

**另一个坑**：Space 返回的 mp3 头里码率不对，`ffprobe` 会把时长虚报约 1.38 倍
（请求 60 s 报 84 s），但 ffmpeg 实际解码出来就是请求的秒数（60 s → 60.0 s，40 s → 39.6 s）。

### 为什么用「短片段 + 拼接」

单次 60 s 片段经 `common_trim()` 去头尾静音（约 5 s）再做 2 s 循环交叉淡化，
成品只剩 ~53 s，低于 60 s 下限；而更长片段会撞 600 s 上限。因此：

- 每层生成 **2 段 × 40 s / 4 steps**，段间做 2 s 等功率交叉淡化；
- 全部片段（含另一层）统一裁到全局最短样本数，保证两层拼接位置完全一致；
- 最后再走 2 s 首尾无缝循环交叉淡化 → 实测 **72.56 s**，落在 60–120 s；
- 段号 i 的 calm 与 fight 共用 seed，所以整条曲子两层始终同速同调同步。

本地拼接只是对模型已生成的音频做交叉淡化，不产生任何新音色，不属于程序化合成。

## 5. 命令

```bash
# ★ 补齐第 2–10 首（断点续跑，已完成的自动跳过）
python -u gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4

# 单首
python gen_music_segments.py --only 2 --duration 40 --segments 2 --steps 4

# 强制重做某首（忽略缓存）
python gen_music_segments.py --only 1 --force --duration 40 --segments 2 --steps 4

# 只看进度
python gen_music_segments.py --status

# ★ 批量验收（60~120s / 44.1k 立体声 / loop 点 / LUFS / 峰值 / 接缝 / 双层对比）
python verify_music.py

# 用缓存重做响度与峰值（模型 mp3 已削波时必跑；不调用模型）
python fix_levels.py
python fix_levels.py --only 2

# 只刷新提示词与试听页，不调用模型
python gen_music_api.py --prompts-only
```

**响度注意**：CPU Space 输出的 mp3 已削波到 0 dBFS，直接按 −1 dBFS 峰值限幅会把
平静层压到 −18 LUFS，且 Vorbis 有损编码还会把峰值过冲约 +0.5 dB 到 −0.8 dBFS。
`fix_levels.py` 先做**无记忆 tanh 峰值整形**（只压超过膝点的极少数样本，不留状态，
对无缝循环安全），再把 WAV 峰值控制在 −2 dBFS，最终两层都能达到 −16 LUFS 且
OGG 峰值 ≤ −1 dBFS。

常用参数：`--duration`（单段秒数）、`--segments`（每层片段数）、`--steps`（扩散步数，
turbo 4–8）、`--skip-existing`、`--force`、`--only`、`--all`、`--status`。
片段缓存在 `tmp/{slug}_{layer}_seg{i}.mp3`，中途中断重跑会复用，不重复烧模型算力。
每完成一首立即写一次 `manifest.json` 与 `preview.html`。

<details><summary>旧路线 A 命令（ZeroGPU 配额恢复 / 有 HF token 时）</summary>

```bash
python gen_music_api.py --all --skip-existing --duration 70 --steps 40 \
       --retries 20 --retry-wait 60
python gen_music_api.py --only 1 --force
```

参数：`--a2a`（改回 audio2audio 派生交战层）、`--reuse-calm`、`--cross`（循环淡化秒数）、
`--start-path` / `--proxy`（网络出口）、`--retries` / `--retry-wait`（配额等待）。
`audio2audio` 模式下 `manual_seeds` 必须为 `None`，否则服务端直接 `error: null`。

</details>

依赖：Python 3.10+、`numpy`、`scipy`、`ffmpeg`（需带 `libvorbis`）。HTTP 客户端只用标准库。

## 6. 切到火山引擎 GenBGM（可选）

`prompts.md` 里每首都给了**中文提示词**，可直接作为 `Text` 传给 GenBGM v5.0
（v5.0 已取消 `Genre` / `Mood` / `Instrument` 结构化枚举，风格完全由中文 `Text` 驱动）。

| 项 | 值 |
| --- | --- |
| 端点 | `POST https://open.volcengineapi.com?Action=GenBGM&Version=2024-08-12`（预付费）<br>`Action=GenBGMForTime`（后付费） |
| 签名 | Volc Signature V4，头 `X-Date` / `X-Content-Sha256` / `Authorization` |
| 请求体 | `Text`、`Duration`、`Version="v5.0"`，可选 `Segments` / `TosBucket` / `CallbackURL` |
| 轮询 | `Action=QuerySong&Version=2024-08-12`，用返回的 `Result.TaskID` |

需要你本人实名开通并配置 `VOLC_ACCESSKEY` / `VOLC_SECRETKEY`；本仓库不代注册、不代付费。
提示词不要太短，过短容易触发版权校验错误 `50000001`。

## 7. 交付状态

**10 首 × 2 层 = 20 个 `.ogg` 全部完成，`manifest.json` 含 10 条，`verify_music.py` 10/10 通过。**

| # | 曲目 | 循环点 | # | 曲目 | 循环点 |
| --- | --- | --- | --- | --- | --- |
| 1 | 西皮流水（京剧） | 74.16 | 6 | 洞庭渔歌（湖南民谣） | 70.98 |
| 2 | 秦腔苦音（秦腔） | 71.50 | 7 | 闽南采茶（福建民谣） | 69.81 |
| 3 | 花鼓小调（花鼓戏） | 73.28 | 8 | 信天游（陕北） | 71.84 |
| 4 | 黄梅采茶（黄梅戏） | 73.26 | 9 | 江南小调（江南） | 66.76 |
| 5 | 川江号子（四川民谣） | 74.32 | 10 | 二人转（东北） | 72.74 |

> 第 1 首原为 ZeroGPU 路线 A 的 86.87 s 版本（舒缓层带鼓点，与后续「无鼓点」契约不一致），
> 已用同一 CPU 片段管线 + 新版提示词重做为 74.16 s，10 首风格口径现已统一。

验收口径：`python verify_music.py` 检查时长 / 编码 / 采样率 / 声道 / loop 点 /
−16 LUFS / 峰值 ≤ −1 dBFS / 循环接缝 / 双层等长 / 起音密度对比，明细写入
`tmp/verify_report.json`。首次批量有 3 首因模型 mp3 削波导致 LUFS 偏移与峰值过冲，
已用 `python fix_levels.py`（不耗模型算力，从 `tmp/*_stitched.wav` 重做）修复。

⚠️ **CPU Space 偶发卡死的处理**：若某个 Space 的 SSE 一直不返回（本次 #1 重做时
`rawdripcollective-codec` 连续两次 `SSE 超过 1500s`，另一次 #9 是 `LM timeout after 901s`），
重试 2 次后会跳过该首。此时**不要从头重跑**：片段缓存 `tmp/{slug}_{layer}_seg{i}.mp3`
会被复用，只要把缺的那一个片段换到另一个 Space 单独生成即可，例如：

```python
import gen_music_space as gs, gen_music_segments as seg, gen_music_api as g, space_client as sc
st = next(x for x in g.STYLES if x['no'] == 1)
seed = 700000000 + st['no'] * 123457 + 0 * 7919   # 段号 i 的 seed
base = 'https://werecooking-ace-step-cpu.hf.space'  # 换一个后端
r = sc.call_space(base, gs.ENDPOINT, gs.params_of(st, 'fight', 40, seed, 4), timeout=1500)
sc.download_audio(base, r['data'], seg.seg_path(st, 'fight', 0))
```

然后 `python gen_music_segments.py --only 1 --force` 会复用全部 4 个片段，只做拼接、归一化与
manifest/preview 更新，不再消耗模型算力。`fix_levels.py` 与预览刷新同理，可在批处理结束后单独重跑。

## 8. 人声唱腔测试曲（独立，不写入 manifest）

正式 10 首都是纯器乐（`lyrics = "[Instrumental]"`）。`音乐.md` 里「可选女声高腔点缀」
这一项单独做了一首**测试曲**，不属于交付清单，**没有写进 `manifest.json`**，
不会被游戏当成正式 BGM 加载。

| 文件 | 说明 |
| --- | --- |
| `game/public/assets/music/test_vocal_xipi.ogg` | 成品，86.60 s 无缝循环，−16 LUFS |
| `vocal_test.html` | 单曲试听 + A/B 对照 + 0–4 kHz 频谱图 + 客观指标 |
| `tmp/vocal_test_inst.mp3` / `tmp/vocal_test_vocal.mp3` | 段 A（纯器乐）/ 段 B（带唱词）原始模型输出 |
| `tmp/vocal_test_report.json` / `tmp/vocal_test_verify.json` | 生成参数与对照指标 / 验收结果 |
| `gen_vocal_test.py` / `verify_vocal_test.py` | 生成脚本 / 验收脚本 |

**方法**：A、B 两段的 caption / seed(710000001) / BPM(98) / 时长(40s) / steps(4)
完全相同，**唯一差别是 `lyrics`**；B 用自编的风格化戏曲短句（不使用任何现存剧目唱词）：

```text
[inst]
[verse]
云开月照古城楼
一嗓西皮绕画梁
[chorus]
啊—— 啊——
[inst]
```

成品按 `A 器乐 → B 唱腔 → A 器乐` 三段做 2 s 等功率交叉淡化，唱腔只占中间一段，
首尾都是器乐，循环点干净。两处针对 CPU 输出的修补：

* 每段先 `common_trim` 去掉模型自带的 ~7 s 静音尾，否则成品中间会有 8 s 空档；
* `declick()` 只修**孤立**的单样本跳变（>0.35、±20 样本内唯一），本次修 11 处；
  第一版阈值 0.15 误伤了 2881 处正常瞬态，已收紧；
* `pick_loop_T()` 在尾部 1.2 s 内挑最平滑的循环边界，避免把源音频里的硬切变成接缝
  （接缝指标从 4.07 降到 0.40）。

**唱腔是否真的生成了**：CPU 4-step + Q4 量化模型音色偏合成感，不能只看「音节率」
（「啊——」长拖腔的音节率天然偏低）。有效证据是 B 段 19–23 s / 29–32 s 出现整组谐波
同步跳进 + 持续音上的规则颤音，频谱图上肉眼可见；量化后 2–4 kHz 上谐波能量比
`0.0168 → 0.0641`（3.8×）、4 s 窗口峰值 `0.0456 → 0.1244`（2.7×），波形相关仅
`0.0188`，成品四等份里 Q3 的上谐波比是首尾均值的 3.8 倍。指标只作参考，**以试听为准**。

```bash
python -u gen_vocal_test.py                # 生成（已有片段自动复用）
python -u gen_vocal_test.py --post-only    # 只用缓存重做后处理 / 试听页，不调用模型
python -u gen_vocal_test.py --force        # 忽略缓存重新调模型
python -u verify_vocal_test.py             # 契约 + 唱腔定位验收
```

> 这次 B 段在 `rawdripcollective-codec` 上第一次 SSE 超时 1500 s，第二次 827 s 成功；
> A 段在 `werecooking` 上 468 s 完成。片段会缓存到 `tmp/vocal_test_*.mp3`，
> 超时后直接重跑即可复用，不必重新推理已完成的段。

## 9. 已封装为可复用 Skill

整套流程已固化为**用户级 skill** `game-bgm-generation`：

| 项 | 路径 |
| --- | --- |
| 安装位置 | `~/.workbuddy-ai/skills/game-bgm-generation/`（用户级） |
| 分发包 | `music/dist/game-bgm-generation.zip` |
| 入口 | `SKILL.md`（触发条件 + 6 步工作流 + 命令速查） |
| 参考文档 | `references/spec.md`（契约）、`model-api.md`（后端）、`troubleshooting.md`（排障）、`case-study.md`（本文件快照） |
| 脚本 | `scripts/` 下 8 个已验证脚本 + `bootstrap.py`（环境自检 / 部署 / 反向同步） |

在新工作区复用：

```bash
python <skill>/scripts/bootstrap.py --target <新工作区根目录>
cd <新工作区>/music
python -u gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4
python fix_levels.py && python verify_music.py
```

改过本目录的脚本后，用
`python <skill>/scripts/bootstrap.py --sync-from <实跑 music 目录>`
把最新实现同步回 skill。**实跑的 `music/` 目录仍是管线唯一真源**，skill 是它的便携快照。
