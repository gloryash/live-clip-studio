# Live Clip Studio 历史记录与真实直播样例 QA

## 环境

- 日期：2026-07-24
- 项目：`/Users/panyupeng/ai/视频加速提纯/live-clip-studio`
- 本地 URL：`http://127.0.0.1:8788`
- 可视浏览器：CDP `9300`，会话 `run-9300-liveclip`
- Whisper：`http://127.0.0.1:8765`，模型 `mlx-community/whisper-large-v3-turbo`
- 真实样例：`/Users/panyupeng/Movies/欢迎来到我的直播间_20260701163953.mp4`
- 真实任务：`f03d40e1-0f06-4454-a83f-1a512c7e4ae2`
- 文件指纹：`7746cd5b8d151aa8df9b8f849dcf908eea795b44f0117e89e25ab08931f7d73f`，`346,721,024` bytes

## 真实分析结果

- 时长：`01:24:05.640`
- 字幕 / 说话人时间轴：2,313 条，2 位匿名说话人
- 关键帧：5,055 张候选帧，经去重后保留 1,026 张；`capped=false`
- 原始转写、字幕、说话人分离、关键帧 JPEG 都写入该任务的本地 `data/<job_id>/` 目录。

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 |
| --- | --- | --- | --- | --- |
| 历史带库 | 9300 可视浏览器 + `GET /api/jobs` | 首页列出现有任务及摘要 | PASS | 首页显示本真实任务和 Mercury 样例；接口返回 2 条 |
| 相同内容复用 | 9300 再次上传同一路径的真实文件 | 返回并打开原 `job_id`，历史数量不增加 | PASS | 上传后 URL 为 `/workspace/f03d40e1-0f06-4454-a83f-1a512c7e4ae2`；上传前后均为 2 条 |
| 复用提示 | 可视工作台 DOM | 显示未重复分析的明确提示 | PASS | `screenshots/history-reuse-notice.jpg`；文本为“已加载上次记录：内容完全相同，未重复分析。” |
| 精确指纹匹配 | API 自动测试 | 按完整 SHA-256 + 文件大小复用，不依赖文件名 | PASS | `tests/test_jobs_api.py` |
| 分功能重跑 | API 自动测试 + 页面按钮 | 字幕重跑保留关键帧；关键帧重跑不影响字幕；均要求显式动作 | PASS | `tests/test_jobs_api.py`；`tests/test_keyframes.py`；工作台“重新生成字幕 / 重新提取”按钮 |
| 重跑期旧字幕不误显示 | API 自动测试 | 字幕状态未 ready 时返回 `202`，不把旧产物当作新结果 | PASS | `tests/test_jobs_api.py` |
| 真实字幕与说话人 | 本地产物 + 可视时间轴 | 保留原文、精确时间、匿名说话人 | PASS | `transcript/segments.json`、`transcript/speaker-turns.json`；2,313 条，2 人 |
| 实时关键帧 | 9300 打开关键帧面板 + manifest | 首次打开后按需启动、无张数上限 | PASS | `keyframes/frames.json`：`candidate_count=5055`，`frame_count=1026`，所有帧 `capped=false` |
| `2×20` 网格 | 9300 DOM + JPEG 截图 | 40 张一页、2 列 | PASS | `screenshots/history-real-keyframes-2x20.jpg`；DOM 40 张、两列 |
| `10×10` 网格 | 9300 DOM + JPEG 截图 | 100 张一页、10 列 | PASS | `screenshots/history-real-keyframes-10x10.jpg`；DOM 100 张、十列 |
| 点击关键帧定位视频 | 9300 DOM | 视频跳到所点关键帧时间 | PASS | 点击 `00:00:02.300` 后播放器 `currentTime=2.697006`（媒体 seek 的正常小于 0.5 秒误差） |
| 页面错误 | Agent Browser `errors` | 无未捕获页面错误 | PASS | 空输出 |
| 人工说话人标注 | 9300 可视浏览器 + API | 每条字幕右侧有两枚独立按钮；不触发视频跳转 | PASS | `screenshots/manual-speaker-annotation-v2.jpg`；DOM 显示两个按钮，未发生交互嵌套 |
| 标注保存与恢复 | API 自动测试 | 单条点击持久化为本地 `manual-speaker-labels.json` | PASS | `tests/test_jobs_api.py::test_manual_speaker_annotation_is_persisted_and_returned` |
| 训练集导出保护 | 真实 API + 自动测试 | 未标完时禁用导出并返回 `409 ANNOTATIONS_INCOMPLETE`；完整标注导出 JSONL | PASS | 真实任务 `0 / 2313` 返回 409；`tests/test_jobs_api.py::test_training_export_requires_complete_manual_labels_then_returns_jsonl` |
| 快捷键自动标注模式 | Web 合同测试 + 9300 可视浏览器 | 开关明确；左右键映射两位说话人；保存后可自动推进 | PASS | `tests/test_web_contract.py::test_workspace_exposes_keyboard_auto_annotation_mode_and_smart_preview`；页面显示“快捷标注 ON” |
| 长字幕智能预听点 | 9300 可视浏览器真实 29.98 秒字幕 | 切换时暂停并靠近口播开始位置，空格立即播放 | PASS | `screenshots/auto-annotation-smart-preview.jpg`；`30.000–59.980` 秒字幕定位到 `58.380` 秒 |
| 空格播放控制 | 9300 键盘事件 | 首次空格播放，再次空格暂停，不触发页面滚动 | PASS | 实测 `paused: true → false → true` |

## 自动验证

本文件最终应配合以下当次结果阅读：

```bash
uv run pytest -q
uv run python -m compileall -q live_clip_studio
curl -fsS http://127.0.0.1:8788/api/health
find docs/qa/screenshots -type f -name '*.png'
```

截图均以 JPEG 保存，避免把大 PNG 带入项目和上下文。
