"""成片反向转写质检：检查剪切点附近是否吃字。

uv run --no-project --with opencc-python-reimplemented --with pillow --with jieba \
    python editing/qa_fb16_whisper.py [clip_id ...]
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import render_fb16_clips as R


WHISPER = "http://127.0.0.1:8765"


def curl_json(*args: str) -> dict:
    return json.loads(subprocess.run(["curl", "-fsS", *args], check=True, capture_output=True, text=True).stdout)


def transcribe(wav: Path) -> dict:
    job = curl_json("-F", f"file=@{wav};type=audio/wav", "-F", "language=zh", "-F", "auto_correct=false",
                    f"{WHISPER}/v1/transcriptions")["job_id"]
    while True:
        status = curl_json(f"{WHISPER}/v1/jobs/{job}").get("status")
        if status == "succeeded":
            return curl_json(f"{WHISPER}/v1/jobs/{job}/result")
        if status == "failed":
            raise RuntimeError(f"whisper job {job} failed")
        time.sleep(1.0)


def norm(text: str) -> str:
    return re.sub(r"[^\w%]", "", R.CC.convert(text)).lower()


def main() -> None:
    spec = R.read_json(R.SPEC_PATH)
    out_dir = R.ROOT / spec["output_dir"]
    qa_dir = out_dir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    fixes = sorted(spec["fixes"].items(), key=lambda kv: -len(kv[0]))
    tr = R.Transcript(R.ROOT / "data" / spec["job_id"])
    wanted = set(sys.argv[1:])
    summary = {}
    for clip in spec["clips"]:
        if wanted and clip["id"] not in wanted:
            continue
        items = R.build_items(tr, clip, fixes)
        pieces = R.build_pieces(tr, items, set(clip.get("chapters", [])))
        cuts = [p.out0 for p in pieces[1:]]
        expected = "".join(norm(tr.turns[it.tid]["text"][it.c0:it.c1]) for it in items)
        wav = qa_dir / f"{clip['id']}.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(out_dir / f"{clip['id']}.mp4"),
                        "-ac", "1", "-ar", "16000", str(wav)], check=True)
        result = transcribe(wav)
        wav.unlink()
        chars: list[tuple[str, float]] = []
        for seg in result.get("segments", []):
            for word in seg.get("words") or []:
                token = norm(str(word.get("word") or word.get("text") or ""))
                for k, ch in enumerate(token):
                    chars.append((ch, float(word["start"])))
        heard = "".join(c for c, _ in chars)
        matcher = difflib.SequenceMatcher(None, expected, heard, autojunk=False)
        issues = []
        for op, a0, a1, b0, b1 in matcher.get_opcodes():
            if op == "equal":
                continue
            at = chars[min(b0, len(chars) - 1)][1] if chars else 0.0
            near = min((abs(at - c) for c in cuts), default=99.0)
            issues.append({"op": op, "t": round(at, 2), "near_cut": round(near, 2),
                           "expected": expected[a0:a1], "heard": heard[b0:b1]})
        summary[clip["id"]] = {"ratio": round(matcher.ratio(), 4), "issues": issues}
        print(f"== {clip['id']} similarity={matcher.ratio():.3f} diffs={len(issues)}")
        for issue in issues:
            flag = "CUT" if issue["near_cut"] < 0.6 else "   "
            print(f"  {flag} {issue['t']:7.2f}s (cut±{issue['near_cut']:.2f}) {issue['op']:7s} "
                  f"期望[{issue['expected']}] 听到[{issue['heard']}]")
    (qa_dir / "whisper-qa.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
