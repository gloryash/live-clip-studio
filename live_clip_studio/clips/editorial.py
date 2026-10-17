"""A restrained interview package learned from three supplied finished videos.

The source camera/edit remains intact in one window; identity text is explicitly
entered by the user and refers to the audible speaker, not a detected face.
"""
from __future__ import annotations

import math
import re
from PIL import Image, ImageDraw
from .timeline import graphics

WINDOW = (0, 510, 1080, 960)
GREEN = (99, 208, 150, 255)
WHITE = (245, 248, 246, 255)


def background() -> Image.Image:
    image = Image.new("RGBA", (1080, 1920))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1080, 509), fill=(0, 3, 1, 255))
    draw.rectangle((0, 1470, 1080, 1920), fill=(0, 3, 1, 255))
    # Sparse radial green halftone, strongest behind the quote and lower right.
    for y in list(range(0, 510, 18)) + list(range(1490, 1920, 18)):
        for x in range(8, 1080, 18):
            distance = math.hypot((x-160)/1.1, y-80) if y<510 else math.hypot(x-880,y-1810)
            wave=(math.sin(distance/42)+1)/2
            strength=max(0,1-distance/850)*(.25+.75*wave)
            radius=1+strength*2
            draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=(5,int(10+strength*44),19,255))
    quote=graphics.text_img('“',graphics.font(graphics.HEAVY,600),(6,40,17,255),stroke=0,shadow=False)
    quote=quote.crop(quote.getbbox()).resize((430,330))
    image.alpha_composite(quote,(75,-25))
    draw.line((65,1560,1015,1560),fill=(25,52,34,150),width=1)
    return image


def highlighted_line(line: str, words: list[str], size: int) -> Image.Image:
    font = graphics.font(graphics.BOLD,size)
    image = Image.new('RGBA', (1000, 115))
    draw = ImageDraw.Draw(image)
    x = 0
    baseline_offset = -font.getbbox(line)[1]
    highlighted = set()
    for word in words:
        for match in re.finditer(re.escape(word), line):
            highlighted.update(range(match.start(), match.end()))
    for i, char in enumerate(line):
        draw.text((x,baseline_offset),char,font=font,fill=GREEN if i in highlighted else WHITE)
        x += font.getlength(char)
    return image


def identity_card(person):
    image=Image.new('RGBA',(260,150)); draw=ImageDraw.Draw(image)
    draw.line((0,2,0,126),fill=GREEN,width=3)
    draw.text((16,0),'发言',font=graphics.font(graphics.BOLD,20),fill=WHITE,anchor='lt',stroke_width=1,stroke_fill=(0,0,0,150))
    draw.text((16,28),person['name'],font=graphics.fit(graphics.BOLD,person['name'],36,240),fill=WHITE,anchor='lt',stroke_width=1,stroke_fill=(0,0,0,150))
    text=person.get('identity','')
    lines=graphics.split_cue(text,graphics.font(graphics.BOLD,23),230) if text else []
    for i,line in enumerate(lines[:3]):
        draw.text((16,77+i*28),line,font=graphics.font(graphics.BOLD,23),fill=WHITE,anchor='lt',stroke_width=1,stroke_fill=(0,0,0,150))
    return image

def build_elements(clip: dict, plan: dict, options: dict) -> list:
    duration = plan['duration']
    elements = []
    size=min(graphics.fit(graphics.BOLD,line,92,920).size for line in clip['title'])
    for i, line in enumerate(clip['title']):
        elements.append(graphics.El(highlighted_line(line, clip.get('title_highlights', []), size),
                                    590, 300+i*105, 0, duration, z=1))
    for text, y, size, color in ((options.get('series',''),1515,38,GREEN),
                                (options.get('brand',''),1610,52,WHITE)):
        if text:
            image = graphics.text_img(text, graphics.fit(graphics.BOLD,text,size,980),color,stroke=0,shadow=False)
            elements.append(graphics.El(image,540,y,0,duration,z=1))
    # All words remain white, including gold-marked sentences; no pop/punch.
    for cue in plan['cues']:
        image = graphics.text_img(cue['text'],graphics.fit(graphics.BOLD,cue['text'],40,950),WHITE,stroke=1,shadow=False)
        elements.append(graphics.El(image,540,1405,cue['start'],cue['end'],z=3))
    people = {p['speaker_id']: p for p in options.get('participants',[])}
    # A stable voice label beside the picture, not a face-recognition claim.
    spans = []
    for item in plan['items']:
        sid = plan.get('source_speakers',{}).get(str(item['tid']))
        if spans and spans[-1]['sid'] == sid:
            spans[-1]['end'] = item['out_e']
        else:
            spans.append({'sid':sid,'start':item['out_s'],'end':item['out_e']})
    for span in spans:
        person=people.get(span['sid'])
        if not person or not person.get('name') or span['end']-span['start']<1.8: continue
        for shot in plan['shots']:
            start,end=max(span['start'],shot['a']),min(span['end'],shot['b'])
            if end<=start: continue
            # Keep the label off faces when an unconfirmed split view is retained.
            y=1260 if shot.get('framing_mode')=='preserve' else 1020
            elements.append(graphics.El(identity_card(person),210,y,start,end,z=2))
    for uid, element in enumerate(elements): element.uid=uid
    return sorted(elements,key=lambda e:e.z)


def shot_filter(index: int, shot: dict, layout: dict) -> str:
    x,y,w,h=shot.get('editorial_rect',shot.get('scene_rect',layout['scene']))
    # Foreground is always contained; soft source extensions fill any side gaps.
    return (f"[s{index}]trim=start_frame={shot['fa']}:end_frame={shot['fb']},setpts=PTS-STARTPTS,"
            f"crop={w}:{h}:{x}:{y},split=2[eb{index}][ef{index}];"
            f"[eb{index}]scale=135:120:force_original_aspect_ratio=increase,crop=135:120,"
            f"boxblur=12:2,scale=1080:960,eq=brightness=-0.06[eback{index}];"
            f"[ef{index}]scale=1080:960:force_original_aspect_ratio=decrease,setsar=1[efront{index}];"
            f"[eback{index}][efront{index}]overlay=(W-w)/2:(H-h)/2,"
            f"pad=1080:1920:0:510:color=black[o{index}]")
