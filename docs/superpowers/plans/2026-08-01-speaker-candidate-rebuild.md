# 重新生成候选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不调用 Whisper、不改变字幕的前提下，使用现有声纹向量重新生成候选说话人。

**Architecture:** FastAPI 新增同步候选重建接口，复用 `discover_candidates` 和已持久化的 `segments.json` / `speaker-embeddings.npz`。前端新增独立按钮，请求成功后重载候选和字幕状态。

**Tech Stack:** Python 3.12, FastAPI, NumPy, vanilla JavaScript, pytest, Agent Browser

**QA Result File:** `docs/qa/2026-08-01-speaker-candidate-rebuild.md`

---

## 文件映射

- `live_clip_studio/app.py`：候选重建 API、文件验证与旧候选状态失效。
- `live_clip_studio/web/workspace.html`：新增“重新生成候选”按钮。
- `live_clip_studio/web/app.js`：确认框、API 请求、处理状态和候选刷新。
- `tests/test_jobs_api.py`：后端行为与错误路径回归测试。
- `tests/test_web_contract.py`：页面控件与请求契约测试。
- `docs/qa/2026-08-01-speaker-candidate-rebuild.md`：验收证据。

## QA 矩阵

| 需求项 | 实现入口 | 验证方式 | 通过标准 | 证据位置 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 只重新生成候选 | `POST /speaker-candidates/rebuild` | pytest / API | 新候选为 `0.35`，processor 未提交 | QA 结果文件 | PENDING |
| 字幕保持不变 | 同上 | pytest 字节比较 | `segments.json` / `speaker-turns.json` 不变 | QA 结果文件 | PENDING |
| 旧候选状态清除 | 同上 | pytest 文件检查 | assignments/predictions 删除，人工数据保留 | QA 结果文件 | PENDING |
| 缺少声纹数据时可理解 | 同上 | pytest / API | HTTP 409，原候选不被覆盖 | QA 结果文件 | PENDING |
| 新按钮与无歧义确认 | `#rebuild-speaker-candidates` | Agent Browser | 桌面/移动可见，文案清楚，无溢出 | `docs/qa/screenshots/` | PENDING |
| 成功后刷新候选 | `rebuildSpeakerCandidates()` | Agent Browser / network | 候选数更新，不进入 Whisper 状态 | QA 结果文件 | PENDING |

### Task 1: 后端候选重建 API

**Files:**
- Modify: `live_clip_studio/app.py`
- Test: `tests/test_jobs_api.py`

- [ ] **Step 1: 先写失败测试**

创建就绪任务，写入最小 `segments.json`、有效 `speaker-embeddings.npz`、旧候选文件、assignments/predictions 和人工数据。调用：

```python
response = client.post(f"/api/jobs/{job_id}/speaker-candidates/rebuild")
assert response.status_code == 200
assert response.json()["similarity_threshold"] == 0.35
assert processor.submitted == []
assert segments_path.read_bytes() == segments_before
assert turns_path.read_bytes() == turns_before
assert not assignments_path.exists()
assert not predictions_path.exists()
assert manual_speakers_path.exists()
assert manual_labels_path.exists()
```

- [ ] **Step 2: 验证 RED**

Run: `uv run pytest tests/test_jobs_api.py::test_rebuild_speaker_candidates_reuses_embeddings_without_whisper -q`

Expected: FAIL，路由不存在。

- [ ] **Step 3: 实现最小 API**

在 `app.py` 导入 `discover_candidates`，新增路由：验证任务，读取段和 NPZ，检查二维 embeddings/一维 indices/长度相等，调用 `discover_candidates(..., similarity_threshold=0.35)`，通过 `write_document` 原子覆盖候选文件，最后删除 assignments/predictions。

- [ ] **Step 4: 验证 GREEN**

Run: `uv run pytest tests/test_jobs_api.py::test_rebuild_speaker_candidates_reuses_embeddings_without_whisper -q`

Expected: PASS。

### Task 2: 后端错误路径

**Files:**
- Modify: `live_clip_studio/app.py`
- Test: `tests/test_jobs_api.py`

- [ ] **Step 1: 写缺少缓存的失败测试**

```python
response = client.post(f"/api/jobs/{job_id}/speaker-candidates/rebuild")
assert response.status_code == 409
assert response.json()["detail"]["code"] == "EMBEDDINGS_NOT_READY"
assert old_candidate_path.read_bytes() == old_candidate_bytes
```

- [ ] **Step 2: 运行并确认 RED**

Run: `uv run pytest tests/test_jobs_api.py::test_rebuild_candidates_keeps_existing_result_when_embeddings_missing -q`

Expected: FAIL，当前返回不符合 409 契约。

- [ ] **Step 3: 实现验证与异常转换**

在写入新候选前完成所有文件、JSON、NPZ 和索引检查。不完整返回 `EMBEDDINGS_NOT_READY`，结构无效返回 `EMBEDDINGS_INVALID`。

- [ ] **Step 4: 运行后端相关测试**

Run: `uv run pytest tests/test_jobs_api.py tests/test_speaker_workflow.py -q`

Expected: PASS。

### Task 3: 工作台按钮与刷新交互

**Files:**
- Modify: `live_clip_studio/web/workspace.html`
- Modify: `live_clip_studio/web/app.js`
- Test: `tests/test_web_contract.py`

- [ ] **Step 1: 写页面契约失败测试**

```python
assert 'id="rebuild-speaker-candidates"' in workspace
assert '/speaker-candidates/rebuild' in script
assert '字幕文字和时间轴不会改变' in script
assert 'await loadCandidateReview()' in script
```

- [ ] **Step 2: 验证 RED**

Run: `uv run pytest tests/test_web_contract.py::test_workspace_can_rebuild_candidates_without_regenerating_transcript -q`

Expected: FAIL，按钮和请求不存在。

- [ ] **Step 3: 实现前端**

增加 `#rebuild-speaker-candidates`。实现 `rebuildSpeakerCandidates()`：确认后禁用按钮，更新候选状态，POST 新接口，清除前端 classification 就绪状态，调用 `loadCandidateReview()` 和 `loadTranscript()`，错误通过 `showCandidateError()` 显示，最后恢复按钮。

- [ ] **Step 4: 验证 GREEN**

Run: `uv run pytest tests/test_web_contract.py::test_workspace_can_rebuild_candidates_without_regenerating_transcript -q`

Expected: PASS。

### Task 4: 全量验证与真实工作台 QA

**Files:**
- Modify: `docs/qa/2026-08-01-speaker-candidate-rebuild.md`
- Evidence: `docs/qa/screenshots/speaker-candidate-rebuild-desktop.jpg`
- Evidence: `docs/qa/screenshots/speaker-candidate-rebuild-mobile.jpg`

- [ ] **Step 1: 运行全套测试**

Run: `uv run pytest -q`

Expected: 0 failures。

- [ ] **Step 2: 重启 8788 服务**

温和结束当前监听 PID，使用 `open start.command` 启动，验证目标工作台 HTTP 200。

- [ ] **Step 3: 用 9400 Chrome 验收**

桌面 `1440x1000` 与移动 `390x844` 下检查新按钮、确认文案和无溢出。在目标任务上执行一次候选重建，确认网络只请求 rebuild API，页面不进入 Whisper 转写状态，候选数更新。

- [ ] **Step 4: 核对文件不变式**

在真实重建前后记录 `segments.json` 和 `speaker-turns.json` SHA-256，两者必须一致；新 `speaker-candidates.json` 必须显示 `similarity_threshold: 0.35`。

- [ ] **Step 5: 更新 QA 文件**

将每行更新为 `PASS` / `FAIL` / `BLOCKED`，记录 pytest 输出、API 响应、SHA-256 和截图路径。
