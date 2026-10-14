# 字幕快捷软删除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 快捷标注模式下按 `D` 持久化软删除当前误识别字幕、自动跳到下一条，并从标注进度和训练集导出中排除该字幕。

**Architecture:** 后端继续把 `speaker-turns.json` 作为不可变转写证据，新增 `deleted-turns.json` 保存删除 ID；标注 API 聚合人工标签与删除状态，训练集导出只处理有效字幕。前端用 `Set` 维护删除 ID，在 `visibleTurns()` 中统一过滤，键盘处理复用现有自动前进逻辑。

**Tech Stack:** FastAPI、原子 JSON 文件写入、原生 JavaScript、pytest、Agent Browser

**QA Result File:** `docs/qa/2026-07-24-subtitle-soft-delete.md`

---

## 文件结构

- 修改 `live_clip_studio/app.py`：删除状态读写、删除 API、进度及导出过滤。
- 修改 `live_clip_studio/web/app.js`：删除状态、`D` 快捷键、自动前进及列表过滤。
- 修改 `live_clip_studio/web/workspace.html`：快捷键提示加入 `D`。
- 修改 `tests/test_jobs_api.py`：持久化、幂等、导出过滤的后端回归测试。
- 修改 `tests/test_web_contract.py`：`D` 快捷键与删除 API 的前端契约测试。
- 创建 `docs/qa/2026-07-24-subtitle-soft-delete.md`：记录真实验证证据。

## QA 矩阵

| 需求项 | 实现入口 | 验证方式 | 通过标准 | 证据位置 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `D` 删除当前字幕并前进 | `handleAutoAnnotationKeydown` | Agent Browser 桌面流程 | 卡片消失、下一条激活、视频时间同步 | `docs/qa/2026-07-24-subtitle-soft-delete.md` | PENDING |
| 删除跨刷新保留 | 删除 API + `deleted-turns.json` | API 测试和浏览器刷新 | 删除 ID 持久化且刷新后不显示 | `docs/qa/2026-07-24-subtitle-soft-delete.md` | PENDING |
| 删除字幕不计入训练集 | `export_training_labels` | pytest API 测试 | 完整性校验与 JSONL 都忽略删除项 | `docs/qa/2026-07-24-subtitle-soft-delete.md` | PENDING |
| 不误触输入与其他模式 | `handleAutoAnnotationKeydown` | 前端契约及 Agent Browser | 仅快捷模式字幕面板响应 `D` | `docs/qa/2026-07-24-subtitle-soft-delete.md` | PENDING |
| 历史人工标签安全 | 独立删除文件 | 真实 API 文件检查 | 现有 `manual-speaker-labels.json` 内容不变 | `docs/qa/2026-07-24-subtitle-soft-delete.md` | PENDING |

### Task 1: 后端软删除状态与导出语义

**Files:**
- Modify: `live_clip_studio/app.py`
- Test: `tests/test_jobs_api.py`

- [ ] **Step 1: 写失败测试**

新增测试构造两条字幕、先标注第一条，然后调用：

```python
deleted = client.delete(f"/api/jobs/{job_id}/transcript/turns/1")
assert deleted.json()["deleted_turn_ids"] == [1]
assert client.get(f"/api/jobs/{job_id}/annotations").json()["active_total_count"] == 1
```

继续标注第二条并导出，断言 JSONL 仅包含第二条，且 `manual-speaker-labels.json` 中第一条标签仍存在；再次删除第一条返回成功，证明幂等。

- [ ] **Step 2: 运行失败测试**

Run: `uv run pytest tests/test_jobs_api.py -q`

Expected: FAIL，删除路由返回 `404` 或响应缺少 `deleted_turn_ids`。

- [ ] **Step 3: 最小实现**

在 `app.py` 增加：

```python
def read_deleted_turn_ids(transcript_dir: Path) -> set[int]:
    path = transcript_dir / "deleted-turns.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = document.get("deleted_turn_ids", []) if isinstance(document, dict) else []
    return {int(value) for value in values if str(value).isdigit()}

def write_deleted_turn_ids(transcript_dir: Path, turn_ids: set[int]) -> None:
    path = transcript_dir / "deleted-turns.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "deleted_turn_ids": sorted(turn_ids)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)

@application.delete("/api/jobs/{job_id}/transcript/turns/{turn_id}")
def delete_transcript_turn(job_id: str, turn_id: int) -> dict[str, Any]:
    _, turns, transcript_dir = annotation_context(job_id)
    if turn_id not in {int(turn.get("id", -1)) for turn in turns}:
        raise HTTPException(status_code=404, detail=error_payload("TURN_NOT_FOUND", "找不到这条字幕"))
    deleted = read_deleted_turn_ids(transcript_dir)
    deleted.add(turn_id)
    write_deleted_turn_ids(transcript_dir, deleted)
    return {"turn_id": turn_id, "deleted_turn_ids": sorted(deleted), "deleted_count": len(deleted)}
```

文件格式固定为 `{"version": 1, "deleted_turn_ids": [1, 2]}`，使用临时文件替换保证原子写入。`get_annotations` 返回 `deleted_turn_ids`、`deleted_count`、`active_total_count`、有效 `annotated_count`；训练集完整性校验和循环均先过滤删除 ID。

- [ ] **Step 4: 运行后端测试**

Run: `uv run pytest tests/test_jobs_api.py -q`

Expected: PASS。

### Task 2: 前端 `D` 快捷键与自动前进

**Files:**
- Modify: `live_clip_studio/web/app.js`
- Modify: `live_clip_studio/web/workspace.html`
- Test: `tests/test_web_contract.py`

- [ ] **Step 1: 写失败契约测试**

断言页面提示含 `D 删除字幕`，脚本包含 `event.key.toLowerCase() === "d"`、删除路由和 `deleteAndAdvance`，并继续保留输入控件焦点保护。

- [ ] **Step 2: 运行失败测试**

Run: `uv run pytest tests/test_web_contract.py -q`

Expected: FAIL，页面与脚本尚无删除交互。

- [ ] **Step 3: 最小实现**

增加 `deletedTurnIds = new Set()`；`visibleTurns()` 先排除删除 ID；`loadAnnotations()` 载入删除状态；`renderAnnotationSummary()` 只计算有效字幕。新增：

```javascript
async function deleteAndAdvance(turnId) {
  const list = visibleTurns();
  const index = list.findIndex((turn) => String(turn.id) === String(turnId));
  const next = index >= 0 ? list[index + 1] : null;
  await requestJson(`/api/jobs/${jobId}/transcript/turns/${turnId}`, { method: "DELETE" });
  deletedTurnIds.add(String(turnId));
  renderSpeakerFilters();
  renderTurns();
  if (next) setActiveTurn(next.id);
  else video.pause();
}
```

键盘处理把 `D` 与左右键一起 `preventDefault()`，忽略长按，并在删除失败时保留当前卡片、显示错误。

- [ ] **Step 4: 运行前端契约与语法检查**

Run: `uv run pytest tests/test_web_contract.py -q && node --check live_clip_studio/web/app.js`

Expected: PASS，Node 退出码为 0。

### Task 3: 集成验证与证据

**Files:**
- Create: `docs/qa/2026-07-24-subtitle-soft-delete.md`

- [ ] **Step 1: 全量自动测试**

Run: `uv run pytest -q && uv run python -m compileall -q live_clip_studio`

Expected: 所有测试通过，编译退出码为 0。

- [ ] **Step 2: 隔离 QA 任务验证**

创建只含两条字幕的临时任务，在 `http://127.0.0.1:8788/workspace/<qa-job-id>` 开启快捷标注，按 `D`。Agent Browser 验证第一条消失、第二条高亮、视频时间跳到第二条起点；刷新后第一条仍不出现。

- [ ] **Step 3: 检查真实历史标注未改变**

在修改前后读取任务 `f03d40e1-0f06-4454-a83f-1a512c7e4ae2` 的 annotations API 和 `manual-speaker-labels.json` 哈希，要求内容一致。

- [ ] **Step 4: 写 QA 结果**

把矩阵更新为 `PASS`/`FAIL`/`BLOCKED`，记录测试命令、浏览器 URL、桌面视口、API 响应和标注哈希。项目不是 Git 仓库，因此不执行提交步骤。
