# 故障排查与恢复

按症状查表。**任何恢复动作都优先复用 `tmp/` 里的模型片段缓存**，
不要重新提交已经成功的推理（CPU Space 一段要跑 8–25 分钟）。

## 生成阶段

| 症状 | 原因 / 处理 |
| --- | --- |
| `You have exceeded your ZeroGPU quota` 或 `error: null` | 路线 A 匿名配额耗尽。换 Space、换代理、本地重置都无效；改走 CPU Space 或让用户提供凭据。不要写本地合成兜底。 |
| `Synth timeout after 600s` | 单段超过 CPU Space 固定 600 s 合成上限。降到 `40s / 4steps`，用多段拼接。 |
| `SSE 超过 1500s` / `LM timeout after 901s` | 某个 CPU Space 偶发卡死。重试 2 次仍失败会跳过该首；**不要从头重跑**，只补缺失片段（见下）。 |
| `502` / 连接被重置 / SSE 流提前结束 | Space 冷启动或临时重启，直接重试；`--skip-existing` 保证已完成的段不会重烧。 |
| `未拿到 event_id` / `FnIndexInferError` | 用错了端点。必须 `/gradio_api/call/<endpoint>`，不是 `/run/predict`。 |
| `返回值里找不到音频文件` | 返回的是相对 `path`，`download_audio()` 会拼 `/gradio_api/file=`；若格式变了，检查 complete 事件的原始 JSON。 |
| 生成时长看起来是 84 s（请求 60 s） | mp3 头码率错误导致 ffprobe 虚报 ~1.38 倍。**以解码 PCM 样本数为准**，不要按 ffprobe 裁。 |

### 只补一个缺失片段

失败的段不会写入 `tmp/{slug}_{layer}_seg{i}.mp3`（或文件 < 50 KB）。
换另一个后端单独补这一段，然后重跑拼接即可（会复用其余全部缓存）：

```python
import gen_music_space as gs, gen_music_segments as seg, gen_music_api as g, space_client as sc
st = next(x for x in g.STYLES if x['no'] == 1)
i = 0
seed = 700000000 + st['no'] * 123457 + i * 7919
base = 'https://werecooking-ace-step-cpu.hf.space'   # 换一个后端
r = sc.call_space(base, gs.ENDPOINT,
                  gs.params_of(st, 'fight', 40, seed, 4), timeout=1500)
sc.download_audio(base, r['data'], seg.seg_path(st, 'fight', i))
```

然后：

```bash
python gen_music_segments.py --only 1 --force
```

`--force` 只强制重做本地拼接/归一化，已有片段一律复用，不消耗模型算力。

## 后处理阶段

| 症状 | 原因 / 处理 |
| --- | --- |
| LUFS 偏到 −18、峰值超标 | CPU 输出 mp3 已削波到 0 dBFS，直接按峰值衰减会压低响度。跑 `python fix_levels.py`（可重跑，不调模型）：先做无记忆 `tanh` 峰值整形，再 −16 LUFS，WAV 峰值控制在 −2 dBFS。 |
| OGG 峰值比 WAV 高约 +0.5 dB | Vorbis 有损编码过冲。`fix_levels.WAV_CEILING_DB = -2.0` 就是为此留的余量，不要用动态限幅（会破坏循环点）。 |
| 成品低于 60 s | 单次 60 s 片段去静音（~5 s）+ 2 s 循环淡化后只剩 ~53 s。改用 `2 段 × 40 s` 拼接。 |
| 中间出现 7–8 s 空档 | 模型自带静音尾。每段先 `common_trim()` 去尾再拼接（`gen_vocal_test.py` 里有实现）。 |
| 循环接缝指标 > 4 / 听到咔哒 | 源音频尾部本身有硬切被折回头部。用 `pick_loop_T()` 在尾部 1.2 s 内挑最平滑的边界（实测 4.07 → 0.40）。 |
| 去咔哒后音乐变闷 | `declick()` 阈值太松会误伤正常瞬态（0.15 时误修 2881 处）。只修**孤立单样本跳变**：`>0.35`、±20 样本内唯一、上限 64 处（本次只修 11 处）。 |
| 两层循环点不一致 / 抛错 | `process_pair_v2()` 会直接报错。检查两层是否用了同 seed / 同 duration，以及是否所有片段统一裁到全局最短样本数。 |
| `manifest.json` 里混进了测试曲 | 测试曲默认不写清单。若误写，删掉对应条目后重跑 `verify_music.py`。 |

## 验收 / 试听阶段

| 症状 | 原因 / 处理 |
| --- | --- |
| `preview.html` 打开空白、音频加载失败 | 用 `file://` 直接打开会被 CORS 拦 fetch。起本地服务：`cd music && python -m http.server 8765 --bind 127.0.0.1`，访问 `http://127.0.0.1:8765/preview.html`。 |
| 平静层还是有鼓点 | 风格 `en` / `cn` 描述里原本带锣鼓词。确认 `strip_percussion()` 生效，且 `CALM_SUFFIX` 里显式写了 `NO drums / NO percussion / NO gongs`。 |
| 交战层不够紧张 | `FIGHT_SUFFIX` 要把「每拍重击、密集锣鼓、打击乐处于最前景」写进 caption；只有 `intense percussion` 太弱。参考历史实测：起音密度 65.4 → 137.4 次/分。 |
| 起音密度没拉开 | 验收里这只是兜底（`fight > calm*0.8`），不是风格判定。以试听和 `tmp/verify_report.json` 的包络起伏为准。 |
| 唱腔"没唱出来" | CPU 4-step + 量化模型不保证每次出清晰人声。看 `tmp/vocal_test_report.json` 的上谐波比与频谱图，或提高 steps / 换有 GPU 的后端；指标只作参考，以试听为准。 |

## 不要做的事

- 不要因为接口失败就在本地用正弦波/鼓机"补一首"。
- 不要删 `tmp/` 后重跑整批；那里是唯一的推理缓存。
- 不要用 `ffprobe` 的时长做裁剪或写 `loop` 点。
- 不要用带状态的动态压缩/限幅做归一化，会破坏无缝循环。
- 不要把可选的测试曲、实验片段写进 `manifest.json`。
