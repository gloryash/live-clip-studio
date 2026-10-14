import json
from pathlib import Path

from test_clip_timeline import layout


def test_real_ffmpeg_renders_both_layouts_and_unknown_without_fixed_fb16_coords(sample_mp4, tmp_path):
    from live_clip_studio.clips.render import render_clip
    from live_clip_studio.clips.timeline import make_plan
    doc = {"format": "live-clip-studio.ai-transcript", "version": 1,
        "job": {"id": "smoke", "duration_seconds": 1},
        "segments": [{"id": 10, "start": 0, "end": .3, "text": "你好", "speaker": {"id": "guest"}},
                     {"id": 20, "start": .3, "end": .8, "text": "完整句子", "speaker": {"id": "UNKNOWN"}}]}
    clip = {"id": "01-smoke", "title": ["真实测试", "完整链路"], "hook": ["切片测试", "输入不同布局"],
        "cta": ["你怎么看", "留言"], "cold": [10], "body": [20], "chapters": [], "gold": [], "cards": [], "lists": [], "fix": []}
    for name, guest in [("split", [160, 0, 160, 180]), ("pip", [240, 90, 80, 90])]:
        l = {"version": 1, "source_size": [320, 180], "scene": [0, 0, 320, 180],
             "people": {"guest": {"role": "G", "wide": guest, "close": guest, "tag": ["嘉宾", "访谈"]}},
             "brand": "测试", "masks": []}
        out = tmp_path / name
        out.mkdir()
        plan = make_plan(clip, doc, l)
        render_clip(sample_mp4, clip, plan, l, out)
        report = json.loads((out / "01-smoke-render.json").read_text())
        assert report["probe"]["streams"][0]["width"] == 1080
        assert report["probe"]["streams"][0]["height"] == 1920
        assert (out / "01-smoke.srt").exists()
        assert (out / "01-smoke-cover.jpg").exists()
