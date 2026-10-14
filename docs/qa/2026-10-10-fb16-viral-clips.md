# QA 结果：fb16d67f 视频号传播切片（9 条）

- 输入：`data/fb16d67f-1141-4fa1-9706-4867926b0174/source.mp4`（6105s，912x1920 左右分屏直播）
- 输出：`exports/fb16-viral-clips/`（9 × mp4 / cover.jpg / srt，`publish.md`，`render-report.json`，`qa/`）
- 脚本：`editing/render_fb16_clips.py`（配置 `editing/fb16_clips.json`）、`editing/cover_fb16_clips.py`、`editing/qa_fb16_whisper.py`

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 |
| --- | --- | --- | --- | --- |
| 5–10 条切片 | 文件计数 | 9 条 | PASS | `exports/fb16-viral-clips/*.mp4` |
| 单条 1–3 分钟 | ffprobe | 60–180s | PASS | 74.1s–107.2s |
| 规格 | ffprobe | 1080x1920 / 30fps / H.264+AAC | PASS | `render-report.json` |
| 音画同步 | 视频/音频流时长 | 差值 < 0.1s | PASS | 最大差值 0.057s |
| 完整解码 | `ffmpeg -v error -f null` | 0 错误 | PASS | 9/9 无输出 |
| 响度 | ebur128 | -16 ~ -13 LUFS | PASS | -14.3 ~ -14.7 LUFS |
| 剪切点不吃字 | Whisper 反向转写 + diff | 剪切点附近只允许口头禅或同音差异 | PASS | `qa/whisper-qa.json`，相似度 0.934–0.975 |
| 开场标题 / 悬念标 / 转场 | 关键帧抽检 | 冷开场钩子 → 白闪 + 标题落入 → 名条 → 悬念卡 → 结尾互动卡 | PASS | `qa/sheet-1..3.jpg` |
| 镜头节奏 | 镜头表 | 单镜头不超过 7.5s | PASS | 最长 7.43s |
| 双人画面去掉 UI 白块 | 抽帧 | 不可见 | PASS | `qa/sheet-*.jpg` |
| 封面 | 目视 | 文字在 3:4 安全区内，无 UI 白块 | PASS | `qa/covers.jpg` |

## 返工记录

| 轮次 | 问题 | 处理 |
| --- | --- | --- |
| 1 | 长字幕在词中间断行（如"放/大到"） | 改用 jieba 词边界断句 |
| 1 | 双人反应镜头落在金句上 | 金句前后跳过 duo |
| 1 | 双人镜头露出右侧 UI 白块；特写头顶被裁 | 加 delogo；放宽特写裁切 |
| 2 | 第 07 条"假设你在"被吃掉（原时间戳只有 0.6s） | 片段重新转写，按真实时间 `retime` |
| 3 | 剪切点依赖 Whisper 时间戳，偶尔切进字音 | 在相邻句的真实空隙里按 20ms 能量最低点下刀 |
| 3 | 第 03 条原转写漏字 | 字幕改为原话"如果你领着AI" |
| 3 | 封面露出 UI 白块，部分帧模糊 | delogo + 从 16 个候选帧中挑最清晰的 |

## 已知限制

- 源视频码率只有 515kbps，单人画面放大约 2.4 倍后会偏软。
- 没有背景音乐（版权原因），建议在视频号发布时从平台曲库里添加。
- 剪切点的质检基于 ASR 反向转写，没有人工逐条试听。
