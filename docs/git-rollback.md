# 本地版本与回滚

`restored-interview-layout` 标签标记 2026-10-14 恢复的单人近景／中景、横向双人模板基线。保留源画面边界保护；已撤销人脸检测和双人上下排列。

每次修改前先查看状态并保存当前代码：

```sh
git status
git add <本次修改的文件>
git commit -m "说明本次修改"
```

查看历史：`git log --oneline --decorate`。

撤销某次已经提交的修改，保留历史：`git revert <提交号>`。

恢复当前基线的模板文件（执行前先提交需要保留的工作）：

```sh
git restore --source restored-interview-layout -- live_clip_studio/clip_templates.py live_clip_studio/clip_runs.py live_clip_studio/clips/render.py live_clip_studio/clips/visual.py
git add live_clip_studio
git commit -m "restore interview layout baseline"
```

Git 管理源码、测试、文档、布局与选题配置、运行所需字体。原视频、成片、运行历史、临时文件、环境和密钥不进入 Git。Git 回滚代码不会自动恢复成片；重新渲染前应另存对应运行目录。

本次被撤销的代码和成片保存在 `tmp/layout-rollback/`；原始运行备份在 `tmp/clip-audit/before/`。网页中的成片存放于 `exports/auto-clips/02ef190a-a2e4-4f75-9e09-6c23052add1f/`，按恢复后的模板重新渲染，复用原来的选题与评分。

## 本次验证

- `python -m pytest -q`：125 passed，5 个既有依赖弃用警告。
- `node --check live_clip_studio/web/app.js` 与 `uv lock --check --offline` 通过。
- 三条成片重新渲染完成；计划均为 `source-framing-guard-v1`，无 `panels` 或 `duo_stacked`。
- 共享 Chrome 9400 上验证历史记录和第 84、85 分钟对应成片：1080×1920，跳转至 10 秒后正常播放，无媒体错误；Range 请求返回 206。
- 成片质检状态仍为 `REVIEW`，未标为通过全部发布审核。
- 抽帧与网页截图：`tmp/layout-rollback/restored-layout.jpg`、`tmp/layout-rollback/web-restored.jpg`。
