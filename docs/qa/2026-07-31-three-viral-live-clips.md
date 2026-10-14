# QA 结果：三条中亚直播切片

## 环境

- 源任务：`02a0cf90-fd57-4117-b207-df0d5b0acb6e`
- FFmpeg：8.1.2
- 可见浏览器：Chrome CDP 9400，session `shared-9400`
- 输出目录：`data/02a0cf90-fd57-4117-b207-df0d5b0acb6e/exports/`

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 |
| --- | --- | --- | --- | --- |
| 三条独立成片 | 文件与 `ffprobe` | 恰好 3 个可解码 MP4 | PASS | 三个 `01/02/03-*.mp4`；全片 `ffmpeg -v error -f null -` 无错误 |
| 每条小于 3 分钟 | `ffprobe` | 每条小于 180 秒 | PASS | 95.228s、169.928s、179.214s |
| 2 秒钩子 | 0.5s/2s 抽帧 | 2 秒内出现明确反差、收益或风险 | PASS | `exports/qa/*-0.5s.jpg`、`*-2s.jpg` |
| 5 秒主题成立 | 5s 抽帧 | 5 秒内明确数据、问题或风险框架 | PASS | `exports/qa/*-5s.jpg` |
| 字幕可读准确 | 0.5s/5s/中段/尾帧检查 | 不越界、不遮脸，无已发现明显错字 | PASS | `exports/qa/*-mid.jpg`、`*-tail.jpg`；已完成一轮字幕返工 |
| 画面和声音正常 | 解码、`blackdetect`、`silencedetect` | 无解码错误、异常黑帧、超过 2 秒异常静音 | PASS | 三条扫描均无匹配输出；AAC 48 kHz |
| 真实浏览器可播放 | Agent Browser 9400 | 可加载、播放、跳转中段与尾部 | PASS | 三条 `readyState=4`；播放时 `paused=false`；分辨率 720×1512 |

## 浏览器证据

- 成片 1：`duration=95.228`，跳转中段后 `currentTime=47.898641`，`paused=false`，`readyState=4`。
- 成片 2：`duration=169.928`，跳转尾部后 `currentTime=169.24866`，`paused=false`，`readyState=4`。
- 成片 3：`duration=179.214`，跳转尾部后 `currentTime=178.517043`，`paused=false`，`readyState=4`。

## 返工记录

| 轮次 | 失败项 | 修复动作 | 结果 |
| --- | --- | --- | --- |
| 1 | FFmpeg 缺少 `libass` | 改用 Pillow 透明覆盖视频 + `overlay` | PASS |
| 2 | 两处字幕瑕疵、音频 96 kHz | 修正文案并固定 `-ar 48000` | PASS |

## 结论

QA 共 7 项：7 PASS、0 FAIL、0 BLOCKED。
