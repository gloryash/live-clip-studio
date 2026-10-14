# 候选说话人确认与全量回填 QA

## 环境

- 日期：2026-07-25
- 页面：`http://127.0.0.1:8788/workspace/f03d40e1-0f06-4454-a83f-1a512c7e4ae2`
- 数据原则：人工标签、候选映射和算法预测分别保存
- 桌面视口：1440×1000
- 移动视口：iPhone 15，393×852，DPR 3

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 无人数先验提出候选 | 合成数据单测 | 自动得到 4 簇 | PASS | `test_discovers_four_candidates_without_a_speaker_count_prior` | 未传人数参数 |
| 候选试听与合并 | API + 浏览器 | 可试听且多候选归一人 | PASS | API 测试；桌面试听 3517.674–3521.845 秒 | 片段结束自动暂停 |
| 默认命名与重命名 | API + 浏览器 | 名称持久化 | PASS | `test_candidate_confirmation_merges_speakers_classifies_turns_and_scores_partial_labels` | 空名称自动编号，自定义“嘉宾”持久化 |
| 注册后全量更新 | API + 浏览器 | 字幕展示预测身份 | PASS | 同一 API 测试 | 预测独立写入，transcript 叠加显示 |
| 部分标签正确率 | 单测 + API | 只统计已标记有效字幕 | PASS | `test_metrics_use_only_labeled_active_turns_and_hold_out_enrollment` | 软删除字幕排除 |
| 独立验证排除注册 | 单测 + API | 注册片段不进 held-out | PASS | held-out 3/3 合成 API 测试 | enrollment IDs 明确落盘 |
| 现有功能无回归 | pytest + compileall | 零失败 | PASS | `52 passed`；compileall；`node --check`；`uv lock --check` | 5 个既有依赖弃用警告，不影响运行 |
| 桌面与移动可用 | Agent Browser | 无阻塞交互和 console error | PASS | `speaker-candidates-desktop-final.jpg`、`speaker-candidates-mobile-final.jpg` | 两视口无横向溢出、console/errors 为空 |
| 混合候选可排除 | 单元测试 + API + Agent Browser | 排除计入处理进度，不进入 enrollment，字幕仍重新分类 | PASS | `test_excluded_mixed_candidate_is_not_used_for_enrollment_but_its_turns_are_classified`、`test_mixed_candidate_can_be_excluded_without_blocking_classification`、`speaker-candidate-exclude.jpg` | 不创建人物，不删除字幕 |

## 返工记录

| 轮次 | 失败项 | 修复动作 | 结果 |
| --- | --- | --- | --- |
| 1 | 旧任务顶部显示 2 人、候选面板显示 5 人 | transcript API 按候选/确认状态派生人数并增加状态字段 | PASS：真实页面显示“5 个候选人物” |
| 2 | `uv lock --check` 报锁文件元数据过期 | 运行 `uv lock` 后从头执行完整验证 | PASS |

## 真实视频证据

- CAM++ 无人数先验候选数：5。
- 候选 S003：28 条，代表片段 ID 1639、1632、1641。
- 候选 S004：24 条，代表片段 ID 1746、1747、1745。
- 当前候选确认进度：4/5；S000→王佳梁、S001→吴总、S003→学生1、S004→学生2，S002 尚未处理；“应用到全部字幕”保持禁用。
- 当前字幕：2313 条原始记录，已有 1 条软删除；人工标签文件 SHA-256 为 `a1cf9200271d7d80659fa89ce5feeffc0925ed8534532fd91cc9908cd54b0010`，迁移前后相同。
- 当前 `speaker-candidate-assignments.json` 中的 4 项映射来自用户操作；本次浏览器 QA 只临时选择了 S002 的排除选项，没有点击确认，也未改写该文件。
