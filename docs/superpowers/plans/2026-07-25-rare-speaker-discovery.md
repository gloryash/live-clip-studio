# 少数说话人发现实验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在独立 `speaker-lab-v2` 目录中验证“局部过聚类、动态新说话人注册、跨尺度稳定性”能否在无人数先验时保留少数说话人并自动估计人数。

**Architecture:** 推理包只读取字幕时间段与预先缓存的匿名声纹向量，先在 5、10、20 分钟窗口内生成微型簇，再通过一对一匹配注册或新建全局原型，最后合并跨尺度稳定原型并输出逐字幕匿名标签。评分包与推理包隔离，只有评分命令能够读取人工标签。

**Tech Stack:** Python 3.12、NumPy、SciPy、scikit-learn、pytest、现有 ECAPA/CAM++/ERes2NetV2 `.npz` embedding 缓存

**QA Result File:** `docs/qa/2026-07-25-rare-speaker-discovery.md`

---

## 假设与约束

- 当前视频仍是冻结测试集，不能用于训练或阈值选择。
- 第一轮参数在评分前固定：窗口 `300/600/1200` 秒、局部微型簇 `6～10`、候选至少跨两个窗口重复、低置信度允许 `UNKNOWN`。
- 新实验不修改 `live_clip_studio/`、网页、`speaker-turns.json` 或人工标注。
- `live-clip-studio` 不是 Git 仓库，因此计划中的 commit 步骤以“记录无法提交”替代，不初始化新仓库。

## 文件结构

- Create: `speaker-lab-v2/pyproject.toml` — 独立包、pytest 与 CLI 配置。
- Create: `speaker-lab-v2/README.md` — 数据隔离、运行命令与输出说明。
- Create: `speaker-lab-v2/src/speaker_lab_v2/data.py` — 只读字幕、embedding 缓存与索引交集。
- Create: `speaker-lab-v2/src/speaker_lab_v2/models.py` — `MicroCluster`、`Prototype`、`InferenceConfig` 数据模型。
- Create: `speaker-lab-v2/src/speaker_lab_v2/microcluster.py` — 窗口切分、过聚类、中心和紧密度。
- Create: `speaker-lab-v2/src/speaker_lab_v2/registry.py` — Hungarian 匹配、候选晋级、等权原型更新。
- Create: `speaker-lab-v2/src/speaker_lab_v2/multiscale.py` — 跨尺度稳定原型与人数估计。
- Create: `speaker-lab-v2/src/speaker_lab_v2/pipeline.py` — 无标签推理与 JSON 输出。
- Create: `speaker-lab-v2/src/speaker_lab_v2/scoring.py` — 人工标签读取与置换不变评分。
- Create: `speaker-lab-v2/tests/` — 纯合成向量单元测试和真实缓存契约测试。
- Create: `speaker-lab-v2/outputs/` — 真实运行产物。
- Create: `docs/qa/2026-07-25-rare-speaker-discovery.md` — QA 证据。

## QA 矩阵

| 需求项 | 实现入口 | 验证方式 | 通过标准 | 证据位置 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 推理不能读取人工标签 | `pipeline.py`、`data.py` | 单元测试 + 源码依赖扫描 | 推理 API 不接受标签路径，源码不导入 `scoring` | QA 文件测试输出 | PENDING |
| 窗口内过聚类 | `microcluster.py` | 合成四人不平衡向量单元测试 | 少数簇不被直接合并进最大簇，生成 6～10 个微型簇 | QA 文件测试输出 | PENDING |
| 动态发现新说话人 | `registry.py` | 两批窗口合成向量状态测试 | 后出现且低相似的簇先成为候选，重复后晋级 | QA 文件测试输出 | PENDING |
| 多数类不控制原型权重 | `registry.py` | 1个大簇与1个小簇等权更新测试 | 原型更新等价于簇中心平均，不按字幕数量平均 | QA 文件测试输出 | PENDING |
| 自动估计人数 | `multiscale.py` | 三尺度合成原型测试 | 四个跨至少两个尺度稳定原型输出人数4 | QA 文件测试输出 | PENDING |
| 真实数据推理 | `pipeline.py` CLI | 使用三个现有 `.npz` 缓存运行 | 不传人数先验，生成 config、prototypes、speaker-count、predictions | `speaker-lab-v2/outputs/<run-id>/` | PENDING |
| 冻结测试集评分 | `scoring.py` CLI | 推理完成后单独运行评分 | 输出 accuracy、Macro-F1、四人 precision/recall/F1、长短字幕、UNKNOWN | `outputs/<run-id>/metrics.json` | PENDING |
| 不覆盖生产文件 | 全实验目录 | 运行前后文件摘要与修改时间检查 | `transcript/speaker-turns.json` 和人工标注摘要不变 | QA 文件摘要记录 | PENDING |

## 实施任务

### Task 1：独立包与数据契约

**Files:**
- Create: `speaker-lab-v2/pyproject.toml`
- Create: `speaker-lab-v2/src/speaker_lab_v2/data.py`
- Test: `speaker-lab-v2/tests/test_data.py`

- [ ] **Step 1：先写失败测试**

测试 `load_embedding_cache` 返回归一化矩阵和零基索引，且 `load_inference_inputs` 不接受人工标签路径。

```python
def test_inference_inputs_expose_no_manual_label_argument():
    assert "manual" not in inspect.signature(load_inference_inputs).parameters
```

- [ ] **Step 2：验证 RED**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_data.py -q`

Expected: FAIL，因为 `speaker_lab_v2.data` 尚不存在。

- [ ] **Step 3：实现最小数据加载器**

定义：

```python
def load_embedding_cache(path: Path) -> EmbeddingCache: ...
def load_inference_inputs(segments_path: Path, embedding_paths: dict[str, Path]) -> InferenceInputs: ...
```

只允许读取 `segments.json` 和 `.npz`，对维度、索引范围、NaN、零向量进行显式校验。

- [ ] **Step 4：验证 GREEN**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_data.py -q`

Expected: PASS。

### Task 2：局部过聚类

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/models.py`
- Create: `speaker-lab-v2/src/speaker_lab_v2/microcluster.py`
- Test: `speaker-lab-v2/tests/test_microcluster.py`

- [ ] **Step 1：先写失败测试**

构造两个各100条的大簇和两个各5条的小簇，验证 `build_microclusters` 不接收真实人数参数，并输出介于6和10之间的微型簇。

```python
clusters = build_microclusters(embeddings, rows, window_seconds=600, seed=0)
assert 6 <= len(clusters) <= 10
assert all(np.isclose(np.linalg.norm(c.centroid), 1.0) for c in clusters)
```

- [ ] **Step 2：验证 RED**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_microcluster.py -q`

Expected: FAIL，因为模块尚不存在。

- [ ] **Step 3：实现过聚类**

使用 `AgglomerativeClustering(metric="cosine", linkage="average")`；簇数使用 `clip(round(sqrt(n / 3)), 6, 10)`，不接收真实说话人数。输出中心、样本索引、累计时长、紧密度和窗口ID。

- [ ] **Step 4：验证 GREEN**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_microcluster.py -q`

Expected: PASS。

### Task 3：动态注册与候选晋级

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/registry.py`
- Test: `speaker-lab-v2/tests/test_registry.py`

- [ ] **Step 1：先写失败测试**

覆盖三个状态转换：首次出现进入候选、同声纹跨窗口重复后晋级、明显不同的后出现声纹创建新候选。另测原型按微型簇等权更新。

```python
registry.observe(window_1_clusters)
assert registry.confirmed_count == 0
registry.observe(window_2_clusters)
assert registry.confirmed_count == 2
registry.observe(window_3_with_new_speaker)
assert registry.candidate_count == 1
```

- [ ] **Step 2：验证 RED**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_registry.py -q`

Expected: FAIL，因为动态注册器尚不存在。

- [ ] **Step 3：实现最小注册器**

使用 `scipy.optimize.linear_sum_assignment` 最大化余弦相似度；确认原型、候选原型均使用微型簇中心等权在线平均；一轮内一个原型最多匹配一个微型簇。阈值从不含标签的相似度分布确定，并受固定安全区间约束。

- [ ] **Step 4：验证 GREEN**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_registry.py -q`

Expected: PASS。

### Task 4：跨尺度稳定性与自动人数

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/multiscale.py`
- Test: `speaker-lab-v2/tests/test_multiscale.py`

- [ ] **Step 1：先写失败测试**

提供三个尺度的匿名原型，其中四个真实方向在至少两个尺度重复，另有一个仅出现一次的噪声原型。

```python
result = estimate_stable_speakers({300: scale_a, 600: scale_b, 1200: scale_c})
assert result.speaker_count == 4
assert len(result.stable_prototypes) == 4
```

- [ ] **Step 2：验证 RED**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_multiscale.py -q`

Expected: FAIL，因为人数估计模块尚不存在。

- [ ] **Step 3：实现跨尺度原型图**

把原型作为节点，仅允许不同尺度之间建立相似度边；使用预声明的相似度规则做连通分量合并；至少跨两个尺度的分量计入稳定人数，并输出尺度支持数与置信度。

- [ ] **Step 4：验证 GREEN**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_multiscale.py -q`

Expected: PASS。

### Task 5：无标签推理、评分隔离与真实实验

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/pipeline.py`
- Create: `speaker-lab-v2/src/speaker_lab_v2/scoring.py`
- Create: `speaker-lab-v2/tests/test_pipeline.py`
- Create: `speaker-lab-v2/tests/test_scoring.py`
- Create: `speaker-lab-v2/README.md`
- Create: `docs/qa/2026-07-25-rare-speaker-discovery.md`

- [ ] **Step 1：先写失败测试**

验证推理结果包含配置、稳定原型、候选、人数与逐句标签；验证评分只做匿名标签最优置换且不会修改预测文件；扫描 `pipeline.py` 和 `data.py` 不得出现人工标签文件名或导入 `scoring`。

- [ ] **Step 2：验证 RED**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest tests/test_pipeline.py tests/test_scoring.py -q`

Expected: FAIL，因为编排与评分模块尚不存在。

- [ ] **Step 3：实现 CLI 与输出**

提供：

```text
speaker-lab-v2 infer --segments ... --embedding ECAPA=... --embedding CAM++=... --embedding ERes2NetV2=... --output ...
speaker-lab-v2 score --prediction ... --manual-labels ... --segments ... --output ...
```

`infer` 不接受人数或人工标签参数；`score` 只在预测文件已存在后运行。

- [ ] **Step 4：运行全部测试**

Run: `cd speaker-lab-v2 && ../.venv/bin/pytest -q`

Expected: 全部 PASS，无 warning 或错误日志。

- [ ] **Step 5：记录生产文件摘要并运行真实推理**

Run:

```bash
shasum -a 256 data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/speaker-turns.json data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/manual-speaker-labels.json
cd speaker-lab-v2
../.venv/bin/python -m speaker_lab_v2.pipeline infer --segments ../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/segments.json --embedding ECAPA=../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/speaker-experiments/ecapa-embeddings.npz --embedding CAM++=../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/speaker-experiments/campplus-embeddings.npz --embedding ERes2NetV2=../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/speaker-experiments/eres2netv2-embeddings.npz --output outputs/frozen-test-v1
```

Expected: 自动生成4类核心JSON，不读取人工标签。

- [ ] **Step 6：一次性冻结评分**

Run:

```bash
../.venv/bin/python -m speaker_lab_v2.scoring --prediction outputs/frozen-test-v1/inferred-speakers.json --manual-labels ../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/manual-speaker-labels.json --segments ../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/segments.json --output outputs/frozen-test-v1/metrics.json
```

Expected: 输出全量和分项指标；无论通过与否都保留结果，不根据分数修改参数后重跑同一测试集。

- [ ] **Step 7：更新 QA 证据并复核摘要**

重新执行 `shasum -a 256`，确认生产文件摘要不变；将测试命令、自动人数、指标、运行时间和文件摘要写入 QA 文件。

## 最终验证

Run:

```bash
cd live-clip-studio/speaker-lab-v2
../.venv/bin/pytest -q
test -f outputs/frozen-test-v1/speaker-count.json
test -f outputs/frozen-test-v1/metrics.json
shasum -a 256 ../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/speaker-turns.json ../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/manual-speaker-labels.json
```

完成证据：

- `speaker-lab-v2/outputs/frozen-test-v1/`
- `docs/qa/2026-07-25-rare-speaker-discovery.md`
- 生产文件运行前后 SHA-256 一致
