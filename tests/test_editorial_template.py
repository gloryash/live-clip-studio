import copy
import json
from pathlib import Path

import pytest
from test_clip_contract import document, decision
from test_clip_timeline import layout
from test_clip_web_api import _job, CapturingExecutor
from live_clip_studio.clip_templates import normalize_options, build_editorial_layout
from live_clip_studio.clips.contract import decision_schema, validate_decisions
from live_clip_studio.clips.timeline import make_plan


def editorial_decision():
    value = decision()
    value['clips'][0].update(cold=[], body=[10,20,35], cards=[], lists=[], title_highlights=['观点'])
    return value


def test_editorial_contract_has_no_repeated_hook_and_preserves_argument_order():
    value = editorial_decision()
    assert validate_decisions(value, document(), template_id='editorial')['clips'][0]['cold_seconds'] == 0
    with pytest.raises(ValueError, match='SCHEMA'):
        validate_decisions(value, document())
    for change, error in [(dict(cold=[10]), 'SCHEMA'),
                          (dict(body=[20,10,35]), 'BODY_ORDER'),
                          (dict(title_highlights=['捏造']), 'TITLE_HIGHLIGHT')]:
        bad=copy.deepcopy(value);bad['clips'][0].update(change)
        with pytest.raises(ValueError, match=error):
            validate_decisions(bad,document(),template_id='editorial')
    # Four-minute arguments are allowed in this preset only.
    doc=document();doc['job']['duration_seconds']=300;doc['segments'][-1]['end']=252
    validate_decisions(value,doc,template_id='editorial')


def test_editorial_plan_keeps_all_speakers_without_artificial_camera_cycle():
    l=layout();l['template_id']='editorial'
    plan=make_plan(editorial_decision()['clips'][0],document(),l)
    assert [i['tid'] for i in plan['items']] == [10,20,35]
    assert plan['source_speakers']['20'] == 'host'
    assert all(s['mode']=='duo' and not s['flash'] for s in plan['shots'])
    assert plan['shots'][0]['fa']==0
    assert plan['shots'][-1]['fb']==plan['total_frames']


def test_options_are_explicit_bounded_and_canonical():
    assert normalize_options('editorial') == {'brand':'','series':'','participants':[]}
    a={'brand':'  栏目  ','participants':[{'speaker_id':'guest','name':'张老师','identity':'研究员'}]}
    assert normalize_options('editorial',a)['brand']=='栏目'
    with pytest.raises(ValueError, match='TEMPLATE_OPTIONS'):
        normalize_options('editorial',{'participants':[{'speaker_id':'guest','name':'','identity':'未知身份'}]})
    with pytest.raises(ValueError, match='TEMPLATE_OPTIONS'):
        normalize_options('editorial',{'brand':'a'*21})
    with pytest.raises(ValueError, match='TEMPLATE_OPTIONS'):
        normalize_options('general',a)


def test_web_options_persist_and_distinguish_runs(tmp_path):
    from fastapi.testclient import TestClient
    app, job_id = _job(tmp_path, complete=True)
    manager=app.state.clip_runs;manager.executor=CapturingExecutor();client=TestClient(app)
    payload={'job_id':job_id,'template_id':'editorial','template_options':{'brand':'栏目','participants':[
        {'speaker_id':'SPEAKER_00','name':'张老师','identity':'研究员'}]}}
    one=client.post('/api/clip-runs',json=payload).json()
    two=client.post('/api/clip-runs',json=payload).json()
    assert one['run_id']==two['run_id']
    payload['template_options']['participants'][0]['identity']='作家'
    three=client.post('/api/clip-runs',json=payload).json()
    assert one['run_id']!=three['run_id']
    assert manager._read(one['run_id'])['template_options']['participants'][0]['identity']=='研究员'
    assert len(manager.list_runs())==2
    payload['template_options']['participants'][0]['speaker_id']='not-in-source'
    assert client.post('/api/clip-runs',json=payload).status_code==422
    assert client.get('/api/clip-sources').json()['sources'][0]['clip_speakers'][0]['id']=='SPEAKER_00'


def test_editorial_selection_uses_its_own_schema_and_prompt(tmp_path):
    from live_clip_studio.clips.selection import generate_clip
    class Model:
        def request(self,prompt,schema,evidence,**kw):
            assert 'cold必须是空数组' in prompt
            assert schema==decision_schema('editorial')
            return editorial_decision()
    result=generate_clip(Model(),document(),{'start_id':10,'end_id':35,'topic':'完整论点'},tmp_path/'detail',template_id='editorial')
    assert not result['cold']


def test_real_editorial_render_has_one_window_static_title_and_no_effects(sample_mp4,tmp_path):
    from live_clip_studio.clips.render import render_clip
    from live_clip_studio.clips.editorial import build_elements, background
    from live_clip_studio.clips.qa import check_probe
    options=normalize_options('editorial',{'brand':'测试栏目','series':'第 1 期','participants':[
        {'speaker_id':'guest','name':'测试嘉宾','identity':'身份测试'}]})
    l=json.loads(build_editorial_layout(tmp_path/'layouts',320,180,tmp_path/'layout.json',options).read_text())
    doc={'segments':[{'id':1,'start':0,'end':.9,'text':'完整测试句','speaker':{'id':'guest'}}], 'job':{'duration_seconds':1}}
    clip=editorial_decision()['clips'][0];clip.update(id='01-test',body=[1],gold=[],chapters=[])
    plan=make_plan(clip,doc,l)
    elements=build_elements(clip,plan,options)
    assert all(e.anim=='none' for e in elements)
    assert background().getpixel((500,900))[3]==0
    render_clip(sample_mp4,clip,plan,l,tmp_path)
    report=json.loads((tmp_path/'01-test-render.json').read_text())
    import subprocess
    probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(tmp_path/"01-test.mp4")]))
    check_probe(probe,plan["duration"])
    graph=(tmp_path/'_work/01-test/graph.txt').read_text()
    assert '1080:960' in graph and 'pad=1080:1920:0:510' in graph
    assert 'fade=' not in graph and '[bar]' not in graph and 'whoosh' not in graph
    assert (tmp_path/'01-test-cover.jpg').stat().st_size>0


def test_template_revision_creates_new_history_without_overwriting_old(tmp_path):
    from fastapi.testclient import TestClient
    app, job_id = _job(tmp_path, complete=True)
    manager=app.state.clip_runs;manager.executor=CapturingExecutor();client=TestClient(app)
    payload={'job_id':job_id,'template_id':'editorial'}
    old=client.post('/api/clip-runs',json=payload).json()
    manager._update(old['run_id'],template_revision=1,status='completed')
    new=client.post('/api/clip-runs',json=payload).json()
    assert new['run_id'] != old['run_id'] and new['template_revision']==4
    assert client.post('/api/clip-runs',json=payload).json()['run_id']==new['run_id']
    assert manager._read(old['run_id'])['template_revision']==1


def test_position_can_be_given_without_inventing_a_name():
    value=normalize_options('editorial',{'participants':[{'speaker_id':'guest','name':'','identity':'','screen_position':'right'}]})
    assert value['participants'][0]['screen_position']=='right'
    with pytest.raises(ValueError, match='TEMPLATE_OPTIONS'):
        normalize_options('editorial',{'participants':[{'speaker_id':'guest','name':'','identity':'','screen_position':'center'}]})


def test_main_and_pip_positions_are_valid_template_options():
    value=normalize_options('editorial',{'participants':[
        {'speaker_id':'host','name':'','identity':'','screen_position':'pip'},
        {'speaker_id':'guest','name':'','identity':'','screen_position':'main'}]})
    assert {p['screen_position'] for p in value['participants']} == {'main','pip'}


def test_editorial_never_borrows_crop_from_another_video_with_same_resolution(tmp_path):
    import json
    layouts = tmp_path / "layouts"
    layouts.mkdir()
    (layouts / "other.json").write_text(json.dumps({"source_size":[912,1920],"scene":[0,588,912,744]}))
    result = json.loads(build_editorial_layout(layouts,912,1920,tmp_path/"layout.json",{"brand":"","participants":[]}).read_text())
    assert result["scene"] == [0,0,912,1920]
