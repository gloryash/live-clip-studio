# 重新生成候选 QA 结果

## 环境

- 测试命令：`uv run pytest -q`（84 passed）
- 启动命令：`start.command`
- 前端 URL：`http://127.0.0.1:8788/workspace/224ce9e4-1363-4016-bd9d-5918b7871ecd`
- 后端 URL：`http://127.0.0.1:8788`

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 只重新生成候选 | API / pytest | 不提交 Whisper，新候选文件使用 `0.35` | PASS | API 返回 `speaker_count: 11`, `similarity_threshold: 0.35`；回归测试断言 `processor.submitted == []` | |
| 字幕保持不变 | pytest / SHA-256 | `segments.json` 和 `speaker-turns.json` 字节不变 | PASS | 前后分别为 `5bc86780...eb2f1` 和 `f278e46a...4beca` | |
| 旧候选状态清除 | pytest / 文件检查 | 旧 assignments/predictions 删除，人工数据保留 | PASS | API 后 `confirmed_count: 0`；`manual-speakers.json` 保留 | 目标任务执行前 assignments/predictions 已不存在，删除行为由 pytest 覆盖 |
| 声纹缓存缺失提示 | pytest / API | 返回 409 与可理解提示 | PASS | `test_rebuild_candidates_keeps_existing_result_when_embeddings_missing` | |
| 新按钮可用 | Agent Browser | 桌面和移动端可见，确认文案无歧义 | PASS | `docs/qa/screenshots/speaker-candidate-rebuild-desktop.jpg`, `speaker-candidate-rebuild-mobile.jpg` | 1440x1000 / 390x844 |
| 页面刷新新候选 | Agent Browser / network | 成功后显示新候选数，不进入 Whisper 转写状态 | PASS | `POST .../speaker-candidates/rebuild` 200；页面显示 `11 个候选人物`；无页面错误 | |

## 返工记录

| 轮次 | 失败项 | 修复动作 | 结果 |
| --- | --- | --- | --- |
