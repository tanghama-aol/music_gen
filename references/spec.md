# 外部 BGM 资产契约

本文件是产出物的验收口径。生成前先确认目标项目的规格文档（例如 `音乐.md`）；
若没有规格文档，默认采用下面这套契约。

## 1. 硬性约束：不许程序化合成

**所有声音必须由音乐生成大模型推理产生。** 严禁在本地写音符、音色、MIDI、
振荡器、包络、鼓机、采样拼接来"造"音乐。本地允许且只允许做：

- 解码模型返回的 mp3 / wav
- 去头尾静音、多个模型片段之间的等功率交叉淡化
- 首尾无缝循环交叉淡化
- 无记忆峰值整形、LUFS 增益、OGG Vorbis 编码
- 写清单、写试听页、跑客观验收

判断标准：删掉本地脚本后，音频内容本身应当无法被重新创造出来。
交叉淡化只是把**模型已生成的音频**接起来，不产生新音色，因此不违反约束。

## 2. 目录与清单

```
music/                                  # 管线脚本所在目录
├── game/public/assets/
│   ├── manifest.json                   # 游戏读取的清单
│   └── music/<slug>_calm.ogg
│   └── music/<slug>_fight.ogg
└── tmp/                                # 模型原始 mp3、中间 wav、报告（可删，但删了会重烧算力）
```

`manifest.json` 结构（字段含义与游戏端约定一致）：

```json
{
  "music": [
    {
      "name": "西皮流水（京剧）",
      "calm": "music/xipiliushui_calm.ogg",
      "fight": "music/xipiliushui_fight.ogg",
      "loop": [0, 74.16]
    },
    { "name": "只有平静层的曲子", "calm": "music/foo.ogg" }
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `name` | 曲名，切歌时显示；省略则用文件名 |
| `calm` | 必填，一直循环播放的舒缓层 |
| `fight` | 可选，紧张层；**必须与 calm 同速、同小节数、同调、同 loop 点** |
| `loop` | `[起点秒, 终点秒]`，两层必须完全相同；省略则整首循环 |

游戏内两层**同时播放**，靠音量交叉淡化切换，等功率增益为
`calm = cos(v·π/2)`、`fight = sin(v·π/2)`。不改速、不改 pitch，
因此两层必须在生成阶段就对齐，不能靠播放端补救。

> 若规格文档写了「平静 98 → 交战 132 BPM」，那是游戏内程序合成音轨的行为；
> 外部音频走叠放规则，两层共用同一个平静 BPM。

## 3. 数值验收口径

`verify_music.py` 逐条检查，明细写到 `tmp/verify_report.json`：

| 项 | 要求 |
| --- | --- |
| 时长 | 60–120 s，`loop[1]` 与实测时长差 < 0.06 s |
| 编码 | `vorbis`，44100 Hz，2 声道 |
| 响度 | 约 −16 LUFS（容差 ±1.2 LU，用 `ffmpeg loudnorm ... print_format=json` 的 `input_i` 实测） |
| 峰值 | ≤ −1 dBFS（解码后的 PCM 实测，不是 ffprobe 元数据） |
| 循环接缝 | `mean(|x[-1]−x[0]|) / mean(|diff(x)|)` < 4 |
| 双层等长 | `|dur(calm) − dur(fight)|` < 0.02 s |
| 双层对比 | 紧张层起音密度不低于平静层的 0.8 倍（只作异常兜底，不作风格判定） |
| 内容 | 无环境音效 / 无 field recording / 无 SFX，避免盖住脚步与枪声 |

额外的内容约定（写进提示词，靠人工试听确认）：

- `calm`：抒情、配器稀疏、**显式排除 drums / percussion / gongs / rhythmic hits**；
  风格描述里原本带锣鼓的词必须先剔除，否则模型照样加鼓。
- `fight`：紧张、有鼓点，**中国大鼓 / 板鼓每拍重击、大锣小锣密集、钹与梆子加花，
  打击乐处于最前景**。
- 两层都写 `seamless loop, no fade in or fade out, no ambient sound effects, steady tempo`。
- 默认纯器乐 `lyrics = "[Instrumental]"`；女声高腔衬腔是可选独立测试，不写进正式清单。

## 4. 对齐是怎么保证的

1. 每个片段编号 `i` 的 calm 与 fight 使用**同一个 seed**（`base_seed + i*7919`）、
   同一个 `bpm`、同一个 `duration`、同一个 `steps`，只有 `caption` 不同。
   `base_seed = 700000000 + no * 123457`。
2. 同 seed 独立生成优于 audio2audio 派生：实测色度相关 0.998、起音包络相关 0.896
   （a2a 为 0.997 / 0.880），且耗时更低。
3. 所有片段（含另一层）统一裁到**全局最短样本数**再拼接，保证两层的拼接位置一致。
4. `fix_levels.process_pair_v2()` 对两层做样本级共同裁剪、同一 2 s 循环交叉淡化，
   返回同一个 `loop` 值写进清单。任何一层循环点不一致会直接抛错。

## 5. 换项目时改哪里

只需要改 `gen_music_api.py` 里的 `STYLES` 列表，其余脚本不用动。每个元素字段：

```python
dict(no=1, slug="xipiliushui", name="西皮流水", opera="京剧", root=74,
     key="D 徵调", scale=[0,2,5,7,9], bpm=98, fight_bpm=132,
     lead="京胡 / 京胡", pluck="琵琶", perc="板鼓、大锣、小锣、钹（急急风）",
     cn="中文风格描述（给中文大模型 / 火山引擎用）",
     en="English style caption for ACE-Step / MusicGen style models")
```

- `slug` 决定文件名，必须是 ASCII，且全表唯一。
- `bpm` 是两层共用的速度；`fight_bpm` 只是规格文档里的参考值，不传给 CPU Space。
- `en` 会经 `strip_percussion()` 剔除鼓点词后成为 `calm` 的 caption，
  `fight` 则保留并追加 `perc` 与 `FIGHT_SUFFIX`。
- 如果要换风格基调，改 `CALM_SUFFIX` / `FIGHT_SUFFIX` / `COMMON` 三个常量即可。
- 改完跑 `python gen_music_api.py --prompts-only` 刷新 `prompts.md` 与 `preview.html`，
  不消耗模型算力。

## 6. 交付检查清单

- [ ] `python verify_music.py` 输出 `N/N 通过`
- [ ] `manifest.json` 条目数与 ogg 文件数匹配（每首 2 个文件）
- [ ] `preview.html` 已刷新，用本地 HTTP 服务试听（不能 `file://`，CORS 会拦 fetch）
- [ ] 拖动滑块从 0 → 1 时两层切换平滑、无相位打架、无爆音
- [ ] 循环点试听：首尾衔接无咔哒、无忽强忽弱
- [ ] 测试曲 / 临时产物**没有**写进 `manifest.json`
- [ ] 把 `game/` 整个目录拷进游戏仓库即可，无需改游戏代码
