# 候选说话人确认与全量回填 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本地网页自动提出可试听的匿名说话人候选，接受用户映射/合并/重命名，并用注册语音回填全部字幕与计算人工标注正确率。

**Architecture:** 新建纯 Python `speaker_workflow.py` 管理候选发现、代表样本、注册分类和评分；`JobProcessor` 持久化 embedding 与候选结果；FastAPI 只负责校验和原子写文件；现有字幕页增加候选确认及评估面板。人工标准答案和算法预测始终使用不同文件。

**Tech Stack:** Python 3.12、FastAPI、NumPy、SciPy AHC、原生 HTML/CSS/JavaScript、pytest、Agent Browser

**QA Result File:** `docs/qa/2026-07-25-speaker-candidate-workflow.md`

---

## 假设

- 当前本机继续使用 ECAPA 生产 embedding；冻结阈值为余弦相似度 `0.25`。
- 每个候选默认选择最多 3 条代表片段；多个候选允许映射到同一真实说话人。
- 当前目录无 Git 元数据，按用户此前确认直接修改项目，无法执行 worktree 和逐步 commit。

## 文件结构

- Create `live_clip_studio/speaker_workflow.py`：纯候选、分类、评估逻辑。
- Modify `live_clip_studio/diarization.py`：向处理器返回本轮 embedding 与 segment index。
- Modify `live_clip_studio/jobs.py`：保存候选和 embedding，生成初始匿名字幕。
- Modify `live_clip_studio/app.py`：候选映射、重命名、分类和评估 API。
- Modify `live_clip_studio/web/workspace.html`、`app.js`、`app.css`：候选试听、映射和指标 UI。
- Create `tests/test_speaker_workflow.py`：纯算法契约。
- Modify `tests/test_jobs_api.py`、`tests/test_web_contract.py`：API 与页面契约。

## QA 矩阵

| 需求项 | 实现入口 | 验证方式 | 通过标准 | 证据位置 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 无人数先验提出候选 | `discover_candidates` | 合成 4 簇单测 | 不提供人数仍输出 4 个候选及代表片段 | QA 文件 | PENDING |
| 候选试听与合并 | 候选 API/网页 | API 测试 + Agent Browser | 两个候选可映射到同一 speaker，试听跳到正确时间 | QA 文件/截图 | PENDING |
| 默认命名与重命名 | speaker API | API 测试 + Agent Browser | 空名称生成“说话人 N”，自定义名刷新后保留 | QA 文件/截图 | PENDING |
| 注册后全量更新 | 分类 API/字幕接口 | 真实状态测试 | 预测独立落盘，字幕响应覆盖为预测人物 | QA 文件 | PENDING |
| 部分标签正确率 | metrics API | 公式单测/API 测试 | 分母只含已标记有效字幕 | QA 文件 | PENDING |
| 独立验证排除注册样本 | `score_predictions` | 单元测试 | held-out IDs 不含 enrollment IDs | QA 文件 | PENDING |
| 现有功能无回归 | 全量应用 | pytest/compileall | 全部测试通过、无编译错误 | QA 文件 | PENDING |
| 桌面与移动可用 | 工作台真实页面 | Agent Browser | 核心流程可操作、无 console error | `docs/qa/screenshots/` | PENDING |
| 混合候选可排除 | 候选 API/注册分类/网页 | 单元测试 + API + Agent Browser | 排除计入处理进度，不进入 enrollment，字幕仍被重新分类 | QA 文件/截图 | PENDING |

### Task 1: 纯说话人工作流

- [ ] 在 `tests/test_speaker_workflow.py` 写合成 embedding 的候选发现、代表片段、注册分类和部分标签评分测试。
- [ ] 运行 `uv run pytest tests/test_speaker_workflow.py -q`，确认因模块缺失而失败。
- [ ] 创建 `live_clip_studio/speaker_workflow.py`，实现固定阈值 AHC、候选样本选择、候选映射分类和评分。
- [ ] 重新运行同一测试，预期全部通过。

### Task 2: 转写处理器持久化候选

- [ ] 在 `tests/test_processor.py` 增加 embedding、候选文件和匿名标签持久化失败测试。
- [ ] 运行目标测试并确认失败原因是尚未保存新产物。
- [ ] 修改 `diarization.py` 和 `jobs.py`，原子保存 `speaker-embeddings.npz` 与 `speaker-candidates.json`。
- [ ] 运行 `uv run pytest tests/test_processor.py tests/test_diarization.py -q`，预期通过。

### Task 3: 候选映射、分类与评估 API

- [ ] 在 `tests/test_jobs_api.py` 增加读取候选、映射/合并、重命名、未确认拦截、全量分类和部分标签指标测试。
- [ ] 运行这些目标测试并确认 404/缺失字段的预期失败。
- [ ] 修改 `app.py`，增加候选、assignment、classification、metrics API，并让 transcript API 叠加算法预测。
- [ ] 重新运行 API 测试，预期全部通过且人工标签文件内容不变。

### Task 4: 候选确认与指标界面

- [ ] 在 `tests/test_web_contract.py` 增加候选面板、试听、映射、全量应用和双准确率显示契约。
- [ ] 运行目标测试并确认 HTML/JS 标记缺失。
- [ ] 修改 `workspace.html`、`app.js`、`app.css`，实现候选卡、时间段试听、映射/重命名、全量分类及指标表。
- [ ] 重新运行 web contract 测试，预期通过。

### Task 5: 真实数据迁移与 QA

- [ ] 为现有任务从已冻结的 CAM++ 候选预测与 embedding 生成生产候选文件，但不修改人工标准答案。
- [ ] 运行 `uv run pytest -q` 和 `uv run python -m compileall -q live_clip_studio`。
- [ ] 启动 8788 服务，用 Agent Browser 在桌面和移动视口验证试听、合并、命名、分类、刷新恢复和正确率。
- [ ] 将每行 QA 状态及命令、URL、截图、console 摘要写入 `docs/qa/2026-07-25-speaker-candidate-workflow.md`。
