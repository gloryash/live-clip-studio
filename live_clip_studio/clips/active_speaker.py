"""Source-local audio/visual association; no host/guest or location priors.

Scores are uncalibrated model logits, NOT identity probabilities. Each short
window is measured again so face positions never transfer between recordings.
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

REVISION = "av-speaker-v1-talkset"
FPS = 30
ANALYSIS_FPS = 25
WEIGHT_SHA = "efc375833887eefa9d209dc92810e18519b04c3c73ea35a549f2a7f40b7d94d5"
WEIGHT_URL = "https://raw.githubusercontent.com/Junhua-Liao/Light-ASD/ed38c232de5efe0261dbd68627c0ade7cdfe14eb/weight/finetuning_TalkSet.model"


def analysis_ranges(plan: dict) -> list[dict]:
    """Every audio-speaker change is a cut, including short interjections.

    Also split source edits and bounded analysis windows. Never infer identity
    across a jump cut, and do not let padding gaps create tiny fake turns.
    """
    spans = []
    for item in plan["items"]:
        sid = plan["source_speakers"].get(str(item["tid"]))
        if spans and spans[-1]["speaker_id"] == sid:
            spans[-1]["end"] = item["out_e"]
        else:
            spans.append({"start": item["out_s"], "end": item["out_e"], "speaker_id": sid})
    boundaries = {0, plan["total_frames"]}
    for a, b in zip(spans, spans[1:]):
        # At a source edit, padding belongs to that piece. Snap the audio gap
        # to the actual edit rather than adding a one-frame false speaker.
        edit = next((p["out"] for p in plan["pieces"] if a["end"] <= p["out"] <= b["start"]), None)
        boundaries.add(round((edit if edit is not None else (a["end"]+b["start"])/2)*FPS))
    boundaries.update(round(p["out"] * FPS) for p in plan["pieces"])
    edges = sorted(boundaries)
    result = []
    for a, b in zip(edges, edges[1:]):
        count = max(1, math.ceil((b - a) / (4 * FPS)))
        for k in range(count):
            fa, fb = a + round((b-a)*k/count), a + round((b-a)*(k+1)/count)
            mid = (fa+fb)/(2*FPS)
            sid = next((s["speaker_id"] for s in spans if mid < s["end"]), spans[-1]["speaker_id"] if spans else None)
            result.append({"fa": fa, "fb": fb, "speaker_id": sid})
    return result


def select_active_face(candidates: list[dict]) -> dict:
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    if not ranked:
        return {"track_id": None, "reason": "no_face"}
    best = ranked[0]
    margin = best["score"] - ranked[1]["score"] if len(ranked) > 1 else None
    reason = ("insufficient_face_coverage" if best["coverage"] < .65 else
              "no_audible_face" if best["score"] < .8 else
              "ambiguous_activity" if margin is not None and margin < 1.0 else "audio_visual_match")
    return {"track_id": best["track_id"] if reason == "audio_visual_match" else None,
            "reason": reason, "score": round(best["score"], 4),
            "margin": round(margin, 4) if margin is not None else None}


def overlap(a, b):
    x = max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]))
    y = max(0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))
    inter = x*y
    return inter / max(1, a[2]*a[3]+b[2]*b[3]-inter)


def detect_tracks(frames: list[np.ndarray]) -> list[dict]:
    """Full-resolution detections retain tiny PiP faces; deduplicate Haar hits.

    Tracks are local spatial tracks for a <=4s window, not person identities.
    A disappearing/moving subject reduces coverage instead of reusing a crop.
    """
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    sample_indices = sorted(set([0, len(frames)-1, *range(6, len(frames), 12)]))
    tracks = []
    for index in sample_indices:
        boxes = detector.detectMultiScale(frames[index], 1.05, 5, minSize=(24,24))
        unique = []
        for box in sorted(boxes, key=lambda b: int(b[2])*int(b[3]), reverse=True):
            box = list(map(int, box))
            if not any(overlap(box, old) > .35 for old in unique):
                unique.append(box)
        used = set()
        for box in unique:
            matches = [(overlap(box,t["observations"][-1][1]), k) for k,t in enumerate(tracks) if k not in used]
            score, k = max(matches, default=(0, -1))
            if score < .25:
                k = len(tracks)
                tracks.append({"track_id": f"face-{k}", "observations": []})
            tracks[k]["observations"].append((index,box)); used.add(k)
    for track in tracks:
        track["coverage"] = len(track["observations"]) / len(sample_indices)
    return tracks


def face_video(frames, track):
    indices, boxes = zip(*track["observations"])
    coordinates = np.array(boxes)
    # Smooth/interpolate local detections; the original model's padded face
    # crop and central 112x112 preprocessing must stay geometrically identical.
    interpolated = np.array([np.interp(np.arange(len(frames)), indices, coordinates[:,k]) for k in range(4)]).T
    output = []
    for frame, (x,y,w,h) in zip(frames,interpolated):
        cx, cy, half = x+w/2, y+h/2, max(w,h)/2
        pad = math.ceil(half*1.8)
        padded = np.pad(frame,pad,constant_values=110)
        crop = padded[int(cy+pad-half):int(cy+pad+half*1.8), int(cx+pad-half*1.4):int(cx+pad+half*1.4)]
        output.append(cv2.resize(crop,(224,224))[56:168,56:168])
    return np.array(output)


class ActivityModel:
    def __init__(self):
        import torch
        from ._light_asd.model import ASD_Model
        path = Path(os.environ.get("LIVE_CLIP_ASD_WEIGHTS", str(Path.home()/".cache/live-clip-studio/light-asd-talkset.model")))
        if not path.is_file():
            import httpx
            path.parent.mkdir(parents=True,exist_ok=True)
            response = httpx.get(WEIGHT_URL,follow_redirects=True,timeout=60)
            response.raise_for_status()
            if hashlib.sha256(response.content).hexdigest() != WEIGHT_SHA:
                raise ValueError("ASD_WEIGHTS: download checksum mismatch")
            import tempfile
            with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
                f.write(response.content); temporary=Path(f.name)
            temporary.replace(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != WEIGHT_SHA:
            raise ValueError("ASD_WEIGHTS: checksum mismatch")
        # CPU works on Intel and Apple Silicon. Keep model loading lazy so the
        # transcript/web application does not require torch at import time.
        torch.set_num_threads(min(4, torch.get_num_threads()))
        self.model = ASD_Model().eval()
        self.fc = torch.nn.Linear(128,2).eval()
        weights = torch.load(path,map_location="cpu",weights_only=True)
        self.model.load_state_dict({k[6:]:v for k,v in weights.items() if k.startswith("model.")})
        self.fc.load_state_dict({k[10:]:v for k,v in weights.items() if k.startswith("lossAV.FC.")})

    def score(self, audio, video):
        import torch
        from python_speech_features import mfcc
        features = mfcc(audio,16000,numcep=13,winlen=.025,winstep=.01)
        n = min(len(video),len(features)//4)
        if n < 5:
            return -10.0
        scores = []
        with torch.inference_mode():
            # Ensemble temporal context, following official demo preprocessing.
            for size in (25,50,100):
                parts = []
                for offset in range(0,n,size):
                    count = min(size,n-offset)
                    if count < 5: continue
                    a = torch.tensor(features[offset*4:(offset+count)*4],dtype=torch.float32)[None]
                    v = torch.tensor(video[offset:offset+count],dtype=torch.float32)[None]
                    output = self.model.forward_audio_visual_backend(self.model.forward_audio_frontend(a),self.model.forward_visual_frontend(v))
                    parts.append(self.fc(output)[:,1].numpy())
                scores.append(float(np.concatenate(parts).mean()))
        return float(np.mean(scores))


def analyze_window(cut: Path, window: dict, size: list[int], model: ActivityModel) -> dict:
    start, duration = window["fa"]/FPS, (window["fb"]-window["fa"])/FPS
    width,height = size
    raw = subprocess.run(["ffmpeg","-v","error","-ss",str(start),"-i",str(cut),"-t",str(duration),
                          "-an","-vf",f"fps={ANALYSIS_FPS},format=gray","-f","rawvideo","-threads","1","-"],
                         check=True,capture_output=True,timeout=90).stdout
    stride = width*height
    if len(raw)%stride or not raw:
        raise ValueError("ASD_FRAMES: incomplete video window")
    frames = list(np.frombuffer(raw,np.uint8).reshape(-1,height,width))
    tracks = detect_tracks(frames)
    audio_raw = subprocess.run(["ffmpeg","-v","error","-ss",str(start),"-i",str(cut),"-t",str(duration),
                                "-vn","-ar","16000","-ac","1","-f","s16le","-"],
                               check=True,capture_output=True,timeout=60).stdout
    audio = np.frombuffer(audio_raw,dtype="<i2")
    for track in tracks:
        track["score"] = model.score(audio,face_video(frames,track)) if track["coverage"] >= .5 else -10.0
    decision = select_active_face(tracks)
    if not window.get("speaker_id") or window["speaker_id"] == "UNKNOWN":
        decision = {"track_id":None,"reason":"unknown_audio_speaker"}
    if duration < .4:
        decision = {"track_id":None,"reason":"short_audio_evidence"}
    return {**window,"start":start,"end":start+duration,"decision":decision,"tracks":tracks}


def analyze_cut(cut: Path, plan: dict, size: list[int]) -> dict:
    began = time.monotonic()
    windows = analysis_ranges(plan)
    try:
        model = ActivityModel()
        # Verify all inference dependencies before processing a long recording.
        import python_speech_features  # noqa: F401
    except (ImportError, OSError, ValueError) as exc:
        return {"revision":REVISION,"ranges":[{**w,"start":w["fa"]/FPS,"end":w["fb"]/FPS,
                 "decision":{"track_id":None,"reason":"activity_model_unavailable"},"tracks":[]} for w in windows],
                "error":str(exc),"elapsed_seconds":round(time.monotonic()-began,3)}
    records = []
    for k, window in enumerate(windows):
        print(f"[speaker-framing] {k+1}/{len(windows)} {window['fa']/FPS:.2f}s {window['speaker_id']}",flush=True)
        records.append(analyze_window(cut,window,size,model))
    return {"revision":REVISION,"ranges":records,"elapsed_seconds":round(time.monotonic()-began,3),
            "score_note":"Light-ASD TalkSet logits; score/margin are evidence thresholds, not calibrated probabilities."}
