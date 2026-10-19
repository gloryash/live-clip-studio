from live_clip_studio.clips.editorial_framing import (
    choose_crop,
    main_faces,
)


def test_portrait_removes_ceiling_but_preserves_all_face_positions():
    faces=[[203,1068,423,423],[190,1040,430,430]]
    x,y,w,h=choose_crop([0,0,912,1920],faces)
    assert w==912 and h<1100 and y>600
    for fx,fy,fw,fh in faces:
        assert y<=fy-.3*fh and y+h>=fy+fh
    assert y+h<=1920


def test_tiny_pip_is_not_primary_and_multi_person_requires_confirmed_side():
    face,region,mode=main_faces([[698,536,73,73],[203,1068,423,423]],[0,0,912,1920])
    assert mode=='multiple_people' and not face
    faces=[[119,812,280,280],[466,826,401,401]]
    assert main_faces(faces,[0,588,912,744])[2]=='multiple_people'
    face,region,mode=main_faces(faces,[0,588,912,744],'right')
    assert mode=='confirmed_right' and region==[456,588,456,744]
    assert face==[faces[1]]


def test_main_and_pip_positions_select_the_speaking_face_in_portrait_source():
    faces=[[350,269,34,34],[114,509,235,235]]
    main, main_region, main_mode=main_faces(faces,[0,0,912,1920],'main')
    pip, pip_region, pip_mode=main_faces(faces,[0,0,912,1920],'pip')
    assert main_mode=='main_face' and main==[faces[1]]
    assert pip_mode=='pip_face' and pip==[faces[0]]
    assert pip_region[2] < 240 and pip_region[3] < 300
    assert pip_region[0] <= faces[0][0] and pip_region[0]+pip_region[2] >= faces[0][0]+faces[0][2]


def test_legacy_left_right_does_not_assign_portrait_pip_audio_to_main_face():
    faces=[[698,536,73,73],[203,1068,423,423]]
    face, region, mode=main_faces(faces,[0,0,912,1920],'left')
    assert face == [] and region == [0,0,912,1920] and mode == 'ambiguous_pip'


def test_uncertain_and_edge_faces_never_produce_out_of_bounds_crops():
    assert choose_crop([0,0,912,1920],[])==[0,0,912,1920]
    for face in [[0,0,400,400],[0,1700,200,200],[600,500,300,300]]:
        x,y,w,h=choose_crop([0,0,912,1920],[face])
        assert 0<=x<x+w<=912 and 0<=y<y+h<=1920
        assert all(v%2==0 for v in [x,y,w,h])


def test_title_punctuation_uses_same_baseline_as_chinese_characters():
    from live_clip_studio.clips.editorial import highlighted_line
    from live_clip_studio.clips.timeline import graphics
    size=80
    image=highlighted_line('游戏，未来',['游戏'],size)
    x=round(graphics.font(graphics.BOLD,size).getlength('游戏'))
    comma=image.crop((x,0,x+size,115)).getbbox()
    assert comma and comma[1]>35, 'Chinese comma must sit low, not look like an opening quote'


def test_portrait_encoder_bars_are_removed_without_trimming_dark_clothing():
    import numpy as np
    from live_clip_studio.clips.editorial_framing import active_vertical_bounds
    gray=np.zeros((960,456),dtype=np.uint8)
    gray[72:864]=60
    gray[700:864]=25
    gray[880:884,:20]=150  # a small watermark below the image is not an active row
    assert active_vertical_bounds(gray,1920)==[144,1728]
    assert active_vertical_bounds(np.zeros_like(gray),1920)==[0,1920]
    rect=choose_crop([0,144,912,1584],[[200,1100,420,420]])
    assert rect[1]+rect[3]<=1728


def test_bottom_boundary_does_not_push_portrait_back_into_empty_ceiling():
    rect=choose_crop([0,144,912,1584],[[200,1100,420,420]],trim_bottom=True)
    assert rect[1]>=900
    assert rect[1]+rect[3]<=1728
    assert rect[1]<=1100-420*.3
    assert rect[1]+rect[3]>=1520



def test_auto_never_equates_largest_face_with_current_speaker():
    faces = [[698, 536, 73, 73], [203, 1068, 423, 423]]
    assert main_faces(faces, [0, 0, 912, 1920])[2] == "multiple_people"


def test_audio_visual_evidence_selects_small_face_and_rejects_ambiguous_scores():
    from live_clip_studio.clips.active_speaker import select_active_face
    candidates = [
        {"track_id": "large", "score": -1.1, "coverage": 1.0},
        {"track_id": "small", "score": 2.3, "coverage": .9},
    ]
    assert select_active_face(candidates)["track_id"] == "small"
    assert select_active_face([{**c, "score": 2.1} for c in candidates])["track_id"] is None
    assert select_active_face([{**candidates[1], "coverage": .2}])["track_id"] is None
    assert select_active_face([{**candidates[1], "score": -.4}])["track_id"] is None


def test_short_speaker_change_and_piece_boundaries_are_not_ignored():
    from live_clip_studio.clips.active_speaker import analysis_ranges
    plan = {"total_frames": 120, "source_speakers": {"1": "a", "2": "b", "3": "a"},
            "items": [{"tid": 1, "out_s": 0, "out_e": 1},
                      {"tid": 2, "out_s": 1, "out_e": 1.6},
                      {"tid": 3, "out_s": 1.6, "out_e": 4}],
            "pieces": [{"out": 0, "frames": 72}, {"out": 2.4, "frames": 48}]}
    ranges = analysis_ranges(plan)
    assert [(r["fa"],r["fb"],r["speaker_id"]) for r in ranges] == [
        (0,30,"a"),(30,48,"b"),(48,72,"a"),(72,120,"a")]


def test_low_confidence_framing_enters_overall_review():
    from live_clip_studio.clips.qa import framing_review_ranges
    source_visual = {"editorial_framing": {"review_ranges": [{"start":0,"end":2,"reason":"ambiguous_activity"}]}}
    assert framing_review_ranges(source_visual) == source_visual["editorial_framing"]["review_ranges"]


def test_source_padding_at_edit_does_not_create_one_frame_wrong_person():
    from live_clip_studio.clips.active_speaker import analysis_ranges
    plan = {"total_frames":120,"source_speakers":{"1":"a","2":"b"},
            "items":[{"tid":1,"out_s":0,"out_e":1.84},{"tid":2,"out_s":2.12,"out_e":4}],
            "pieces":[{"out":0,"frames":60},{"out":2,"frames":60}]}
    assert [(r['fa'],r['fb'],r['speaker_id']) for r in analysis_ranges(plan)] == [(0,60,'a'),(60,120,'b')]


def test_measured_face_crop_survives_mirror_and_rescale_without_location_inputs():
    from live_clip_studio.clips.editorial_framing import speaking_face_crop
    for factor in (.5,1,2):
        for mirror in (False,True):
            def track(box):
                x,y,w,h=box
                if mirror: x=912-x-w
                return {'observations':[(0,[v*factor for v in (x,y,w,h)])], 'coverage':1}
            small=track([700,540,70,70]); large=track([200,1050,420,420])
            x,y,w,h=speaking_face_crop([int(912*factor),int(1920*factor)],small,[large])
            fx,fy,fw,fh=small['observations'][0][1]
            assert x<=fx<fx+fw<=x+w and y<=fy<fy+fh<=y+h
            assert fw/w>.35 and fh/h>.35
            assert y+h<large['observations'][0][1][1]


def test_distant_pip_does_not_narrow_main_subject_unnecessarily():
    from live_clip_studio.clips.editorial_framing import speaking_face_crop
    main={'coverage':1,'observations':[(0,[200,1050,420,420])]}
    pip={'coverage':1,'observations':[(0,[700,540,70,70])]}
    assert speaking_face_crop([912,1920],main,[pip]) == speaking_face_crop([912,1920],main,[])


def test_identity_and_previous_manual_positions_cannot_override_audio_visual_match(monkeypatch):
    from live_clip_studio.clips import active_speaker
    from live_clip_studio.clips.editorial_framing import reframe_cut
    from pathlib import Path
    records=[]
    for a,b,sid,selected in [(0,30,'a','small'),(30,120,'b','large')]:
        records.append({'fa':a,'fb':b,'start':a/30,'end':b/30,'speaker_id':sid,
                        'decision':{'track_id':selected,'reason':'audio_visual_match'},
                        'tracks':[{'track_id':'large','coverage':1,'observations':[(0,[200,1050,420,420])]},
                                  {'track_id':'small','coverage':1,'observations':[(0,[700,540,70,70])]}]})
    monkeypatch.setattr(active_speaker,'analyze_cut',lambda *args: {'ranges':records})
    plan={}
    result=reframe_cut(Path('unused'),plan,{'source_size':[912,1920],'template_options':{'participants':[
        {'speaker_id':'a','name':'虚构身份','screen_position':'main'},
        {'speaker_id':'b','name':'另一身份','screen_position':'pip'}]}})
    assert plan['shots'][0]['editorial_rect'][1]<700
    assert plan['shots'][1]['editorial_rect'][1]>800
    assert not result['review_ranges']


def test_continuity_uses_observed_face_track_only_within_same_audio_and_source_piece():
    from live_clip_studio.clips.editorial_framing import resolve_continuity
    def record(a, sid, chosen, piece=0):
        return {'fa':a,'fb':a+30,'piece_index':piece,'speaker_id':sid,
                'decision':{'track_id':chosen,'reason':'audio_visual_match' if chosen else 'ambiguous_activity'},
                'tracks':[{'track_id':'left','coverage':1,'observations':[(0,[100+a/30,300,80,100])]},
                          {'track_id':'right','coverage':1,'observations':[(0,[500,300,80,100])]}]}
    rows=[record(0,'a','left'),record(30,'a',None),record(60,'b',None),record(90,'a',None,1)]
    resolve_continuity(rows)
    assert rows[1]['decision']['track_id']=='left'
    assert rows[1]['decision']['reason']=='continuous_observed_face_track'
    assert rows[2]['decision']['track_id'] is None
    assert rows[3]['decision']['track_id'] is None
