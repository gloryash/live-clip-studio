from PIL import Image, ImageDraw


def scene_layout():
    return {'source_size': [912, 1920], 'scene': [0, 588, 912, 744],
            'people': {'host': {'role': 'H', 'wide': [0, 608, 456, 566], 'close': [10, 633, 410, 509]}}}


def test_letterbox_guard_preserves_fullscreen_instead_of_cutting_half_a_face():
    from live_clip_studio.clips.visual import layout_matches_frame, resolve_shots
    full = Image.new('L', (96, 202), 170)
    split = Image.new('L', (96, 202), 0)
    ImageDraw.Draw(split).rectangle((0, 62, 95, 139), fill=170)
    layout = scene_layout()
    assert layout_matches_frame(split, layout)
    assert not layout_matches_frame(full, layout)
    shots = [{'fa': 0, 'fb': 6, 'mode': 'hc', 'flash': True, 'a': 0, 'b': .2}]
    resolved = resolve_shots(shots, [True, True, False, False, True, True], layout)
    assert [(s['fa'], s['fb']) for s in resolved] == [(0, 2), (2, 4), (4, 6)]
    assert resolved[1]['foreground_rect'] == [0, 0, 912, 1920]
    assert resolved[1]['scene_rect'] == [0, 0, 912, 1920]
    assert [s['flash'] for s in resolved] == [True, False, False]
    assert resolved[2]['foreground_rect'] == layout['people']['host']['close']


def test_shot_filter_and_cover_use_resolved_geometry():
    from live_clip_studio.clips.render import shot_filter, cover_rect
    layout = scene_layout()
    shot = {'fa': 0, 'fb': 30, 'mode': 'hc', 'flash': False,
            'foreground_rect': [0, 0, 912, 1920], 'scene_rect': [0, 0, 912, 1920],
            'layout_mode': 'preserve_source'}
    graph = shot_filter(0, shot, layout)
    assert graph.count('crop=912:1920:0:0') == 2
    assert 'crop=410:509:10:633' not in graph
    assert cover_rect({'shots': [shot], 'items': [{'speaker': 'H'}]}, layout) == [0, 0, 912, 1920]


def test_freeze_detector_ignores_graphics_and_resets_at_source_cuts():
    from live_clip_studio.clips.visual import find_holds
    # 90 unchanged actor frames, 30 fps; a source cut breaks the hold.
    spans = find_holds([0.] * 90, [False] * 45 + [True] + [False] * 44, minimum_frames=40)
    assert len(spans) == 2
    assert all(s['duration'] < 1.6 for s in spans)
    assert not find_holds([2.] * 90, [False] * 90, minimum_frames=40)


def test_real_cut_switches_geometry_on_the_exact_layout_change_frame(tmp_path):
    import subprocess
    from live_clip_studio.clips.visual import inspect_cut
    cut = tmp_path / 'switch.mkv'
    # Tiny portrait fixture: letterboxed split, then full-screen single.
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'color=black:s=96x202:r=30:d=2', '-vf',
                    "drawbox=x=0:y=62:w=96:h=78:color=white:t=fill,drawbox=x=0:y=0:w=96:h=202:color=white:t=fill:enable='gte(n,30)'",
                    '-c:v', 'libx264', '-threads', '1', '-crf', '12', str(cut)], check=True)
    plan = {'total_frames': 60, 'pieces': [{'out': 0, 'source_start': 100}],
            'shots': [{'fa': 0, 'fb': 60, 'mode': 'hc', 'flash': False, 'a': 0, 'b': 2}]}
    shots, report = inspect_cut(cut, plan, scene_layout())
    assert [(s['fa'], s['fb'], s['layout_mode']) for s in shots] == [(0, 30, 'template'), (30, 60, 'preserve_source')]
    assert report['preserved_source_seconds'] == 1


def test_motion_detects_frozen_host_even_when_guest_moves_and_zoom_changes(tmp_path):
    import subprocess
    from live_clip_studio.clips.visual import inspect_cut
    cut = tmp_path / 'frozen-host.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'color=gray:s=48x202:r=30:d=2', '-f', 'lavfi', '-i',
                    'testsrc2=s=48x202:r=30:d=2', '-filter_complex', '[0:v][1:v]hstack[v]',
                    '-map', '[v]', '-c:v', 'libx264', '-threads', '1', '-crf', '12', str(cut)], check=True)
    plan = {'total_frames': 60, 'pieces': [{'out': 0, 'source_start': 100}],
            'shots': [{'fa': 0, 'fb': 30, 'mode': 'hc', 'flash': False},
                      {'fa': 30, 'fb': 60, 'mode': 'hw', 'flash': False}]}
    _, report = inspect_cut(cut, plan, scene_layout())
    assert len(report['source_holds']) == 1
    hold = report['source_holds'][0]
    assert hold['duration'] > 1.9
    assert 100 <= hold['source_start'] < 100.1
    assert hold['source_end'] == 102
