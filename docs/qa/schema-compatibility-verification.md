# 切片 Schema 接口兼容性修复（2026-10-14）

原因：`DECISION_SCHEMA` 用于本地 JSON Schema 校验，包含 `uniqueItems`；RelayRouter Responses 严格输出接口拒绝该关键字。本地完整 Schema 曾直接发送给接口。

修复：`ModelClient.request` 发送递归转换后的 Schema，仅移除 `uniqueItems`；不修改原始 Schema。本地校验继续拒绝重复编号，长度、时长、锚点和其他约束保持执行。

官方资料核对：https://platform.openai.com/docs/guides/structured-outputs （Structured Outputs 只支持 JSON Schema 子集；数组支持 minItems/maxItems）。实际接口错误是本次兼容问题的直接证据。

验证：

- 回归测试先复现请求中出现 uniqueItems；修复后通过，同时证明原始 Schema 未被修改。
- 全部测试：120 passed。
- 从失败任务 `02ef190a-a2e4-4f75-9e09-6c23052add1f` 的缓存选题继续执行，真实 GPT-6.1-Sol detail 请求成功，生成 3 条视频、封面、字幕和评分。
- 旧错误请求证据保留；新 detail-02-1/detail-03-1 请求不含 uniqueItems。
- 3 条技术检查均 PASS；第 1、2 条语音检查分别 0.9471/0.9462，均有 1 项剪切附近的可疑差异，标记 REVIEW；第 3 条语音检查 0.9601，PASS。
- 最终状态 needs_review；Schema 错误已消除，未将语音复核项误标为通过。
- 更新日常服务端口 8788，接口能够读取 3 条结果，视频均支持 Range 206；网页显示最新任务和结果。
