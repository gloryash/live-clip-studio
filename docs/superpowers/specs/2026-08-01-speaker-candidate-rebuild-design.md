# 重新生成候选设计

## 目标

在工作台增加“重新生成候选”操作。该操作只使用现有字幕分段和说话人声纹向量重新聚类，不调用 Whisper，不修改字幕文字或时间轴。

## 交互

- 在字幕工具栏保留“重新生成字幕”，新增“重新生成候选”。
- 点击新按钮后显示确认提示：字幕不会改变，但旧的候选确认和 AI 说话人分类结果会清除。
- 请求期间禁用按钮，显示“正在重新聚类候选”。
- 成功后重新加载候选列表和说话人状态，候选需要重新确认。
- 失败时在候选区显示后端错误，不影响现有字幕。

## 后端

新增 `POST /api/jobs/{job_id}/speaker-candidates/rebuild`。

1. 验证任务和 `transcript/segments.json`、`transcript/speaker-embeddings.npz` 存在。
2. 从现有文件读取字幕段、声纹向量和索引。
3. 调用 `discover_candidates`，使用当前默认相似度阈值 `0.35`。
4. 原子覆盖 `speaker-candidates.json`。
5. 删除 `speaker-candidate-assignments.json` 和 `speaker-predictions.json`，防止旧候选 ID 污染新结果。
6. 保留 `segments.json`、`speaker-turns.json`、`manual-speakers.json`、`manual-speaker-labels.json` 和 `deleted-turns.json`。
7. 返回新的候选数量、模型和相似度阈值。

## 错误处理

- 任务不存在：`404 JOB_NOT_FOUND`。
- 字幕段或声纹缓存不完整：`409 EMBEDDINGS_NOT_READY`，提示使用“重新生成字幕”。
- 缓存结构或索引无效：`409 EMBEDDINGS_INVALID`，不覆盖原候选文件。

## 测试

- API 测试证明新候选使用 `0.35` 重建。
- 断言处理器没有提交 Whisper 任务。
- 断言字幕段和说话人时间轴文件的字节内容不变。
- 断言旧候选映射和说话人预测被清除，人工姓名和逐条标注保留。
- 覆盖缺少声纹缓存的错误路径。
- 页面契约测试覆盖新按钮、新接口和刷新候选行为。
- 使用 9400 Chrome 在桌面和 390px 移动视口验收按钮、确认框、成功状态与无溢出布局。
