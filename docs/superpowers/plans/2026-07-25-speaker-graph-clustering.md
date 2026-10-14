# 声纹图聚类第二轮实验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在无人数先验和无标签推理条件下，比较NME谱聚类、声学轮次谱聚类、多尺度微型簇谱聚类能否同时保留两位少数说话人。

**Architecture:** 在 `speaker-lab-v2` 新增独立图聚类模块，使用稀疏余弦图的 normalized maximum eigengap 自动选择人数；三个策略共享同一核心算法，只改变进入图的节点。全部预测先落盘，再调用现有独立评分模块一次性评分。

**Tech Stack:** Python 3.12、NumPy、SciPy sparse、scikit-learn GaussianMixture/KMeans、pytest

**QA Result File:** `docs/qa/2026-07-25-speaker-graph-clustering.md`

---

## QA 矩阵

| 需求项 | 实现入口 | 验证方式 | 通过标准 | 证据位置 | 状态 |
| --- | --- | --- | --- | --- | --- |
| NME自动人数 | `graph_cluster.py` | 四方向合成向量 | 不传人数并输出4 | QA文件 | PENDING |
| 稀疏图参数选择不读标签 | `graph_cluster.py` | API签名与源码扫描 | 无标签、人数、评分参数 | QA文件 | PENDING |
| 声学轮次聚合 | `turns.py` | 连续同声纹/切换合成序列 | 同声纹连续段合并，切换处断开 | QA文件 | PENDING |
| 多尺度微型簇等权 | `strategies.py` | 不平衡合成向量 | 图节点为微型簇中心，不按成员数复制 | QA文件 | PENDING |
| 三策略真实推理 | `experiment_v2.py` | 三个embedding缓存 | 9组预测全部写出且包含自动人数证据 | `outputs/frozen-dev-v2/` | PENDING |
| 一次性评分 | 现有 `scoring.py` | 所有预测落盘后评分 | 产生每策略完整指标 | `outputs/frozen-dev-v2/metrics.json` | PENDING |
| 生产数据不变 | SHA-256 | 推理前后比较 | 两个生产文件摘要一致 | QA文件 | PENDING |

## Task 1：NME谱聚类核心

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/graph_cluster.py`
- Create: `speaker-lab-v2/tests/test_graph_cluster.py`

- [ ] 先写四个正交声纹簇的失败测试，调用 `nme_spectral_cluster(embeddings)`，断言 `speaker_count == 4`、标签数等于样本数且相同随机种子输出一致。
- [ ] 运行 `../.venv/bin/pytest tests/test_graph_cluster.py -q`，确认因模块缺失而RED。
- [ ] 实现固定邻居集合 `5/10/20/40/80`、非负余弦图、对称top-k稀疏化、normalized Laplacian、`2～8`人数eigengap、确定性KMeans。
- [ ] 重跑测试并确认GREEN。

## Task 2：声学轮次

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/turns.py`
- Create: `speaker-lab-v2/tests/test_turns.py`

- [ ] 先写两个说话人按 `AAA/BBB/AAA` 连续块排列的失败测试，断言输出3个轮次并保留所有成员索引。
- [ ] 运行 `../.venv/bin/pytest tests/test_turns.py -q`，确认RED。
- [ ] 用相邻余弦相似度两成分 `GaussianMixture(random_state=0)`，以高均值成分后验≥0.8且时间间隔≤0.75秒作为合并条件；每个轮次中心等权平均并归一化。
- [ ] 重跑测试并确认GREEN。

## Task 3：三个无标签策略

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/strategies.py`
- Create: `speaker-lab-v2/tests/test_strategies.py`

- [ ] 先写失败测试，验证 `raw_nme`、`turn_nme`、`multiscale_micro_nme` 都不接受人数或标签参数，返回 `speaker_count/labels/evidence`。
- [ ] 运行 `../.venv/bin/pytest tests/test_strategies.py -q`，确认RED。
- [ ] `raw_nme`直接聚类字幕向量；`turn_nme`先聚合轮次再传播；`multiscale_micro_nme`收集300/600/1200秒微型簇中心、等权谱聚类，再把字幕向量分配给全局中心。
- [ ] 重跑测试并确认GREEN。

## Task 4：真实批量实验与一次性评分

**Files:**
- Create: `speaker-lab-v2/src/speaker_lab_v2/experiment_v2.py`
- Create: `speaker-lab-v2/tests/test_experiment_v2.py`
- Create: `docs/qa/2026-07-25-speaker-graph-clustering.md`

- [ ] 先写失败测试，验证批量结果扁平化为 `模型:策略` 九组预测，并且API不接受标签路径。
- [ ] 运行 `../.venv/bin/pytest tests/test_experiment_v2.py -q`，确认RED。
- [ ] 实现CLI，读取三种缓存，固定运行三策略，记录每组自动人数、eigengap、邻居数、轮次数/微型簇数和耗时。
- [ ] 运行全部测试，要求无失败。
- [ ] 记录生产文件SHA-256，运行一次 `outputs/frozen-dev-v2` 无标签推理。
- [ ] 确认九组预测均已落盘后，调用 `scoring.py` 一次性生成 `metrics.json`。
- [ ] 不修改参数、不重跑评分；将PASS/FAIL、人数、四人召回、总体指标和运行压力写入QA文件。

## 最终验证

```bash
cd live-clip-studio/speaker-lab-v2
../.venv/bin/pytest -q
test -f outputs/frozen-dev-v2/inferred-speakers.json
test -f outputs/frozen-dev-v2/metrics.json
shasum -a 256 ../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/speaker-turns.json ../data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2/transcript/manual-speaker-labels.json
```
