# AI 音乐生成提示词（10 首 × 平静 / 交战）

来源：`../音乐.md`。每首两条，同一 BPM、同一调式、同一小节数，便于叠放。

## 用法 A：本仓库脚本（ACE-Step 1.5 CPU Space，免密钥）

当前生产链路用「英文提示词」的 caption 调 `gen_music_segments.py` 的 `/generate`，
两个 CPU Space 各跑一层，同 seed + 同 BPM + 同 40s 片段，再本地拼接成 60–120s 无缝循环。

```bash
python -u gen_music_segments.py --all --skip-existing --duration 40 --segments 2 --steps 4
python gen_music_segments.py --only 2 --force   # 重做单首
python verify_music.py                          # 验收
```

> `gen_music_api.py` 的 ZeroGPU 客户端（路线 A）因匿名配额耗尽已停用，仅保留公共函数。

## 用法 B：火山引擎 GenBGM（中文提示词，需 AK/SK）

把下面每首的「中文提示词」整段作为 `Text` 传入，见 README.md。
GenBGM v5.0 已取消 Genre/Mood/Instrument 结构化枚举，风格完全由中文 Text 驱动。

## 用法 C：Suno / Udio / MusicGen

用「英文提示词」；平静版追加 `slow to medium tempo, sparse, atmospheric, seamless loop`，
交战版追加 `faster tempo, intense percussion, urgent, same key and bar count, seamless loop`。

---

## 1. 西皮流水（京剧）

- 主音 MIDI `74` / D 徵调 / 音阶 `0,2,5,7,9`
- 平静 98 BPM · 表格交战 132 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 京胡 / 京胡 · 弹拨 琵琶 · 锣鼓 板鼓、大锣、小锣、钹（急急风）

**平静版（英文 / ACE-Step）**

```
Chinese Peking opera xipi liushui, jinghu fiddle lead, pipa plucked strings, D zhi pentatonic mode, D 徵调, 98 BPM, 京胡 / 京胡, 琵琶, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Chinese Peking opera xipi liushui, jinghu fiddle lead, pipa plucked strings, bangu drum, daluo and xiaoluo gongs, D zhi pentatonic mode, D 徵调, 98 BPM, 京胡 / 京胡, 琵琶, 板鼓、大锣、小锣、钹（急急风）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
京剧西皮流水过门，京胡领奏，节奏明快，D 徵调。游戏配乐BGM，D 徵调，约 98 BPM，主奏京胡 / 京胡，弹拨琵琶，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
京剧西皮流水过门，京胡领奏，板鼓与大锣小锣点子紧密，节奏明快，D 徵调，带戏曲锣鼓经「急急风」气质。游戏配乐BGM，D 徵调，约 98 BPM，主奏京胡 / 京胡，弹拨琵琶，纯器乐无人声，打击乐板鼓、大锣、小锣、钹（急急风），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 2. 秦腔苦音（秦腔）

- 主音 MIDI `69` / A 苦音 / 音阶 `0,2,4,6,7,9,10`
- 平静 80 BPM · 表格交战 118 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 板胡 / 唢呐 · 弹拨 三弦 · 锣鼓 大鼓、大锣、梆子

**平静版（英文 / ACE-Step）**

```
Chinese Qinqiang opera kuyin mode, banhu fiddle lead, suona, A kuyin scale with raised fourth and flat seventh, A 苦音, 80 BPM, 板胡 / 唢呐, 三弦, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Chinese Qinqiang opera kuyin mode, banhu fiddle lead, suona, heavy Chinese bass drum and big gong, A kuyin scale with raised fourth and flat seventh, A 苦音, 80 BPM, 板胡 / 唢呐, 三弦, 大鼓、大锣、梆子, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
秦腔苦音，板胡高亢苍凉领奏，唢呐助阵，节奏如黄土高原上的呐喊，A 调带升四降七的苦音色彩。游戏配乐BGM，A 苦音，约 80 BPM，主奏板胡 / 唢呐，弹拨三弦，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
秦腔苦音，板胡高亢苍凉领奏，唢呐助阵，大鼓与大锣沉重有力，节奏如黄土高原上的呐喊，A 调带升四降七的苦音色彩。游戏配乐BGM，A 苦音，约 80 BPM，主奏板胡 / 唢呐，弹拨三弦，纯器乐无人声，打击乐大鼓、大锣、梆子，紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 3. 花鼓小调（花鼓戏）

- 主音 MIDI `71` / B 宫五声 / 音阶 `0,2,4,7,9`
- 平静 106 BPM · 表格交战 138 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 竹笛 / 唢呐 · 弹拨 三弦 · 锣鼓 小锣、木鱼（带摇摆）

**平静版（英文 / ACE-Step）**

```
Chinese Huagu opera folk tune, dizi bamboo flute and suona call and response, B 宫五声, 106 BPM, 竹笛 / 唢呐, 三弦, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Chinese Huagu opera folk tune, dizi bamboo flute and suona call and response, small gong and woodblock, swung rhythm, B gong pentatonic, B 宫五声, 106 BPM, 竹笛 / 唢呐, 三弦, 小锣、木鱼（带摇摆）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
欢快俏皮，竹笛与唢呐问答，带轻微摇摆的节奏，B 宫五声调。游戏配乐BGM，B 宫五声，约 106 BPM，主奏竹笛 / 唢呐，弹拨三弦，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
湖南花鼓戏小调，欢快俏皮，竹笛与唢呐问答，小锣木鱼点缀，带轻微摇摆的节奏，B 宫五声调。游戏配乐BGM，B 宫五声，约 106 BPM，主奏竹笛 / 唢呐，弹拨三弦，纯器乐无人声，打击乐小锣、木鱼（带摇摆），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 4. 黄梅采茶（黄梅戏）

- 主音 MIDI `67` / G 大调七声 / 音阶 `0,2,4,5,7,9,11`
- 平静 78 BPM · 表格交战 108 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 二胡 / 竹笛 · 弹拨 古筝 · 锣鼓 板鼓、小锣

**平静版（英文 / ACE-Step）**

```
Chinese Huangmei opera, erhu lyrical lead, dizi flute and guzheng zither accompaniment, fresh and gentle, G major heptatonic, G 大调七声, 78 BPM, 二胡 / 竹笛, 古筝, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Chinese Huangmei opera, erhu lyrical lead, dizi flute and guzheng zither accompaniment, fresh and gentle, G major heptatonic, G 大调七声, 78 BPM, 二胡 / 竹笛, 古筝, 板鼓、小锣, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
安徽黄梅戏，二胡抒情领奏，竹笛和古筝伴奏，节奏舒缓委婉，如《打猪草》般清新，G 大调七声音阶。游戏配乐BGM，G 大调七声，约 78 BPM，主奏二胡 / 竹笛，弹拨古筝，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
安徽黄梅戏，二胡抒情领奏，竹笛和古筝伴奏，节奏舒缓委婉，如《打猪草》般清新，G 大调七声音阶。游戏配乐BGM，G 大调七声，约 78 BPM，主奏二胡 / 竹笛，弹拨古筝，纯器乐无人声，打击乐板鼓、小锣，紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 5. 川江号子（四川民谣）

- 主音 MIDI `67` / G 宫五声 / 音阶 `0,2,4,7,9`
- 平静 94 BPM · 表格交战 126 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 竹笛 / 唢呐 · 弹拨 三弦 · 锣鼓 大鼓、梆子（明显摇摆）

**平静版（英文 / ACE-Step）**

```
Sichuan Chuanjiang haozi folk work song, dizi flute and sanxian lute, call and response, G 宫五声, 94 BPM, 竹笛 / 唢呐, 三弦, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Sichuan Chuanjiang haozi folk work song, dizi flute and sanxian lute, call and response, strongly swung rhythm, G gong pentatonic, G 宫五声, 94 BPM, 竹笛 / 唢呐, 三弦, 大鼓、梆子（明显摇摆）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
四川民谣，竹笛与三弦弹拨，节奏带明显摇摆，川江号子般的呼应感，轻松诙谐，G 宫五声调。游戏配乐BGM，G 宫五声，约 94 BPM，主奏竹笛 / 唢呐，弹拨三弦，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
四川民谣，竹笛与三弦弹拨，节奏带明显摇摆，川江号子般的呼应感，轻松诙谐，G 宫五声调。游戏配乐BGM，G 宫五声，约 94 BPM，主奏竹笛 / 唢呐，弹拨三弦，纯器乐无人声，打击乐大鼓、梆子（明显摇摆），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 6. 洞庭渔歌（湖南民谣）

- 主音 MIDI `64` / E 徵调 / 音阶 `0,2,5,7,9`
- 平静 70 BPM · 表格交战 104 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 二胡 / 唢呐 · 弹拨 古筝 · 锣鼓 大鼓、大锣（沉稳）

**平静版（英文 / ACE-Step）**

```
Hunan Dongting fishing folk song, broad and flowing like Liuyang River, erhu and guzheng arpeggios, E zhi pentatonic, E 徵调, 70 BPM, 二胡 / 唢呐, 古筝, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Hunan Dongting fishing folk song, broad and flowing like Liuyang River, erhu and guzheng arpeggios, E zhi pentatonic, steady drum, E 徵调, 70 BPM, 二胡 / 唢呐, 古筝, 大鼓、大锣（沉稳）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
湖南民谣，如《浏阳河》般悠长宽广，二胡与古筝，徵调，带江水般流动的分解和弦，E 徵调。游戏配乐BGM，E 徵调，约 70 BPM，主奏二胡 / 唢呐，弹拨古筝，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
湖南民谣，如《浏阳河》般悠长宽广，二胡与古筝，徵调，鼓点沉稳，带江水般流动的分解和弦，E 徵调。游戏配乐BGM，E 徵调，约 70 BPM，主奏二胡 / 唢呐，弹拨古筝，纯器乐无人声，打击乐大鼓、大锣（沉稳），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 7. 闽南采茶（福建民谣）

- 主音 MIDI `69` / A 羽调 / 音阶 `0,3,5,7,10`
- 平静 82 BPM · 表格交战 114 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 竹笛 / 二胡 · 弹拨 琵琶 · 锣鼓 木鱼、小锣（灵动）

**平静版（英文 / ACE-Step）**

```
Fujian Minnan tea-picking folk tune, pipa tremolo and dizi flute, agile, A yu pentatonic, A 羽调, 82 BPM, 竹笛 / 二胡, 琵琶, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Fujian Minnan tea-picking folk tune, pipa tremolo and dizi flute, agile, A yu pentatonic, woodblock and small gong, A 羽调, 82 BPM, 竹笛 / 二胡, 琵琶, 木鱼、小锣（灵动）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
福建闽南民谣，琵琶轮指与竹笛，如《采茶舞曲》般灵动，羽调，A 羽调。游戏配乐BGM，A 羽调，约 82 BPM，主奏竹笛 / 二胡，弹拨琵琶，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
福建闽南民谣，琵琶轮指与竹笛，如《采茶舞曲》般灵动，羽调，木鱼与小锣轻点节奏，A 羽调。游戏配乐BGM，A 羽调，约 82 BPM，主奏竹笛 / 二胡，弹拨琵琶，纯器乐无人声，打击乐木鱼、小锣（灵动），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 8. 信天游（陕北）

- 主音 MIDI `62` / D 羽调 / 音阶 `0,3,5,7,10`
- 平静 62 BPM · 表格交战 100 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 唢呐 / 板胡 · 弹拨 三弦 · 锣鼓 大鼓、大锣（极简、大跳长音）

**平静版（英文 / ACE-Step）**

```
Northern Shaanxi Xintianyou folk song, suona long soaring notes with wide leaps, D yu pentatonic, D 羽调, 62 BPM, 唢呐 / 板胡, 三弦, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Northern Shaanxi Xintianyou folk song, suona long soaring notes with wide leaps, free expansive rhythm, D yu pentatonic, minimal drum, D 羽调, 62 BPM, 唢呐 / 板胡, 三弦, 大鼓、大锣（极简、大跳长音）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
陕北信天游，唢呐低吟高亢的长音，音域宽、大跳，节奏自由舒展，如黄土高原上的呼喊，D 羽调。游戏配乐BGM，D 羽调，约 62 BPM，主奏唢呐 / 板胡，弹拨三弦，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
陕北信天游，唢呐低吟高亢的长音，音域宽、大跳，节奏自由舒展，如黄土高原上的呼喊，D 羽调，鼓点极简。游戏配乐BGM，D 羽调，约 62 BPM，主奏唢呐 / 板胡，弹拨三弦，纯器乐无人声，打击乐大鼓、大锣（极简、大跳长音），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 9. 江南小调（江南）

- 主音 MIDI `74` / D 宫五声 / 音阶 `0,2,4,7,9`
- 平静 76 BPM · 表格交战 108 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 竹笛 / 二胡 · 弹拨 古筝 · 锣鼓 梆子、小锣（轻盈）

**平静版（英文 / ACE-Step）**

```
Jiangnan sizhu silk and bamboo folk tune, dizi flute, guzheng and pipa, soft like Jasmine Flower, D 宫五声, 76 BPM, 竹笛 / 二胡, 古筝, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Jiangnan sizhu silk and bamboo folk tune, dizi flute, guzheng and pipa, soft like Jasmine Flower, D gong pentatonic, D 宫五声, 76 BPM, 竹笛 / 二胡, 古筝, 梆子、小锣（轻盈）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
江南丝竹小调，如《茉莉花》般柔美，竹笛和古筝琵琶，水乡的轻盈与烟雨，D 宫五声调，节奏舒缓。游戏配乐BGM，D 宫五声，约 76 BPM，主奏竹笛 / 二胡，弹拨古筝，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
江南丝竹小调，如《茉莉花》般柔美，竹笛和古筝琵琶，水乡的轻盈与烟雨，D 宫五声调，节奏舒缓。游戏配乐BGM，D 宫五声，约 76 BPM，主奏竹笛 / 二胡，弹拨古筝，纯器乐无人声，打击乐梆子、小锣（轻盈），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```

## 10. 二人转（东北）

- 主音 MIDI `69` / A 宫五声 / 音阶 `0,2,4,7,9`
- 平静 116 BPM · 表格交战 146 BPM（外部音频两条共用平静 BPM，见 README）
- 主奏 唢呐 / 唢呐 · 弹拨 三弦 · 锣鼓 大鼓、钹（咚恰两拍子）

**平静版（英文 / ACE-Step）**

```
Northeast Chinese Errenzhuan folk duet, suona and banhu call and response, lively, A 宫五声, 116 BPM, 唢呐 / 唢呐, 三弦, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, slow to medium tempo, gentle soothing and lyrical, sparse airy arrangement, soft sustained strings and solo melodic instrument, absolutely NO drums, NO percussion, NO gongs, NO rhythmic hits, quiet and floating, calm exploration layer, seamless loop, no fade in or fade out, no ambient sound effects
```

**交战版（英文 / ACE-Step）**

```
Northeast Chinese Errenzhuan folk duet, suona and banhu call and response, lively, strong dong-qia two-beat rhythm, A gong pentatonic, A 宫五声, 116 BPM, 唢呐 / 唢呐, 三弦, 大鼓、钹（咚恰两拍子）, game BGM soundtrack, orchestral and Chinese folk fusion, cinematic, instrumental, no lyrics, no vocals, no ambience SFX, no field recording, steady tempo, no tempo change, tense urgent and threatening, prominent heavy Chinese war drums, loud bangu drum and deep low drum pounding on every beat, dense rapid daluo xiaoluo gong crashes, fast percussion rolls and cymbal accents, relentless driving battle rhythm, aggressive martial percussion, drums and percussion are the dominant foreground layer, same key and bar count, seamless loop, no fade in or fade out, no ambient sound effects
```

**平静版（中文 / 火山引擎 GenBGM `Text`）**

```
东北二人转，唢呐与板胡对答，欢快泼辣，手绢翻飞般的热闹，A 宫五声调。游戏配乐BGM，A 宫五声，约 116 BPM，主奏唢呐 / 唢呐，弹拨三弦，纯器乐无人声，舒缓层：旋律抒情，配器极稀疏，只有拉弦与弹拨的长音，完全不要鼓点、不要锣鼓、不要任何打击乐与节奏敲击，安静飘逸，可无缝循环，无淡入淡出，不要环境音效
```

**交战版（中文 / 火山引擎 GenBGM `Text`）**

```
东北二人转，唢呐与板胡对答，欢快泼辣，节奏强烈的「咚恰」两拍子，手绢翻飞般的热闹，A 宫五声调。游戏配乐BGM，A 宫五声，约 116 BPM，主奏唢呐 / 唢呐，弹拨三弦，纯器乐无人声，打击乐大鼓、钹（咚恰两拍子），紧张层：大鼓与板鼓每拍重击，大锣小锣密集催打，钹与梆子急促加花，锣鼓经贯穿全曲并处于最前景，紧迫压迫、战意不屈，同调同小节数，可无缝循环，无淡入淡出，不要环境音效
```
