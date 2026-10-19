"""Stable, evidence-based portrait framing. Face boxes never identify a speaker."""
from __future__ import annotations
import math
from statistics import median
import cv2
import numpy as np

FPS = 30
RATIO = 1080 / 960


def pip_region(bounds, faces):
    """Return a tight portrait-friendly source window around a small PiP face.

    The detected face is already inside the small source panel. A broad
    window makes the panel stay visually small after the portrait render, so
    keep only a modest margin around the face and panel label.
    """
    if not faces:
        return list(bounds)
    bx, by, bw, bh = bounds
    face = faces[0]
    cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
    width = min(bw, max(150, int(face[2] * 2.4)))
    height = min(bh, max(int(width / RATIO), int(face[3] * 2.5)))
    # PiP labels are normally rendered below the face. Bias the window upward
    # so the label does not become the dominant element after enlargement.
    cy -= face[3] * .5
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
    if len(inside)==1: return inside, list(bounds), 'dominant_face'
    return [],list(bounds),'multiple_people'


def active_vertical_bounds(gray, source_height):
    """Ignore near-black encoder letterboxing, not dark clothing/background detail."""
    rows=np.flatnonzero((gray>18).mean(axis=1)>.15)
    if not len(rows): return [0,source_height]
    scale=source_height/gray.shape[0]
    return [math.floor(rows[0]*scale),math.ceil((rows[-1]+1)*scale)]


def speaking_face_crop(size, target, others):
    """Measured face-relative composition; never a source-pixel layout preset.

    Keep the whole observed head and a little torso. Exclude other observed
    faces; if two people overlap too closely, refuse to invent a single view.
    """
    width, height = size
    faces = [b for _, b in target['observations']]
    fw, fh = median(b[2] for b in faces), median(b[3] for b in faces)
    left, right = min(b[0] for b in faces), max(b[0]+b[2] for b in faces)
    top, bottom = min(b[1] for b in faces), max(b[1]+b[3] for b in faces)
    w = min(width, max(fw*2.3, right-left+fw*.5))
    h = min(height, max(fh*2.1, bottom-top+fh*.65))
    cx = median(b[0]+b[2]/2 for b in faces)
    x = max(0, min(cx-w/2, width-w))
    y = max(0, min(top-fh*.38, height-h))
    for track in others:
        if track['coverage'] < .5: continue
        for _, (ox,oy,ow,oh) in track['observations']:
            if ox+ow<=x or ox>=x+w or oy+oh<=y or oy>=y+h:
                continue
            if ox+ow <= left:
                nx = max(x, (ox+ow+left)/2); w -= nx-x; x=nx
            elif ox >= right:
                w = min(w, (right+ox)/2-x)
            if oy+oh <= top:
                ny = max(y, (oy+oh+top)/2); h -= ny-y; y=ny
            elif oy >= bottom:
                h = min(h, (bottom+oy)/2-y)
    # Outward rounding preserves head extents, within even source boundaries.
    x,y = int(x)//2*2, int(y)//2*2
    w,h = min(width-x,math.ceil(w/2)*2)//2*2,min(height-y,math.ceil(h/2)*2)//2*2
    if min(w,h) < 2 or any(not (x<=b[0] and y<=b[1] and x+w>=b[0]+b[2] and y+h>=b[1]+b[3]) for b in faces):
        return None
    for track in others:
        if track['coverage'] < .5: continue
        if any(min(x+w,b[0]+b[2])>max(x,b[0]) and min(y+h,b[1]+b[3])>max(y,b[1]) for _,b in track['observations']):
            return None
    return [x,y,w,h]


def reframe_cut(cut, plan, layout):
    from .active_speaker import analyze_cut, REVISION
    analysis = analyze_cut(cut,plan,layout['source_size'])
    full = [0,0,*layout['source_size']]
    shots, evidence, review = [], [], []
    for record in analysis['ranges']:
        chosen = record['decision']['track_id']
        target = next((t for t in record['tracks'] if t['track_id']==chosen),None)
        others = [t for t in record['tracks'] if t is not target]
        crop = speaking_face_crop(layout['source_size'],target,others) if target else None
        reason = record['decision']['reason'] if not target or crop else 'unsafe_single_person_crop'
        mode = 'active_speaker' if crop else 'preserve'
        shot = {'fa':record['fa'],'fb':record['fb'],'a':record['start'],'b':record['end'],
                'mode':'duo','flash':False,'editorial_rect':crop or full[:],
                'framing_mode':mode,'speaker_id':record['speaker_id']}
        shots.append(shot)
        evidence.append({**record,'mode':mode,'crop':shot['editorial_rect'],'reason':reason})
        if not crop:
            review.append({'start':record['start'],'end':record['end'],
                           'speaker_id':record['speaker_id'],'reason':reason})
    # Do not reuse the previous person's crop for short interjections. Any
    # unresolved range remains explicit and participates in overall QA.
    plan['shots'] = shots
    return {**{k:v for k,v in analysis.items() if k!='ranges'}, 'revision':REVISION,
            'ranges':evidence,'review_ranges':review,
            'note':'逐段音画关联；姓名、身份、历史位置不参与选脸。未确认则保留源画面并需复核。'}

