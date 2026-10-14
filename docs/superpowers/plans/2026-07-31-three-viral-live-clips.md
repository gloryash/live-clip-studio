# Three Viral Live Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从指定直播素材生成 3 条竖屏、单条小于 3 分钟、具备强前 5 秒钩子的成片。

**Architecture:** 用一个声明式 JSON 保存每条成片的片段顺序、标题、关键词和音效点；用单一 Python 编排脚本生成 FFmpeg filter graph、重排原视频、生成 ASS 动态字幕并导出 MP4。所有产物写入独立 `exports/viral-clips`，不修改源素材与转录文件。

**Tech Stack:** Python 3.12、FFmpeg 8、ffprobe、ASS 字幕、JSON

**QA Result File:** `docs/qa/2026-07-31-f03d40e1-three-viral-live-clips.md`

---

## 文件结构

- Create: `editing/viral_clips.json`，保存 3 条片子的片段、钩子与包装配置。
- Create: `editing/render_viral_clips.py`，读取配置并生成字幕、filter graph 和 MP4。
- Create: `exports/viral-clips/*.mp4`，最终成片。
- Create: `exports/viral-clips/*.srt`，成片时间轴字幕。
- Create: `exports/viral-clips/render-report.json`，记录输入、输出、时长和编码信息。
- Create: `docs/qa/2026-07-31-three-viral-live-clips.md`，记录验收矩阵与证据。

## QA 矩阵

| 需求项 | 实现入口 | 验证方式 | 通过标准 | 证据位置 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 生成 3 条独立视频 | `editing/viral_clips.json`、渲染脚本 | 文件计数 + `ffprobe` | 恰好 3 个可解码 MP4 | `exports/viral-clips/render-report.json` | PENDING |
| 每条小于 3 分钟 | 片段配置 | `ffprobe -show_entries format=duration` | 每条 `duration < 180` | QA 文档 | PENDING |
| 开头 2 秒有强观点 | 钩子重排、顶部标题 | 抽帧 + 试听 | 0–2 秒出现完整强观点，非寒暄 | `exports/viral-clips/qa/*-000.jpg` | PENDING |
| 开头 5 秒建立悬念或反差 | 标题与第二句 | 抽帧 + 试听 | 5 秒前完成冲突/问题/反差设置 | `exports/viral-clips/qa/*-005.jpg` | PENDING |
| 字幕清晰且不遮挡 | ASS 字幕安全区 | 抽帧检查 | 无超框、无三行堆叠、人物关键区域可见 | `exports/viral-clips/qa/*.jpg` | PENDING |
| 音频清晰无爆音 | FFmpeg loudness/peak 检测 | `ebur128`、`volumedetect`、试听 | 无削波，讲话始终可辨 | QA 日志 | PENDING |
| 无黑帧和异常断句 | 成片扫描、关键切点试听 | `blackdetect` + 人工检查 | 无非设计黑帧，切点不吞字 | QA 文档 | PENDING |
| 原素材保持不变 | 独立输出目录 | 输入文件哈希前后对比 | `source.mp4` SHA-256 不变 | QA 文档 | PENDING |

### Task 1: 固化剪辑清单

- [ ] 从 AI 字幕 JSON 中为每条视频选择完整语义片段，片段边界贴合字幕起止时间。
- [ ] 在 `editing/viral_clips.json` 中写入 `id`、`title`、`hook`、`segments`、`keywords` 和目标时长。
- [ ] 汇总片段时长，确保每条预计时长小于 180 秒。

### Task 2: 实现渲染器

- [ ] 读取剪辑清单与 AI 字幕，映射原始时间到成片时间。
- [ ] 生成每条视频的 SRT 与 ASS，限制双行并应用标题、关键词颜色和安全区。
- [ ] 生成 FFmpeg filter graph，按清单裁剪并拼接音视频，添加轻推近、标题和钩子音效。
- [ ] 使用 H.264/AAC 导出，保留 `912x1920`、`yuv420p` 和快速启动元数据。
- [ ] 生成 `render-report.json`，记录每条成片的 duration、codec、resolution 和源片段。

### Task 3: 渲染三条成片

- [ ] 运行 `python3 editing/render_viral_clips.py`。
- [ ] 检查渲染命令全部退出码为 0；失败时保存对应 FFmpeg stderr 并只重跑失败视频。
- [ ] 确认输出目录恰好包含 3 个 MP4 与 3 个 SRT。

### Task 4: 技术 QA

- [ ] 用 `ffprobe` 验证时长、分辨率、编码和音视频流。
- [ ] 用 `blackdetect` 扫描非设计黑帧。
- [ ] 用 `ebur128` 和 `volumedetect` 检查响度与峰值。
- [ ] 对每条抽取 0、2、5 秒及中后段 JPEG，检查字幕、标题和安全区。
- [ ] 对比渲染前后 `source.mp4` SHA-256。

### Task 5: 内容 QA 与修订

- [ ] 在本地播放器逐条试听开头 10 秒、所有拼接点和结尾。
- [ ] 检查 0–2 秒强观点、0–5 秒反差/悬念是否成立。
- [ ] 对吞字、重复、字幕断行或音效遮挡进行最多 3 轮局部修订。
- [ ] 更新 QA 文档所有行的 `PASS`、`FAIL` 或 `BLOCKED` 状态和证据。

### Task 6: 最终交付检查

- [ ] 运行完整验证命令并读取全部输出。
- [ ] 确认 QA 矩阵没有 `FAIL` 或必需项 `BLOCKED`。
- [ ] 在 9300 可见浏览器或系统播放器中打开成片，确认用户可直接预览。

## 最终验证命令

```bash
python3 editing/render_viral_clips.py
find exports/viral-clips -maxdepth 1 -name '*.mp4' -print
ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,codec_name,width,height -of json exports/viral-clips/*.mp4
shasum -a 256 data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/source.mp4
```
