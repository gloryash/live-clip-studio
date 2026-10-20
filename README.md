# Live Clip Studio

本地直播视频理解工作台。上传本地视频后，通过 Whisper 生成带时间轴的原始识别，再使用千问文本模型严格校对错别字和专有名词，同时保留匿名说话人分段和可解释的时间来源。

## 快速启动

1. 先启动本机 Whisper Large V3 Turbo 服务：

   ```bash
   "/Users/panyupeng/Desktop/星盘下的子模块/玄学自媒体/douyin-downloader/start-whisper-service.command"
   ```

2. 检查服务与模型：

   ```bash
   curl -fsS http://127.0.0.1:8765/health
   ```

   返回必须包含 `"status":"ok"` 和 `mlx-community/whisper-large-v3-turbo`。

3. 双击 [start.command](./start.command)，或在终端运行：

   ```bash
   cd "/Users/panyupeng/ai/视频加速提纯/live-clip-studio"
   ./start.command
   ```

4. 浏览器会打开 `http://127.0.0.1:8788`。

首页“自动切片”下方的“成片历史”保存每次转换记录。点击记录可直接预览成片、查看传播评分和 AI 评价，并下载视频、封面、字幕。成片统一保存于 `exports/auto-clips/<run_id>/`，刷新网页或重新启动服务不会清除它们。同一场直播使用同一模板、相同模板资料再次操作会打开已有结果，不重复调用模型或渲染；失败记录保留，并允许重试。

`start.command` 会用 `uv` 同步项目和 diarization 依赖。首次运行可能需要下载 SpeechBrain ECAPA 模型；之后使用本机缓存。

## 使用方式

- 视频可以点击选择、拖入，或在文件夹中复制视频文件后回到首页按 `⌘V`（Mac）/ `Ctrl+V`（Windows）粘贴。显示文件名和大小后，点击“开始分析”。复制视频链接或应用内消息不一定包含视频文件；无法粘贴时先保存视频，再选择或拖入。
- 上传视频后自动进入工作台，字幕面板先完成 Whisper 转写与千问文本校对，再在不知道人数的情况下生成匿名说话人候选。
- 每个候选人物提供最多 3 段代表语音。点击即可按原视频时间范围试听；候选可以自动创建新人物，也可以合并到已有说话人并重命名。
- 候选若包含多人、噪声或明显错误，可选择“混合声音 / 错误候选（排除注册）”。它会计为已处理，但不会创建人物或污染注册声纹；其中字幕仍由其他已确认人物重新分类。
- 全部候选确认后，点击“应用到全部字幕”会用注册声纹重新分类字幕。低置信度短片段不会被强行归人。
- 完成候选确认和全量分类后，可点击“导出 AI 精准字幕 JSON”。该文件包含整场对话、句段起止时间、说话人 ID/姓名/置信度、Whisper 逐词时间，以及覆盖原文每个字符的时间。它不要求逐条完成人工标注；已有的逐条人工说话人修正会优先于自动分类，无法判断的片段保留为 `UNKNOWN`。
- 每条字幕保留原文、开始/结束时间和 `说话人 1 / 2 / …`。点击字幕可跳到对应视频位置。
- 首次打开“关键帧”标签页会自动启动场景抽帧和双通道去重。
- 关键帧列数允许 `2–10`，行数允许 `1–20`；`2×20` 为 40 张/页，`10×10` 为 100 张/页。
- 刷新页面会通过 `job_id` 恢复已生成的字幕和关键帧。
- 首页会显示本机历史记录。再次导入字节内容完全相同的视频时，系统会按完整 SHA-256 与文件大小命中已有任务，直接打开原工作台，不会重复上传、转写或抽帧。
- 需要更新某项产物时，在工作台显式点击“重新生成字幕”或“重新提取”。前者只重跑转写与说话人区分，保留已有关键帧；后者只重跑关键帧，保留字幕。
- 字幕卡片右侧可人工标记为“说话人 1 / 说话人 2”。每次点击立即保存到本机；全部句子标完后，“导出训练集 JSONL”会下载带音频相对路径、时间范围、原算法标签和人工标签的清单。
- 开启“快捷标注”后，`←` 标记说话人 1，`→` 标记说话人 2，保存后自动选中下一句并同步视频。`Space` 控制播放/暂停；长字幕使用文本长度估算智能预听点，避免从几十秒片段的开头等待。
- 存在逐条人工标准答案时，分类后显示两项指标：“标注内正确率”统计全部已标注字幕；“独立验证正确率”排除用于注册声纹的代表片段。未标记字幕不进入正确率分母。

## 本地数据

每个任务保存在 `data/<job_id>/`：

```text
source.mp4
media.json
job.json
transcript/raw.json
transcript/raw.txt
transcript/segments.json
transcript/speaker-turns.json
transcript/speaker-embeddings.npz
transcript/speaker-candidates.json
transcript/speaker-candidate-assignments.json
transcript/speaker-predictions.json
transcript/manual-speaker-labels.json
keyframes/frames.json
keyframes/frame_*.jpg
```

`job.json` 还保存源文件的 `sha256` 与 `size_bytes`，用于本机历史复用。若源文件内容改变（即使文件名相同），会创建新任务；若只是同内容文件换了名称或路径，则会命中既有任务。

视频、音频、字幕、图片、声纹候选、算法预测和人工标注均保存在本机。人工标准答案与算法预测使用不同文件，重新分类不会覆盖人工标注。Whisper 完成后，服务会把识别文本发送给阿里云千问做文本校对；原始音频和视频不会发送给千问。云端校对失败时，任务仍使用 Whisper 原文完成。

AI 精准字幕中的逐字时间会如实标注来源：`whisper_word` 是单字 token 的原始 Whisper 时间，`interpolated_within_word` 是多字 token 内等分，`synthetic_boundary` 是空格或标点锚定的边界，`interpolated_within_segment` 是逐词时间缺失、异常，或千问改字后无法与 Whisper 原词对齐时的句段内回退。它是基于 Whisper 词时间的最佳可解释对齐，不宣称达到音素级强制对齐精度。

候选协议与声纹模型解耦。新视频当前默认使用 ECAPA embedding；已经验证的直播样本使用缓存的 CAM++ embedding 迁移进入同一候选确认界面。

## 可选配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LIVE_CLIP_DATA_DIR` | 项目内 `data/` | 任务数据目录 |
| `LIVE_CLIP_WHISPER_URL` | `http://127.0.0.1:8765` | Whisper 服务地址 |
| `LIVE_CLIP_WHISPER_MODEL` | `mlx-community/whisper-large-v3-turbo` | 必须匹配的模型名 |
| `LIVE_CLIP_WHISPER_TIMEOUT` | `7200` | 转写最长等待秒数 |
| `LIVE_CLIP_MAX_UPLOAD_BYTES` | `53687091200` | 最大视频字节数 |
| `LIVE_CLIP_EXECUTOR_WORKERS` | `2` | 本地后台工作线程数 |

## 测试

```bash
uv run pytest -q
python3 -m compileall -q live_clip_studio
```

## 固定模板切片流水线

AI 只负责从已标注的 AI 精准字幕中选择句段并填写 JSON 配置；后端负责校验、时间线、布局、FFmpeg 渲染、封面和 Whisper QA。网页自动转换按素材分辨率选择 `editing/layouts/` 中的布局，使用原有单人近景／中景和横向双人模板。检测到源画面边界变化时保留完整源画面。布局参数示例放在 `editing/layouts/`，可复制 `main-pip.example.json` 修改。

网页现有两个预设：

- **一般**：原有冷开场、单人近中景切换、悬念卡、金句及互动卡。
- **观点对谈**：从三条参考成片提炼的黑绿观点包装。自然问题或观点开场、按原顺序保留完整论证、单一画面窗口、固定两行标题和绿色关键词、白色字幕；60–300 秒，不重复金句开场，不加白闪、悬念卡或互动尾卡。v3 对竖屏录屏检测稳定的主要人脸并裁去过多留白；不足以可靠检测时保留原画面。左右分屏可按用户确认的出镜位置切换发言者；主画面加小窗布局可明确选择“主画面／右上角小窗”，不能从声音 ID 猜测人脸身份。

选择“观点对谈”后，可填写品牌名、栏目名，以及每位已标注说话人的姓名/称呼和身份/职务。未知资料留空；姓名身份以小型“发言”信息条显示在主画面侧边。还可选填左侧／右侧出镜位置（稳定左右分屏），或主画面／右上角小窗（竖屏主画面加 PiP），不确定时选自动／保留多人。说话人名称仅作为填写参考，系统不自动推断或生成职务。相同资料和模板版本复用已有结果，改资料或升级模板产生新任务并保留旧成片。点击历史记录可恢复该任务的资料。

v2 迭代与成片对照见 [构图改进验证](docs/qa/editorial-v2/README.md)。参考拆解与 v1 验证见 [第二模板计划](docs/reference-template-plan.md) 和 [验证记录](docs/qa/reference-template/README.md)。

```bash
# 先检查输入、布局和字幕，不调用模型
uv run python -m live_clip_studio.clips prepare \
  --job-dir data/<job-id> --layout editing/layouts/geo.json \
  --out exports/<run>

# 全链路：分窗选题 → 细化配置 → 校验 → 渲染 → 回听 QA
uv run python -m live_clip_studio.clips run \
  --job-dir data/<job-id> --layout editing/layouts/geo.json \
  --out exports/<run> --count 3
```

每次运行在输出目录保留 `run.json`、`events.jsonl`、`input-report.json`、`ai/`、`decisions.json`、`plans/`、MP4/SRT/封面、`qa/` 和 `publish.md`。修改 `decisions.json` 后可使用 `--decisions` 进入不调用 AI 的渲染/QA；发布前仍必须人工完整观看。

本地版本保存和回滚方式见 [Git 回滚说明](docs/git-rollback.md)。
