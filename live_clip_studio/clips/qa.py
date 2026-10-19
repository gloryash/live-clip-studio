from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from .contract import normalized
from .input import write_json
from .timeline import graphics


def check_probe(probe: dict, expected_duration: float) -> dict:
    video = next((s for s in probe["streams"] if s.get("codec_type") == "video"), None)
    audio = next((s for s in probe["streams"] if s.get("codec_type") == "audio"), None)
    if not video or video.get("width") != 1080 or video.get("height") != 1920 or video.get("codec_name") != "h264":
        raise ValueError("QA_VIDEO: expected 1080x1920 H264")
    rate = str(video.get("avg_frame_rate") or "0/1").split("/")
    fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0
    if abs(fps - 30) > .01:
        raise ValueError(f"QA_FPS: expected 30fps, got {fps}")
    if video.get("pix_fmt") not in (None, "yuv420p"):
        raise ValueError(f"QA_PIX_FMT: expected yuv420p, got {video.get('pix_fmt')}")
    if not audio or audio.get("codec_name") != "aac":
        raise ValueError("QA_AUDIO: expected AAC audio stream")
    vd, ad = float(video.get("duration", 0)), float(audio.get("duration", 0))
    if abs(vd - ad) > .1 or abs(vd - expected_duration) > .1:
        raise ValueError(f"QA_DURATION: planned={expected_duration}, video={vd}, audio={ad}")
    return {"status": "PASS", "video_seconds": vd, "audio_seconds": ad, "av_difference": round(abs(vd-ad), 5)}


def compare_speech(expected: str, heard_rows: list[dict], cuts: list[float]) -> dict:
    expected = normalized(graphics.CC.convert(expected))
    chars = [(c, float(r["start"])) for r in heard_rows for c in normalized(graphics.CC.convert(r["text"]))]
    heard = "".join(c for c, _ in chars)
    match = difflib.SequenceMatcher(None, expected, heard, autojunk=False)
    issues = []
    for op, a0, a1, b0, b1 in match.get_opcodes():
        if op == "equal":
            continue
        at = chars[min(b0, len(chars)-1)][1] if chars else 0.0
        near = min((abs(at-c) for c in cuts), default=999)
        issues.append({"op": op, "t": round(at, 3), "near_cut": round(near, 3),
                       "expected": expected[a0:a1], "heard": heard[b0:b1]})
    suspicious = [i for i in issues if i["op"] in ("delete", "replace") and len(i["expected"]) >= 3 and i["near_cut"] < .6]
    status = "REVIEW" if match.ratio() < .9 or suspicious else "PASS"
    return {"status": status, "ratio": round(match.ratio(), 4), "expected": expected, "heard": heard,
            "issues": issues, "suspicious_cut_issues": suspicious}


def transcribe_for_qa(wav: Path, evidence: Path, *, timeout_seconds: float = 600) -> dict:
    base = os.environ.get("LIVE_CLIP_WHISPER_URL", "http://127.0.0.1:8765").rstrip("/")
    with httpx.Client(timeout=120) as client:
        response = client.get(base + "/health", timeout=5)
        response.raise_for_status()
        health = response.json()
        if health.get("status") != "ok" or health.get("model") != "mlx-community/whisper-large-v3-turbo":
            raise ValueError("QA_WHISPER: local Large V3 Turbo service is not ready")
        with wav.open("rb") as audio:
            response = client.post(base + "/v1/transcriptions", files={"file": (wav.name, audio, "audio/wav")},
                                   data={"language": "zh", "auto_correct": "false"})
        response.raise_for_status()
        job = response.json()["job_id"]
        write_json(evidence.with_name(evidence.name + "-job.json"), {"job_id": job, "model": health["model"], "auto_correct": False})
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = client.get(base + f"/v1/jobs/{job}", timeout=15)
            response.raise_for_status()
            state = response.json()
            if state.get("status") == "failed":
                raise ValueError(f"QA_WHISPER_FAILED: {state.get('error')}")
            if state.get("status") == "succeeded":
                response = client.get(base + f"/v1/jobs/{job}/result", timeout=30)
                response.raise_for_status()
                result = response.json()
                write_json(evidence.with_name(evidence.name + "-transcript.json"), result)
                return result
            time.sleep(1)
    raise ValueError(f"QA_WHISPER_TIMEOUT: job {job}, deadline {timeout_seconds}s")


def framing_review_ranges(source_visual: dict) -> list[dict]:
    return (source_visual.get('framing', {}).get('review_ranges', [])
            + source_visual.get('editorial_framing', {}).get('review_ranges', []))


def qa_clip(path: Path, plan: dict, doc: dict, qa_dir: Path, *, speech: bool = True) -> dict:
    qa_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, timeout=30)
    probe = json.loads(result.stdout)
    technical = check_probe(probe, plan["duration"])
    with (qa_dir / f"{stem}-decode.log").open("w") as log:
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                       check=True, stdout=subprocess.DEVNULL, stderr=log, timeout=600)
    loud = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vn", "-af", "loudnorm=I=-15:TP=-1.5:LRA=8:print_format=json",
                           "-f", "null", "-"], capture_output=True, text=True, check=True, timeout=300)
    loudness = json.loads(loud.stderr[loud.stderr.rfind("{"):loud.stderr.rfind("}")+1])
    write_json(qa_dir / f"{stem}-loudness.json", loudness)
    if not -18 <= float(loudness["input_i"]) <= -12 or float(loudness["input_tp"]) > 0:
        raise ValueError(f"QA_LOUDNESS: {loudness['input_i']} LUFS, peak {loudness['input_tp']}dB")
    timestamps = sorted({.5, min(plan["duration"]-.1, next(p["out"] for p in plan["pieces"] if not p["cold"]) + 1),
                         plan["duration"]*.33, plan["duration"]*.66, plan["duration"]-2})
    sheet = Image.new("RGB", (270*len(timestamps), 510), "#222222")
    for k, at in enumerate(timestamps):
        frame = qa_dir / f"{stem}-frame-{k+1}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf", "scale=270:480", str(frame)],
                       check=True, timeout=60)
        with Image.open(frame) as image:
            sheet.paste(image, (270*k, 0))
        ImageDraw.Draw(sheet).text((270*k+10, 488), f"{at:.2f}s", fill="white")
    sheet.save(qa_dir / f"{stem}-contact.jpg", quality=85)
    report = {"id": stem, "technical": technical, "full_decode": "PASS", "loudness": loudness,
              "visual_review": "PENDING", "contact_sheet": f"{stem}-contact.jpg"}
    rendered = json.loads(path.with_name(stem + "-render.json").read_text()) if path.with_name(stem + "-render.json").is_file() else {}
    report["source_visual"] = rendered.get("source_visual", {})
    if speech:
        wav = qa_dir / f"{stem}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", str(wav)], check=True, timeout=60)
        heard = transcribe_for_qa(wav, qa_dir / stem)
        wav.unlink(missing_ok=True)
        heard_rows = []
        for row in heard.get("segments", []):
            words = row.get("words") or []
            if words:
                heard_rows.extend({"text": w.get("word") or w.get("text") or "", "start": w["start"]} for w in words)
            else:
                heard_rows.append({"text": row["text"], "start": row["start"]})
        turns = {r["id"]: r for r in doc["segments"]}
        expected = "".join(turns[i["tid"]]["text"] for i in plan["items"])
        report["speech"] = compare_speech(expected, heard_rows, [p["out"] for p in plan["pieces"][1:]])
        for issue in report["speech"]["issues"]:
            p = next((p for p in reversed(plan["pieces"]) if p["out"] <= issue["t"]), plan["pieces"][0])
            issue.update(source_time=round(p["source_start"]+issue["t"]-p["out"], 3), turn_ids=p["turns"])
    else:
        report["speech"] = {"status": "SKIPPED"}
    framing_review = framing_review_ranges(report["source_visual"])
    report["status"] = "PASS" if report["speech"]["status"] == "PASS" and not report["source_visual"].get("source_holds") and not framing_review else "REVIEW"
    write_json(qa_dir / f"{stem}-qa.json", report)
    return report
