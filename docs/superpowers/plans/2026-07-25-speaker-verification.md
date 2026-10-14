# 同人验证与注册语音实验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证官方固定same-speaker阈值能否无监督迁移，以及每人1/3/5条注册语音能达到的持出集准确率。

**Architecture:** 在`verification.py`实现固定阈值AHC和注册中心分类；`experiment_v3.py`先生成无标签AHC预测，再独立运行显式有监督注册协议。两种结果分文件保存。

**Tech Stack:** Python 3.12、NumPy、SciPy hierarchy、pytest

**QA Result File:** `docs/qa/2026-07-25-speaker-verification.md`

---

## QA矩阵

| 需求项 | 验证方式 | 通过标准 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| 固定阈值AHC不读标签 | API签名和合成簇 | 自动输出簇数，无人数/标签参数 | QA文件 | PENDING |
| 注册样本严格持出 | 合成标签测试 | 注册ID不进入评估ID | QA文件 | PENDING |
| 固定时间顺序选样 | 打乱输入索引测试 | 始终选择时间最早满足时长的N条 | QA文件 | PENDING |
| 三模型三档注册 | 真实批量实验 | 输出9组持出结果和注册ID | `enrollment-metrics.json` | PENDING |
| 生产数据不变 | SHA-256 | 前后摘要一致 | QA文件 | PENDING |

## TDD任务

1. 创建`tests/test_verification.py`，先让固定阈值AHC的两簇合成测试失败，再实现`fixed_threshold_ahc`。
2. 增加注册样本选择和持出分类失败测试，验证时间顺序、最低2秒和注册样本排除，再实现`evaluate_enrollment`。
3. 创建`tests/test_experiment_v3.py`，验证三模型被展开为AHC预测和1/3/5注册结果，再实现CLI。
4. 运行全量测试；记录生产摘要；先生成AHC预测并评分，再运行注册协议；不根据成绩修改参数。
5. 写入QA并执行完成审计。
