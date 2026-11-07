# 音乐生成模型接口与后端选择

## 0. 选路原则

1. **默认免凭据**：优先用公开的、由 Space 拥有者承担算力的模型推理接口，
   不要求用户提供 API Key，不代注册、不代付费。
2. **不要程序化合成兜底**：模型接口全挂时，如实报告阻塞，不要退化成本地写音符。
3. 用户自己有凭据时，优先切到对应的官方 API（见 §5），把提示词与后处理管线复用即可。
4. 每次换后端，都先跑一个最小任务（10 s / 4 steps）验证可用，再批量提交。

当前两条路线的状态（2026-11 实测）：

| 路线 | 状态 | 说明 |
| --- | --- | --- |
| A. ACE-Step v1 官方 ZeroGPU Space | ❌ 不可用 | 匿名 ZeroGPU 配额全局耗尽 |
| B. ACE-Step 1.5 GGUF **CPU** Space | ✅ 当前使用 | 两个 `cpu-basic` 实例，可并行 |

## 1. 通用 Gradio 客户端

`space_client.py` 用标准库实现，无第三方 HTTP 依赖：

```
POST {base}/gradio_api/call/{endpoint}     body: {"data": [按序排列的参数]}
  → 返回 {"event_id": "..."}
GET  {base}/gradio_api/call/{endpoint}/{event_id}   (SSE 流，长连接)
  → event: progress → 打印阶段
  → event: complete → data 是 JSON 列表，里面含音频 FileData
  → event: error    → 直接抛错（配额耗尽时 data 是 null）
```

`call_space()` 返回 `{data, secs, event_id}`；`download_audio()` 递归找出
`.wav/.mp3/.flac/.ogg/.m4a` 的 url/path，相对路径会拼成
`{base}/gradio_api/file=<path>`。SSE 超时用 `timeout=` 控制，CPU 推理建议 ≥ 1500 s。

**常见坑**：
- `/run/predict` 会 404 或报 `FnIndexInferError`，必须用 queue API `/gradio_api/call/...`。
- `event: error / data: null` = 服务端配额/运行错误，重试或换出口都没用，要换后端。
- 返回值里的 FileData 有时是相对路径，不要只找绝对 URL。

## 2. 路线 A：ACE-Step v1 ZeroGPU（已废弃，保留知识）

- Space：`https://ace-step-ace-step.hf.space`，端点 `/gradio_api/call/__call__`。
- 22 个顺序参数，关键位：`audio_duration`、`prompt`、`lyrics`、
  `manual_seeds`、`audio2audio_enable`、`ref_audio_input`。
- `ref_audio_input` 必须是 Gradio `FileData`（先 POST `/gradio_api/upload`），
  传字符串会报错；`audio2audio` 模式下 `manual_seeds` 必须为 `None`，否则 `error: null`。
- 配额报错原文：
  `You have exceeded your ZeroGPU quota (90s requested vs. 0s left)` /
  `You have exceeded your ZeroGPU runs limit. Authenticate with a Hugging Face token for more`。
- 穷举验证：21 个 RUNNING 的 `zero-a10g` 音乐 Space × 3 条网络出口
  = 63 次最小任务，成功 **0** 次。配额按 HF 服务端账号/IP 计，
  换 Space、换代理、本地"重置"都不能恢复；只有提供 HF token 或改用付费 API 才行。

`gen_music_api.py` 仍保留该客户端与 `--a2a` / `--reuse-calm` / `--start-path` /
`--proxy` / `--retries` 等参数，配额恢复或拿到 token 时可重新启用。

## 3. 路线 B：ACE-Step 1.5 GGUF CPU Space（当前主力）

两个后端（各自独立实例，天然并行，一层一个）：

```
https://werecooking-ace-step-cpu.hf.space
https://rawdripcollective-codec-ace-step-cpu.hf.space
```

端点 `/generate`，**8 个顺序参数**：

| # | 参数 | 生产取值 |
| --- | --- | --- |
| 1 | `caption` | 自然语言风格描述 + 层后缀（见 `references/spec.md` §3） |
| 2 | `lyrics` | `"[Instrumental]"`（纯器乐）；要人声时改结构标签，见 §4 |
| 3 | `bpm` | `STYLES[i]["bpm"]`，两层相同 |
| 4 | `duration` | `40`（秒/片段） |
| 5 | `seed` | `700000000 + no*123457 + seg_index*7919` |
| 6 | `steps` | `4`（turbo，4–8） |
| 7 | `lora_select` | `"None (no LoRA)"` |
| 8 | `lm_model_select` | `"acestep-5Hz-lm-1.7B-Q8_0.gguf"` |

常量集中在 `gen_music_space.py` 的 `BACKENDS / ENDPOINT / LORA / LM_MODEL / LYRICS`，
参数组装在 `params_of()`。换模型或换 Space 时只改这一处。

### 硬限制与规避

- `app.py` 里 `_poll_job(synth_job_id, timeout=600)` 是固定 **600 s 合成上限**。
  实测 `65s / 8steps` → `Synth timeout after 600s`；`40s / 4steps` 稳定完成；
  `60s / 4steps` 勉强能过（641–869 s）。
- 因此用「**短片段多次推理 + 等功率交叉淡化拼接**」：
  每层 2 段 × 40 s / 4 steps，段间 2 s 交叉淡化，最后 2 s 首尾循环交叉淡化，
  成品约 66–74 s，正好落在 60–120 s。
- 单段完整一次推理（含 LM + synth）实测 468–900 s，偶发 1500 s 超时。
  务必用 `--skip-existing` 和 `tmp/*_seg{i}.mp3` 缓存做断点续跑，
  **超时后不要从头重跑**，只补缺的那一个片段，参考 `references/troubleshooting.md`。
- Space 返回的 mp3 头码率不对，`ffprobe` 会把时长**虚报约 1.38 倍**
  （请求 60 s 报 84 s）。以 `ffmpeg` 解码出的 PCM 样本数为准，不要用 ffprobe 时长裁剪。

## 4. 人声唱腔分支

`lyrics != "[Instrumental]"` 会触发唱腔分支。结构标签用
`[inst] / [verse] / [chorus]`，唱词自编、避免直接引用现存剧目唱词：

```text
[inst]
[verse]
云开月照古城楼
一嗓西皮绕画梁
[chorus]
啊—— 啊——
[inst]
```

`gen_vocal_test.py` 的 A/B 对照：A 器乐、B 唱腔，两段 caption / seed / bpm /
duration / steps **完全相同，只有 lyrics 不同**；成品按 `A → B → A` 拼接，
唱腔只占中间，首尾器乐保证循环点干净。

判断唱腔是否真的生成，不能只看音节率（长拖腔天然偏低）。有效证据：
2–4 kHz 上谐波能量比明显上升、频谱图上出现整组谐波同步跳进与规则颤音、
A/B 波形相关极低。`verify_vocal_test.py` 输出这些指标，**最终以试听为准**。
CPU 4-step + 量化模型音色偏合成感，不要把它当正式交付。

## 5. 有凭据时的官方 API（可选）

火山引擎 GenBGM（用户本人实名开通，配置 `VOLC_ACCESSKEY` / `VOLC_SECRETKEY`）：

| 项 | 值 |
| --- | --- |
| 端点 | `POST https://open.volcengineapi.com?Action=GenBGM&Version=2024-08-12`（预付费）<br>`Action=GenBGMForTime`（后付费） |
| 签名 | Volc Signature V4，头 `X-Date` / `X-Content-Sha256` / `Authorization` |
| 请求体 | `Text`（中文提示词）、`Duration`、`Version="v5.0"`，可选 `Segments` / `TosBucket` / `CallbackURL` |
| 轮询 | `Action=QuerySong&Version=2024-08-12`，用 `Result.TaskID` |

v5.0 已取消 `Genre` / `Mood` / `Instrument` 结构化枚举，风格完全由中文 `Text` 驱动；
提示词太短容易触发版权校验错误 `50000001`。`prompts.md` 里每首都备了中文提示词，
可直接复用。切官方 API 时，把 `params_of()` 换成请求体组装，
后处理（拼接 / 归一化 / 循环 / 清单 / 验收）整条链路不动。

同理，Suno / Udio / MusicGen / 自有 HF token 的 ZeroGPU 也可以按这个方式接入：
**只替换「拿模型原始音频」这一步**，其余全部复用。

## 6. 依赖

Python 3.10+、`numpy`、`scipy`、`ffmpeg`（须带 `libvorbis` 编码器）、`ffprobe`。
HTTP 客户端只用标准库 `urllib`。`references/spec.md` 的 LUFS 实测依赖
`ffmpeg -af loudnorm=I=-16:TP=-1.0:LRA=11:print_format=json -f null -` 的 stderr。
