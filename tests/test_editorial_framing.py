from live_clip_studio.clips.editorial_framing import choose_crop, main_faces


def test_portrait_removes_ceiling_but_preserves_all_face_positions():
    faces=[[203,1068,423,423],[190,1040,430,430]]
    x,y,w,h=choose_crop([0,0,912,1920],faces)
    assert w==912 and h<1100 and y>600
    for fx,fy,fw,fh in faces:
        assert y<=fy-.3*fh and y+h>=fy+fh
    assert y+h<=1920


def test_tiny_pip_is_not_primary_and_multi_person_requires_confirmed_side():
    face,region,mode=main_faces([[698,536,73,73],[203,1068,423,423]],[0,0,912,1920])
    assert mode=='dominant_face' and len(face)==1
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
