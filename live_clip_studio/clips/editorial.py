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
    draw.rectangle((0, 0, 1080, 509), fill=(2, 9, 6, 255))
    draw.rectangle((0, 1470, 1080, 1920), fill=(2, 9, 6, 255))
    # Original deterministic texture; no reference creator's logo is copied.
    for y in list(range(0, 510, 18)) + list(range(1490, 1920, 18)):
        for x in range(10, 1080, 18):
            strength = max(0, math.sin(x / 180 + y / 110))
            draw.ellipse((x, y, x+2, y+2), fill=(10, int(20+strength*22), 21, 255))
    draw.text((65, -100), '“', font=graphics.font(graphics.HEAVY, 430), fill=(10, 49, 28, 255))
    return image


def highlighted_line(line: str, words: list[str], size: int) -> Image.Image:
    font = graphics.fit(graphics.BOLD, line, size, 970)
    image = Image.new('RGBA', (1000, 125))
    draw = ImageDraw.Draw(image)
    x = (1000-font.getlength(line))/2
    highlighted = set()
    for word in words:
        for match in re.finditer(re.escape(word), line):
            highlighted.update(range(match.start(), match.end()))
    for i, char in enumerate(line):
        draw.text((x, 10), char, font=font, fill=GREEN if i in highlighted else WHITE)
        x += font.getlength(char)
    return image


def build_elements(clip: dict, plan: dict, options: dict) -> list:
    duration = plan['duration']
    elements = []
    for i, line in enumerate(clip['title']):
        elements.append(graphics.El(highlighted_line(line, clip.get('title_highlights', []), 86),
                                    540, 300+i*105, 0, duration, z=1))
    for text, y, size, color in ((options.get('series',''),1515,38,GREEN),
                                (options.get('brand',''),1610,52,WHITE)):
        if text:
            image = graphics.text_img(text, graphics.fit(graphics.BOLD,text,size,980),color,stroke=0,shadow=False)
            elements.append(graphics.El(image,540,y,0,duration,z=1))
    # All words remain white, including gold-marked sentences; no pop/punch.
    for cue in plan['cues']:
        image = graphics.text_img(cue['text'],graphics.fit(graphics.BOLD,cue['text'],44,980),WHITE,stroke=2)
        elements.append(graphics.El(image,540,1405,cue['start'],cue['end'],z=3))
    people = {p['speaker_id']: p for p in options.get('participants',[])}
    # One stable label per uninterrupted speaker run. Place outside the picture
    # so wrong/no camera switch cannot imply that a visible face was identified.
    spans = []
    for item in plan['items']:
        sid = plan.get('source_speakers',{}).get(str(item['tid']))
        if spans and spans[-1]['sid'] == sid:
            spans[-1]['end'] = item['out_e']
        else:
            spans.append({'sid':sid,'start':item['out_s'],'end':item['out_e']})
    for span in spans:
        person=people.get(span['sid'])
        if not person: continue
        for text,y,size,color in ((f"发言：{person['name']}",1715,38,GREEN),
                                  (person['identity'],1770,30,WHITE)):
            if text:
                image=graphics.text_img(text,graphics.fit(graphics.BOLD,text,size,980),color,stroke=0,shadow=False)
                elements.append(graphics.El(image,540,y,span['start'],span['end'],z=2))
    for uid, element in enumerate(elements): element.uid=uid
    return sorted(elements,key=lambda e:e.z)


def shot_filter(index: int, shot: dict, layout: dict) -> str:
    x,y,w,h=shot.get('scene_rect',layout['scene'])
    # Contain the entire source scene. Two people remain side by side.
    return (f"[s{index}]trim=start_frame={shot['fa']}:end_frame={shot['fb']},setpts=PTS-STARTPTS,"
            f"crop={w}:{h}:{x}:{y},scale=1080:960:force_original_aspect_ratio=decrease,"
            f"pad=1080:960:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
            f"pad=1080:1920:0:510:color=black[o{index}]")
