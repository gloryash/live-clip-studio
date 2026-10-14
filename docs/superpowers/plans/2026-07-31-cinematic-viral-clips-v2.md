# 纪录片采访感病毒切片 V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把三个固定分屏直播切片升级为具有单人近景、反应镜头、画面内字幕和克制声音设计的纪录片采访风格成片。

**Architecture:** 新渲染器读取既有 edit manifest、说话人时间轴和字幕，先规划 3–8 秒的镜头清单，再用 FFmpeg 把源分屏重构为左人物近景、右人物近景和双人全景。Pillow 生成字幕与标题透明覆盖层，Python 生成无版权氛围音和提示音，最终统一混音并输出到 `exports-v2/`。

**Tech Stack:** Python 3.12、Pillow、FFmpeg 8、ffprobe、pytest、Agent Browser 9400。

**QA Result File:** `docs/qa/2026-07-31-cinematic-viral-clips-v2.md`

---

## 文件

- Create: `tools/render_cinematic_clips.py`：镜头规划、近景构图、字幕覆盖和声音设计。
- Create: `tests/test_render_cinematic_clips.py`：镜头长度、说话人映射、反应镜头和字幕精简测试。
- Create: `data/.../exports-v2/`：三个 V2 MP4、镜头清单、字幕层、声音层和 QA 截图。
- Create: `docs/production/2026-07-31-cinematic-viral-clips-v2.md`：制作与返工记录。

## QA 矩阵

| 需求项 | 实现入口 | 验证方式 | 通过标准 | 证据位置 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 三条 V2 且不覆盖 V1 | 独立输出目录 | 文件与 SHA-256 | V1 保留，V2 恰好 3 条 | `exports-v2/` | PENDING |
| 多机位采访感 | shot planner | 镜头清单与抽帧 | 每条包含 left/right/dual，3–8 秒为主 | `*-shots.json` | PENDING |
| 人脸构图 | FFmpeg crop graph | 多时点抽帧 | 人脸完整，近景不越界 | `exports-v2/qa/*.jpg` | PENDING |
| 字幕升级 | Pillow overlay | 视觉检查 | 两行内、画面内、不遮嘴、关键字克制强调 | QA 截图 | PENDING |
| 悬念与声音 | score + cue generator | 波形、响度和播放 | 有氛围与提示音但人声清晰 | QA 文档 | PENDING |
| 时长与编码 | ffprobe | 元数据检查 | 每条小于 180 秒，720×1512，H.264/AAC 48k | QA 文档 | PENDING |
| 浏览器播放 | Agent Browser 9400 | 开始、中段、尾部播放 | `readyState=4`，可播放和跳转 | QA 文档 | PENDING |

## 实施任务

1. 写镜头规划测试：按说话人合并短句，限制主镜头 3–8 秒，每隔若干镜头加入短反应镜头。
2. 实现说话人映射与镜头规划，输出可审计的 `shots.json`。
3. 实现左近景、右近景、双人全景与模糊同源背景的 FFmpeg 构图。
4. 实现两行画面内字幕、说话人标签、数字与风险词强调。
5. 生成三种不同情绪的低强度背景音和段落提示音，与原声混合。
6. 渲染三个 V2，抽取开场、镜头切换、中段、结尾截图并进行最多三轮定点返工。
7. 全片解码、黑帧、静音、响度、元数据与 9400 浏览器播放验收。

## 最终验证

```bash
uv run pytest tests/test_render_cinematic_clips.py -q
python3 tools/render_cinematic_clips.py --manifest edits/02a0cf90-fd57-4117-b207-df0d5b0acb6e/edit-manifest.json --render
ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,width,height,sample_rate data/02a0cf90-fd57-4117-b207-df0d5b0acb6e/exports-v2/*.mp4
```

预期：测试通过；三条 V2 均小于 180 秒；QA 矩阵全部 PASS。
