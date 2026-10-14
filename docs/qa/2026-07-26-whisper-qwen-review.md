# Whisper → 千问文本校对 QA

- 日期：2026-07-26
- 样片：`/Users/panyupeng/Movies/插件绑定.mp4`
- Live Clip Studio 任务：`78b5ac31-a12f-4151-91bf-c3b5ad58ad95`
- ASR：`mlx-community/whisper-large-v3-turbo`
- 文本校对：`dashscope / qwen3.7-max`
- 结果：PASS 10 / FAIL 0 / BLOCKED 0

## QA 矩阵

| # | 验收项 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | Whisper 服务校对器、配置、Worker 和 API 回归 | PASS | 父项目全量 `620 passed, 1 skipped` |
| 2 | Live Clip Studio 全量回归 | PASS | `71 passed, 5 warnings` |
| 3 | 两个 Python 包均可编译 | PASS | `python -m compileall -q` 均退出 0 |
| 4 | 完整样片实际跑通 Whisper → 千问 → 说话人 → ready | PASS | 任务 `ready / 100%`，60 个句段 |
| 5 | 用户指出的关键错词全部修正 | PASS | `学办 4→0`、`学伴 0→4`、`门杰列夫 1→0`、`文杰列夫 1→0`、`门捷列夫 0→2` |
| 6 | 工作台使用千问文字，同时保留 Whisper 原文/词时间 | PASS | `raw.json` 仍是原文；60/60 句段带 `text_source=qwen_text_correction`；13 句文字实际变更 |
| 7 | 候选人物确认、全量分类和点击导出闭环 | PASS | 测试人物名“演示者”；导出按钮解锁；浏览器下载 JSON 成功 |
| 8 | AI 字幕 JSON 数据完整且时间来源诚实 | PASS | 721 字符全部还原，0 文字不匹配，0 时间越界，0 非单调句段，0 缺失说话人 |
| 9 | Whisper 页面默认千问配置与移动端 | PASS | `qwen3.7-max`、自动校对默认勾选；1440×1000 与 393×852@3x 无页面/控制台错误，无横向溢出 |
| 10 | Live Clip Studio 响应式与校对文字显示 | PASS | 1440×1000、393×852@3x、852×393@3x 均显示“数字学伴终端”和“门捷列夫”，无横向溢出、控制台错误或页面错误 |

## 实际校对结果

千问共处理 60 个句段，其中 13 个句段改变文字。关键修正包括：

```text
AI情绪调节学办形象 → AI情绪调节学伴形象
数字学办终端 → 数字学伴终端
终端界面的学办形象 → 终端界面的学伴形象
学办语音交互界面 → 学伴语音交互界面
门杰列夫元素周期表 → 门捷列夫元素周期表
你好，我是文杰列夫 → 你好，我是门捷列夫
形线成的形象 → 现成的形象
心理测试性插件 → 心理测试型插件
知识区位互动型插件 → 知识趣味互动型插件
```

## 逐字时间核验

- 46 个句段继续使用 Whisper 词时间，其中句末标点或全/半角标点差异会安全生成零时长边界。
- 10 个真正改变发音文字的句段使用 `segment_interpolation`，不把 Whisper 原词时间冒充为校对后文字的精确时间。
- 4 个句段因 7 个 Whisper 词 token 的原始时间无效，使用词级与句内插值的混合回退。
- 导出计数：397 个 `whisper_word`，85 个 `interpolated_within_word`，65 个 `synthetic_boundary`，174 个 `interpolated_within_segment`。

## 证据

- [实际导出的 AI 精准字幕](evidence/2026-07-26-whisper-qwen-review/plugin-binding-ai-transcript.json)
- [Whisper 千问配置·桌面](evidence/2026-07-26-whisper-qwen-review/whisper-qwen-desktop.jpg)
- [Whisper 千问配置·手机竖屏](evidence/2026-07-26-whisper-qwen-review/whisper-qwen-mobile.jpg)
- [工作台校对字幕·桌面](evidence/2026-07-26-whisper-qwen-review/live-clip-corrected-desktop.jpg)
- [工作台校对字幕·手机竖屏](evidence/2026-07-26-whisper-qwen-review/live-clip-corrected-mobile.jpg)
- [工作台校对字幕·手机横屏](evidence/2026-07-26-whisper-qwen-review/live-clip-corrected-mobile-landscape.jpg)

## 命令证据

```bash
# Live Clip Studio
.venv/bin/pytest tests/ -q
.venv/bin/python -m compileall -q live_clip_studio

# Whisper 服务
/Users/panyupeng/ai/视频加速提纯/live-clip-studio/.venv/bin/pytest \
  tests/test_whisper_service_correction.py \
  tests/test_whisper_service_config.py \
  tests/test_whisper_service_worker.py \
  tests/test_whisper_service_api.py \
  tests/test_whisper_service_client_app.py -q
/Users/panyupeng/ai/视频加速提纯/live-clip-studio/.venv/bin/python -m compileall -q whisper_service
```

警告仅为现有 Starlette/httpx 弃用提示与 Pillow `getdata` 弃用提示，本轮无新增测试失败。
