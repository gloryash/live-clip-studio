# Live Clip Studio 第一阶段 QA 结果

## 环境

- 日期：2026-07-23
- 项目：`/Users/panyupeng/ai/视频加速提纯/live-clip-studio`
- 本地 URL：`http://127.0.0.1:8788`
- Whisper：`http://127.0.0.1:8765`，`mlx-community/whisper-large-v3-turbo`
- 真实样例：`02-mercury-career.mp4`，`job_id=f407d13c-fa25-4d44-82c3-a968eda06465`
- 样例结果：49.364 秒，31 条字幕，2 个匿名说话人，54 张候选帧，49 张去重关键帧

## 验收矩阵

| 需求项 | 验证方式 | 通过标准 | 状态 | 证据 |
| --- | --- | --- | --- | --- |
| Whisper 未开启警告 | 8791 临时服务 + Agent Browser | 显示指定警告，上传按钮禁用 | PASS | `screenshots/whisper-offline-warning-fresh.jpg` |
| Whisper 模型合同 | 真实 health + pytest | 只接受精确模型名 | PASS | `curl /health`；`tests/test_health.py` |
| 视频上传与页面跳转 | TestClient + 已持久化真实 job | 返回 `job_id` 和 workspace URL，视频可播放 | PASS | `tests/test_jobs_api.py`；`data/f407d13c-.../source.mp4` |
| 精准字幕时间轴 | 真实 Mercury + JSON 检查 | 原始 ASR 保留，31 条 turn 有序且 `start < end` | PASS | `transcript/raw.json`；`transcript/speaker-turns.json` |
| 匿名说话人区分 | embedding 测试 + 真实 Mercury | 显示至少 2 个匿名标签 | PASS | `speaker_count=2`；`tests/test_diarization.py` |
| diarization 诚实降级 | processor/API/UI 测试 | 保留文字，人数未知，不伪装单人 | PASS | `tests/test_processor.py`；`tests/test_health.py` |
| 点击字幕跳转 | Agent Browser DOM click | `currentTime` 设为 24.36 秒，误差 < 0.5 秒 | PASS | 实测 `target=24.36, currentTime=24.36, delta=0` |
| 关键帧按需启动 | API 幂等测试 + JS 回归测试 | 首次打开标签页自动 POST，重复请求只提交一次 | PASS | `tests/test_keyframes.py`；`tests/test_web_contract.py` |
| 场景候选与双通道去重 | synthetic red/blue video | 场景变化保留，重复蓝帧移除 | PASS | `tests/test_keyframes.py` |
| 关键帧无上限 | wrapper contract + 真实 frames.json | `max_frames=0`，无 `capped=true` | PASS | 49 张实帧；`tests/test_keyframes.py` |
| `2×20` / `10×10` 矩阵 | Agent Browser | 40/100 张每页，2/10 列，40+9 翻页正确 | PASS | `screenshots/keyframes-2x20-fresh.jpg`；`keyframes-10x10-fresh.jpg` |
| 点击关键帧跳转 | JS 事件 + 播放器状态检查 | `currentTime` 等于帧时间戳，误差 < 0.5 秒 | PASS | workspace 浏览器运行记录 |
| 刷新恢复任务 | Agent Browser reload | 恢复 31 条字幕、2 个说话人、49 张关键帧 | PASS | `screenshots/workspace-transcript-desktop-fixed.jpg` |
| 响应式布局 | 1440×1000 + 390×844 | 核心控件可达，手机端无横向溢出 | PASS | `screenshots/workspace-mobile-fresh.jpg`；`scrollWidth=clientWidth=375` |
| 本地数据边界 | 源码 + 文件系统检查 | 运行产物只写入 `data/<job_id>/`，无 CDN/外部分析 API | PASS | `data/f407d13c-.../`；源码 `rg` 检查 |

## 浏览器证据

- 桌面上传页：`screenshots/upload-desktop.jpg`
- 字幕工作台：`screenshots/workspace-transcript-desktop-fixed.jpg`
- 关键帧 2×20：`screenshots/keyframes-2x20-fresh.jpg`
- 关键帧 10×10：`screenshots/keyframes-10x10-fresh.jpg`
- 手机端：`screenshots/workspace-mobile-fresh.jpg`
- Whisper 不可用：`screenshots/whisper-offline-warning-fresh.jpg`
- 页面 console 与 uncaught page errors：无输出。

## 返工记录

| 轮次 | 失败项 | 根因 | 修复动作 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | 成功后仍显示 diarization 警告和 loading | 组件 `display:flex` 覆盖 HTML `hidden` | 增加 `[hidden]{display:none!important}` 与回归测试 | PASS |
| 1 | 首次打开关键帧不会自动启动 | tab 只调用 GET，未根据 `not_started` POST | 新增 `activateKeyframes()` 与回归测试 | PASS |
| 1 | 页面请求默认 favicon 返回 404 | 没有声明本地图标 | 新增本地 SVG favicon 与合同测试 | PASS |

## 自动验证

```text
uv run pytest -q
python3 -m compileall -q live_clip_studio
curl -fsS http://127.0.0.1:8788/api/health
rg -n 'TODO|TBD|cdn|https://.*(js|css)' live_clip_studio tests
find docs/qa/screenshots -type f -name '*.png'
```

最终验证以上述命令的当次输出为准。

当次结果：`32 passed`，编译成功，health 为 `ready=true`，无 TODO/TBD/CDN 命中，无 PNG 证据图，所有截图文件头均为 JPEG。5 条 warning 均来自 Starlette TestClient 和上游 `claude-real-video` 的 Pillow 弃用提示，项目代码无 warning。
