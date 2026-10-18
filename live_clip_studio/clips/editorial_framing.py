"""Stable, evidence-based portrait framing. Face boxes never identify a speaker."""
from __future__ import annotations
import math
import subprocess
from statistics import median
import cv2
import numpy as np

FPS = 30
RATIO = 1080 / 960


def pip_region(bounds, faces):
    """Return a portrait-friendly source window around a small PiP face."""
    if not faces:
        return list(bounds)
    bx, by, bw, bh = bounds
    face = faces[0]
    cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
    width = min(bw, max(240, int(face[2] * 8)))
    height = min(bh, max(int(width / RATIO), int(face[3] * 5)))
    x = max(bx, min(cx - width / 2, bx + bw - width))
    y = max(by, min(cy - height / 2, by + bh - height))
    return [int(x)//2*2, int(y)//2*2, int(width)//2*2, int(height)//2*2]


def choose_crop(bounds, observations, *, trim_bottom=False):
    """Keep head room and all observed face extents; avoid per-frame tracking."""
    x, y, w, h = bounds
    if not observations:
        return list(bounds)
    fh = median(b[3] for b in observations)
    top = min(b[1] - .35*b[3] for b in observations)
    bottom = max(b[1] + 1.4*b[3] for b in observations)
    wanted_h = min(h, max(w/RATIO, fh*2.1, bottom-top))
    cy = median(b[1]+b[3]/2 for b in observations)
    start = min(cy - wanted_h*.40, top)
    if trim_bottom and start+wanted_h>y+h:
        # Prefer less torso to reintroducing a ceiling above the head.
        wanted_h=min(wanted_h,max(w/RATIO,y+h-start))
    start = max(y, min(start, y+h-wanted_h))
    if start+wanted_h < bottom:
        wanted_h = min(h, bottom-start)
    # Keep full horizontal feed, including hair/gestures. Even coordinates for H264.
    return [int(x)//2*2, int(start)//2*2, int(w)//2*2, min(int(y+h)-int(start)//2*2, math.ceil(wanted_h/2)*2)//2*2]


def main_faces(faces, bounds, side='auto'):
    x,y,w,h=bounds
    inside=[f for f in faces if x<=f[0]+f[2]/2<=x+w and y<=f[1]+f[3]/2<=y+h]
    inside=sorted(inside,key=lambda f:f[2]*f[3],reverse=True)
    if not inside: return [], list(bounds), 'no_face'
    # Ignore tiny PiP faces. Equal-sized people stay together unless position is explicit.
    large=[f for f in inside if f[2]*f[3]>=inside[0][2]*inside[0][3]*.30]
    if side == 'main':
        # In a main-plus-PiP source, the largest detected face is the main feed.
        return [inside[0]], list(bounds), 'main_face'
    if side == 'pip':
        # A PiP assignment is only trusted when there is a distinct second face.
        # If the detector sees one face, preserving the source is safer than
        # silently zooming the main feed for the wrong speaker.
        if len(inside) >= 2 and inside[-1][2] * inside[-1][3] < inside[0][2] * inside[0][3] * .70:
            return [inside[-1]], pip_region(bounds, [inside[-1]]), 'pip_face'
        return [], list(bounds), 'no_pip_face'
    if side in ('left','right'):
        # A legacy left/right choice is ambiguous on a full portrait source.
        # When the frame contains one large face and a much smaller PiP face,
        # falling through to dominant_face would silently assign the audio to
        # the wrong person. Preserve the source until the user selects main/pip.
        if w / h < 1.05:
            if len(inside) >= 2 and inside[-1][2] * inside[-1][3] < inside[0][2] * inside[0][3] * .70:
                return [], list(bounds), 'ambiguous_pip'
            return [], list(bounds), 'no_face'
        half=[x if side=='left' else x+w/2,y,w/2,h]
        selected=[f for f in large if half[0]<=f[0] and f[0]+f[2]<=half[0]+half[2]]
        if len(selected)==1:
            return selected,half,'confirmed_'+side
        return [],list(bounds),'no_face'
    if len(large)==1: return large, list(bounds), 'dominant_face'
    return [],list(bounds),'multiple_people'


def active_vertical_bounds(gray, source_height):
    """Ignore near-black encoder letterboxing, not dark clothing/background detail."""
    rows=np.flatnonzero((gray>18).mean(axis=1)>.15)
    if not len(rows): return [0,source_height]
    scale=source_height/gray.shape[0]
    return [math.floor(rows[0]*scale),math.ceil((rows[-1]+1)*scale)]


def reframe_cut(cut, plan, layout):
    width,height=layout['source_size']; sw=456; sh=round(height*sw/width)
    command=['ffmpeg','-v','error','-i',str(cut),'-an','-vf',f'fps=2,scale={sw}:{sh},format=gray',
             '-f','rawvideo','-threads','1','-']
    detector=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    samples=[]; stride=sw*sh
    # Stream frames: a five-minute portrait must not allocate a gigabyte of RGB frames.
    with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
        while True:
            raw=process.stdout.read(stride)
            if not raw: break
            if len(raw)!=stride:
                process.kill()
                raise ValueError('EDITORIAL_FRAMES: incomplete analysis frame')
            frame=np.frombuffer(raw,dtype=np.uint8).reshape(sh,sw)
            boxes=detector.detectMultiScale(frame,1.1,5,minSize=(24,24))
            samples.append((len(samples)*.5,[list(map(float,(x*width/sw,y*height/sh,w*width/sw,h*height/sh))) for x,y,w,h in boxes],active_vertical_bounds(frame,height)))
        error=process.stderr.read().decode(errors='replace')
        if process.wait()!=0: raise ValueError('EDITORIAL_FRAMES: '+error[-1000:])
    people={p['speaker_id']:p for p in layout.get('template_options',{}).get('participants',[])}
    spans=[]
    for item in plan['items']:
        sid=plan['source_speakers'].get(str(item['tid']))
        if spans and spans[-1]['sid']==sid: spans[-1]['end']=item['out_e']
        else: spans.append({'sid':sid,'start':item['out_s'],'end':item['out_e']})
    result=[]; evidence=[]
    for shot in plan['shots']:
        edges={shot['fa'],shot['fb']}
        for previous,span in zip(spans,spans[1:]):
            # Cut at a real speaker change, never at tiny audio padding gaps.
            explicit=any(people.get(s['sid'],{}).get('screen_position','auto')!='auto' for s in (previous,span))
            if span['end']-span['start']>=1.8 and explicit:
                edge=round((previous['end']+span['start'])/2*FPS)
                if shot['fa']<edge<shot['fb']: edges.add(edge)
        edges=sorted(edges)
        for a,b in zip(edges,edges[1:]):
            midpoint=(a+b)/(2*FPS)
            span=next((s for s in spans if midpoint<s['end']),spans[-1] if spans else {})
            side=people.get(span.get('sid'),{}).get('screen_position','auto')
            # main/pip explicitly describe a full portrait source. The PiP
            # often sits outside the configured split scene, so do not crop it
            # out before face selection.
            bounds=[0,0,width,height] if side in ('main','pip') else shot.get('scene_rect',layout['scene'])
            nearby=[s for s in samples if a/FPS<=s[0]<b/FPS]
            if not nearby and samples: nearby=[min(samples,key=lambda s:abs(s[0]-midpoint))]
            decisions=[main_faces(f,bounds,side) for _,f,_ in nearby]
            modes=[d[2] for d in decisions]
            reliable=[d for d in decisions if d[0]]
            mode='preserve'; rect=list(bounds)
            # Auto crops need broad coverage; confirmed half-feeds may keep their full height through missed profiles.
            threshold=.30 if side in ('left','right') and bounds[2]/bounds[3]>=1.05 else .70
            if reliable and len(reliable)>=len(decisions)*threshold and len({d[2] for d in reliable})==1 and modes.count('multiple_people')<=len(modes)*.1:
                mode=reliable[0][2];region=reliable[0][1][:]
                if mode == 'pip_face':
                    region = pip_region([0, 0, width, height], [f for d in reliable for f in d[0]])
                if mode in ('dominant_face', 'main_face', 'pip_face') and region[2]/region[3]<1:
                    top=max(region[1],min(s[2][0] for s in nearby))
                    bottom=min(region[1]+region[3],max(s[2][1] for s in nearby))
                    # Only remove outer bands; retain all observed face boxes.
                    faces=[f for d in reliable for f in d[0]]
                    if bottom-top>=region[3]*.5 and all(top<=f[1] and f[1]+f[3]<=bottom for f in faces):
                        region=[region[0],top,region[2],bottom-top]
                rect=choose_crop(region,[f for d in reliable for f in d[0]],trim_bottom=mode=="dominant_face")
            result.append({**shot,'fa':a,'fb':b,'a':a/FPS,'b':b/FPS,'editorial_rect':rect,'framing_mode':mode})
            evidence.append({'start':a/FPS,'end':b/FPS,'speaker_id':span.get('sid'),'mode':mode,'crop':rect,
                             'samples':len(nearby),'detected_samples':len(reliable)})
    for i,shot in enumerate(result):
        if shot['framing_mode']=='preserve' and shot['fb']-shot['fa']<9:
            neighbor=result[i-1] if i else result[i+1] if len(result)>1 else shot
            if neighbor['framing_mode']!='preserve':
                shot['editorial_rect']=neighbor['editorial_rect'][:]
                shot['framing_mode']='brief_transition_hold'
    # Adjacent sentence edits with essentially the same composition share one stable crop.
    for previous,current in zip(result,result[1:]):
        p,c=previous['editorial_rect'],current['editorial_rect']
        if previous['framing_mode']==current['framing_mode'] and p[0]==c[0] and p[2]==c[2] and abs(p[1]-c[1])<24 and abs(p[3]-c[3])<24:
            top=min(p[1],c[1]);bottom=max(p[1]+p[3],c[1]+c[3]);merged=[p[0],top,p[2],bottom-top]
            previous['editorial_rect']=current['editorial_rect']=merged
    for record,shot in zip(evidence,result):
        record.update(mode=shot['framing_mode'],crop=shot['editorial_rect'])
    plan['shots']=result
    return {'revision':'editorial-framing-v3','ranges':evidence,'note':'人脸只用于稳定构图；左右发言者位置须明确填写。main/pip 用于主画面加小窗布局；检测不足保留原画面。'}
