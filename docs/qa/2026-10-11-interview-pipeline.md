# QA 结果：配置驱动访谈切片流水线

## 环境

- 日期：2026-10-11
- 项目：`live-clip-studio`
- 模型入口：CC Switch 当前 Codex provider → `https://api.relayrouter.ai/v1/responses`
- 模型：`gpt-6.1-sol`
- 转写：本机 `http://127.0.0.1:8765`，`mlx-community/whisper-large-v3-turbo`
- 媒体：本机 FFmpeg
- 独立验证输入：`data/6253be2a-009e-40a3-9866-aa71afdd937d`（《GEO：机会在哪儿？》）
- 输出：`exports/geo-pipeline-validation/`

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 |
| --- | --- | --- | --- | --- |
| 已标注输入可直接进入流水线 | `export_job`、输入契约测试、真实 GEO preflight | 人工说话人优先、删除生效、ID/时间合法 | PASS | `exports/geo-pipeline-validation/input-report.json` |
| relayrouter 指定模型可用 | 真实 Responses JSON Schema 探针 + 真实选题请求 | 返回 `model=gpt-6.1-sol`，结构化 JSON | PASS | `exports/geo-pipeline-validation/ai/*-response.json` |
| AI 只输出固定配置 | Schema/业务校验正反例 + GEO detail 输出 | 不接受不存在 ID、重复正文、越界卡片、危险改写 | PASS | `validation.json`、`tests/test_clip_contract.py` |
| 全场文本分窗选题 | GEO 2,137 句段、8 个窗口真实调用 | 候选含源句段 ID，最终选 2 条互不重叠主题 | PASS | `ai/topics.json` |
| 另一直播完整生成切片 | GEO 真实渲染 | 2 条 MP4/SRT/封面/发布稿生成 | PASS | `01-ai-citation.*`、`02-seo-still-matters.*` |
| 两种布局由配置驱动 | 单测 + 真实 FFmpeg 短样本 split/PiP | 不依赖 fb16 固定坐标，1080×1920 成片 | PASS | `tests/test_clip_render.py`、`exports/geo-pipeline-validation/` |
| 技术质量 | ffprobe、完整 decode、响度、抽帧 | H.264/AAC、1080×1920、30fps、画音差≤0.1s、约 -15 LUFS | PASS | `qa/summary.json`、`qa/*-decode.log`、`qa/*-loudness.json` |
| Whisper 回听不吃字 | 成片反向转写和剪切点比对 | 语音相似度高；剪切点异常明确标记 | REVIEW | `qa/summary.json`；01=0.9643 PASS，02=0.9694 REVIEW |
| 失败可定位并重跑 | `RunState` 故障测试、`run.json`、`events.jsonl` | 阶段、错误、run_id、输入哈希可回读，不泄漏密钥 | PASS | `tests/test_clip_pipeline.py` |
| 现有项目回归 | `uv run pytest -q`、`compileall` | 111 tests passed | PASS | 命令输出 |

## 独立验证结果

GEO 验证实际经历了：`preflight → select（8 次分窗发现 + 2 次细化）→ plan → render → qa`。总选择阶段约 466 秒，渲染约 65 秒，QA 约 17 秒。生成的两条切片分别为 147.43 秒和 102.80 秒；两条均完整解码、画音时长差 0.023 秒和 0.072 秒，响度 -14.69/-14.84 LUFS。抽帧接触表显示标题、字幕、要点卡、人物条和 CTA 均进入画面。

第二条的 Whisper 比对相似度 0.9694，但在一个剪切点附近发现单字插入和长停顿/口语差异，状态被保留为 `REVIEW`，没有伪装为自动通过。需要人用手机完整播放两条成片，确认这类差异是否听感自然；这也是该系统的最终人工门禁。

## 返工记录

| 轮次 | 失败项 | 修复动作 | 结果 |
| --- | --- | --- | --- |
| 1 | 初版模型异常不会重试 | 将 API/空输出/截断/JSON 错误纳入一次有界重试，并写安全 error evidence | PASS |
| 1 | 源视频缓存仅看大小和 mtime | 增加源文件 SHA-256 | PASS |
| 1 | 跨运行事件难以区分 | `run_id` 和 `input_hash` 写入状态与事件 | PASS |
| 1 | 输入字幕可能乱序/重叠 | preflight 拒绝乱序和重叠时间段 | PASS |
| 1 | QA 未严格验证帧率 | 增加 30fps 和 yuv420p 检查 | PASS |
| 1 | Responses 回包字段兼容性 | 同时支持 `output[].content[].text` 与顶层 `output_text`，空输出拒绝 | PASS |

## 目前仍需人工完成

- 手机完整观看 `exports/geo-pipeline-validation/01-ai-citation.mp4` 和 `02-seo-still-matters.mp4`，确认原意、跳剪、字幕和人物条。
- 确认 GEO 直播嘉宾身份和布局参数后再发布；不要把自动生成的标题、话题或嘉宾名条直接视为事实。
- `REVIEW` 状态的音频差异应先听，再决定修剪句段或接受。

## Claude 规则与新流水线的同源对比

我读取了 Claude 的 `editing/fb16_clips.json`、`render-report.json`、9 条成片抽帧表，并把其中前两条的句段配置交给新流水线做了同源重渲染，结果在 `exports/fb16-pipeline-comparison/`。

| 项目 | Claude 原成片 | 新流水线同源重渲染 | 结论 |
| --- | ---: | ---: | --- |
| 平均时长（9 条） | 91.99s | 由配置决定 | 不是固定时长，规则允许 60–180s |
| 平均镜头数 | 21.9 | 同源样本 28/27 | 新渲染器保持类似密度 |
| 最大单镜头 | 6.97s | 7.33/7.40s | 与“约 7.5 秒内换镜”一致 |
| 主持人/嘉宾近远景 | `gw/gc` 周期，必要时 `hw/hc` | 同样由固定循环生成 | 这是程序规则，不是逐句情绪判断 |
| 双人镜头 | 17/21/… 条中按转场和短插话出现 | dialogue/monologue 模式控制 | 不能强制所有片段都双人 |
| 白闪 | 章节/换段触发 | 章节触发 | 视觉语法一致 |
| 字幕/金句/卡片/CTA | 全部存在 | 全部由配置驱动 | 包装结构一致 |

抽帧显示两者共同的稳定规则：开头先给大字和人物脸；主持人出现时使用主持人画面；嘉宾长段在 `gw/gc` 间交替；章节位置用白闪；金句保持脸在画面中并用黄色字幕；末尾保留互动卡。新旧差异主要来自包装文案、品牌条、嘉宾名条和布局配置，而非“某句话情绪到了就推近”。

## 规则复核结论

Claude 的实际方法应分成两层：

1. **内容判断层**：选题、冷开场、标题、悬念卡、是否问答型、哪些句子是金句。这些需要读稿和语义判断，AI 或人来做。
2. **固定执行层**：近景/中景循环、双人过渡、每镜时长上限、白闪、字幕位置、金句颜色、卡片和 CTA。这些可以由程序稳定执行。

新增 `mode` 后，系统把访谈分成 `dialogue` 和 `monologue`：问答型要求正文同时包含双方；嘉宾连续观点型允许独白，不再硬拼主持人。此前 GEO 第一轮验证暴露的“嘉宾独白被误当成问答”已通过这条契约修正。
