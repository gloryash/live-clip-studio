# QA 结果：f03d40e1 三条直播切片

## 环境

- 输入：`data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/source.mp4`
- 工作区 URL：`http://127.0.0.1:8788/workspace/f03d40e1-0f06-4454-a83f-1a512c7e4ae2`
- 可见浏览器：CDP `9300`，session `shared-9300`
- 渲染器：FFmpeg 8.1.2、ImageMagick

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 3 条独立 MP4 | 文件计数、ffprobe | 恰好 3 条且可解码 | PASS | `exports/viral-clips/render-report.json` | 均为 H.264/AAC、912x1920 |
| 单条小于 180 秒 | ffprobe | `duration < 180` | PASS | `render-report.json` | 104.503s、129.118s、173.769s |
| 2 秒钩子 | 抽帧、字幕首句、浏览器播放 | 强观点完整出现 | PASS | `exports/viral-clips/qa/hooks-final.jpg` | 第 1 条返工后原声 0 秒进入强观点 |
| 5 秒钩子 | 抽帧、浏览器播放 | 建立悬念或反差 | PASS | `exports/viral-clips/qa/hooks-final.jpg` | 三条均在 5 秒内完成冲突设定 |
| 字幕与标题 | 抽帧 | 清晰、不超框、不遮挡 | PASS | `hooks-final.jpg`、`mid-contact-sheet.jpg` | 钩子条下移，5.2 秒后消失 |
| 音频质量 | volumedetect、试听 | 无削波、无明显遮盖 | PASS | `exports/viral-clips/qa/*-volumedetect.log` | max -2.9/-4.6/-4.0 dB |
| 画面连续性 | blackdetect、抽帧、浏览器播放 | 无空白输出、无吞字 | PASS | `exports/viral-clips/qa/*-blackdetect.log` | 命中来自直播原画面黑色版式，抽帧仍有有效人物和字幕 |
| 源素材完整 | SHA-256 | 渲染前后相同 | PASS | `render-report.json` | 前后均为 `7746cd5b...f7d73f` |

## 浏览器证据

- `t4`：`01-ai-white-collar.mp4`
- `t5`：`02-leave-the-ship.mp4`
- `t6`：`03-first-100-users.mp4`
- 三个标签均位于 `shared-9300` 可见浏览器，可直接播放。

## 返工记录

| 轮次 | 失败项 | 修复动作 | 结果 |
| --- | --- | --- | --- |
| 1 | FFmpeg 缺少 `ass/libass` 滤镜 | 改为 ImageMagick 透明字幕层 + FFmpeg overlay | PASS |
| 2 | 第 1 条强观点原声晚于 2 秒；钩子条压脸 | 前移到 578.127 秒并下移钩子条 | PASS |

## 结论

QA 共 8 项：8 PASS、0 FAIL、0 BLOCKED。
