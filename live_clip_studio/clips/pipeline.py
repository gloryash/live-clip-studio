from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from .contract import DECISION_SCHEMA, decision_schema, validate_decisions
from .input import compact_rows, export_job, read_json, validate_transcript, write_json
from .model import MODEL, ModelClient, load_api_key
from .qa import qa_clip
from .render import render_clip
from .selection import select_clips
from .timeline import make_plan, validate_layout
from .visual import RENDER_REVISION


def fingerprint(*values) -> str:
    cleaned = [{k: v for k, v in value.items() if k != "generated_at"} if isinstance(value, dict) else value for value in values]
    return hashlib.sha256(json.dumps(cleaned, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunState:
    def __init__(self, out: Path, input_hash: str):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.run_id = f"run-{int(time.time()*1000)}"
        self.value = {"version": 1, "run_id": self.run_id, "input_hash": input_hash, "status": "running", "stages": {}}
        self.save()

    def safe(self, value):
        key = os.environ.get("LIVE_CLIP_API_KEY")
        return value.replace(key, "<redacted>") if key else value

    def save(self):
        write_json(self.out / "run.json", self.value)

    def event(self, stage: str, status: str, **extra):
        value = {"time": time.time(), "run_id": self.run_id, "input_hash": self.value.get("input_hash"), "stage": stage, "status": status, **extra}
        with (self.out / "events.jsonl").open("a", encoding="utf-8") as log:
            log.write(self.safe(json.dumps(value, ensure_ascii=False)) + "\n")

    @contextmanager
    def stage(self, name: str):
        started = time.monotonic()
        self.value["stages"][name] = {"status": "running", "started_at": time.time()}
        self.save()
        self.event(name, "running")
        print(f"[{name}] start", flush=True)
        try:
            yield
        except BaseException as exc:
            error = self.safe(str(exc))
            self.value.update(status="failed", failed_stage=name, error=error)
            self.value["stages"][name].update(status="failed", error=error, elapsed_seconds=round(time.monotonic()-started, 3))
            self.save()
            self.event(name, "failed", error=error)
            raise
        else:
            self.value["stages"][name].update(status="completed", elapsed_seconds=round(time.monotonic()-started, 3))
            self.save()
            self.event(name, "completed")


def publish_document(decisions: dict, plans: list[dict], out: Path) -> None:
    byid = {p["id"]: p for p in plans}
    lines = ["# 访谈切片发布稿", "", "按以下顺序人工审核。手机完整播放确认原意、人物、字幕后再发布。未自动发布。", ""]
    for clip in decisions["clips"]:
        lines += [f"## {clip['id']} · {''.join(clip['title'])}", "", f"时长：{byid[clip['id']]['duration']:.1f}秒",
                  f"正文：{''.join(clip['hook'])} {''.join(clip['cta'])}", "话题：#访谈 #观点分享",
                  f"视频：{clip['id']}.mp4；封面：{clip['id']}-cover.jpg；字幕：{clip['id']}.srt", ""]
    (out / "publish.md").write_text("\n".join(lines), encoding="utf-8")


def execute(args) -> dict:
    out = Path(args.out).resolve()
    previous = read_json(out / "run.json", {})
    state = RunState(out, "pending")
    with state.stage("preflight"):
        source = Path(args.source).resolve() if args.source else Path(args.job_dir).resolve() / "source.mp4"
        if not source.is_file():
            raise ValueError("SOURCE_MISSING: " + str(source))
        doc = read_json(Path(args.transcript)) if args.transcript else export_job(Path(args.job_dir))
        report = validate_transcript(doc)
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)],
                                          check=True, capture_output=True, text=True, timeout=30).stdout)
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        if not any(s["codec_type"] == "audio" for s in probe["streams"]):
            raise ValueError("SOURCE_AUDIO: no audio stream")
        if abs(float(probe["format"]["duration"]) - doc["job"]["duration_seconds"]) > .25:
            raise ValueError("SOURCE_TIME: transcript and source duration differ")
        layout = read_json(Path(args.layout))
        validate_layout(layout, video["width"], video["height"])
        template_id = layout.get("template_id", "general")
        schema = decision_schema(template_id)
        source_info = {"path": str(source), "size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns,
                       "sha256": file_digest(source)}
        input_hash = fingerprint(doc, layout, source_info, {"count": args.count, "banned": args.ban})
        state.value["input_hash"] = input_hash
        state.value["source"] = source_info
        state.save()
        write_json(out / "input.json", doc)
        write_json(out / "layout.json", layout)
        write_json(out / "input-report.json", {**report, "probe": probe, "input_hash": input_hash})
        write_json(out / "decision.schema.json", schema)
        (out / "transcript.txt").write_text(compact_rows(doc["segments"]), encoding="utf-8")
    if args.command == "prepare":
        state.value.update(status="prepared")
        state.save()
        return state.value
    with state.stage("select"):
        if args.decisions:
            decisions = read_json(Path(args.decisions))
        elif previous.get("input_hash") == input_hash and (out / "decisions.json").exists() and not args.fresh:
            decisions = read_json(out / "decisions.json")
            state.event("select", "cached")
        elif args.command in ("render", "qa", "plan"):
            raise ValueError("DECISIONS_REQUIRED: no matching cached decisions; pass --decisions or run selection")
        else:
            model = ModelClient(load_api_key())
            try:
                decisions = select_clips(model, doc, args.count, out / "ai", banned_terms=tuple(args.ban), template_id=template_id)
            finally:
                model.close()
        report = validate_decisions(decisions, doc, banned_terms=tuple(args.ban), template_id=template_id)
        write_json(out / "validation.json", report)
        write_json(out / "decisions.json", decisions)
    with state.stage("plan"):
        from .active_speaker import REVISION as SPEAKER_FRAMING_REVISION
        render_hash = fingerprint(input_hash, decisions, {"renderer": SPEAKER_FRAMING_REVISION if template_id == "editorial" else RENDER_REVISION})
        plans = [make_plan(clip, doc, layout) for clip in decisions["clips"]]
        for plan in plans:
            maximum = 300 if template_id == "editorial" else 180
            if not 60 <= plan["duration"] <= maximum:
                raise ValueError(f"RENDER_DURATION: {plan['id']} {plan['duration']:.2f}s")
            cache = read_json(out / (plan["id"] + "-render.json"), {})
            if cache.get("render_hash") == render_hash and cache.get("resolved_shots"):
                plan["shots"] = cache["resolved_shots"]
                plan["source_visual"] = cache.get("source_visual", {})
            write_json(out / "plans" / (plan["id"] + ".json"), plan)
        publish_document(decisions, plans, out)
        state.value["render_hash"] = render_hash
    if args.command in ("select", "plan"):
        state.value.update(status="planned")
        state.save()
        return state.value
    if args.command != "qa":
        with state.stage("render"):
            for clip, plan in zip(decisions["clips"], plans):
                cache = read_json(out / (clip["id"] + "-render.json"), {})
                artifacts = [out / (clip["id"] + suffix) for suffix in (".mp4", ".srt", "-cover.jpg")]
                if cache.get("render_hash") == render_hash and all(p.is_file() for p in artifacts) and not args.fresh:
                    state.event("render", "cached", clip=clip["id"])
                    continue
                print(f"[render] {clip['id']} {plan['duration']:.1f}s", flush=True)
                report = render_clip(source, clip, plan, layout, out)
                report["render_hash"] = render_hash
                write_json(out / (clip["id"] + "-render.json"), report)
    if args.command == "render":
        state.value.update(status="rendered_qa_pending")
        state.save()
        return state.value
    with state.stage("qa"):
        reports = []
        for plan in plans:
            cache = read_json(out / (plan["id"] + "-render.json"), {})
            if cache.get("render_hash") != render_hash:
                raise ValueError("QA_STALE_RENDER: render differs from current input/decisions")
            print(f"[qa] {plan['id']}", flush=True)
            reports.append(qa_clip(out / (plan["id"] + ".mp4"), plan, doc, out / "qa", speech=not args.skip_speech))
        write_json(out / "qa/summary.json", {"clips": reports})
    state.value.update(status="completed_pending_human_review" if all(r["status"] == "PASS" for r in reports) else "needs_review")
    state.save()
    return state.value


def main():
    parser = argparse.ArgumentParser(description="固定模板访谈切片：AI仅填配置，后端校验/剪切/渲染/质检")
    parser.add_argument("command", choices=["prepare", "select", "plan", "render", "qa", "run"])
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--job-dir", help="现有已标注任务目录")
    inputs.add_argument("--transcript", help="AI精准字幕JSON；必须配--source")
    parser.add_argument("--source")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--decisions", help="人工审核/修改的JSON；不调用AI")
    parser.add_argument("--fresh", action="store_true", help="不复用当前阶段缓存")
    parser.add_argument("--skip-speech", action="store_true", help="仅技术质检，结果标记REVIEW")
    parser.add_argument("--ban", action="append", default=[], help="额外禁止出现的词，可重复")
    args = parser.parse_args()
    if not 1 <= args.count <= 30:
        parser.error("count must be 1–30")
    if args.transcript and not args.source:
        parser.error("--transcript requires --source")
    try:
        result = execute(args)
    except (Exception, KeyboardInterrupt) as exc:
        message = str(exc)
        key = os.environ.get("LIVE_CLIP_API_KEY")
        if key:
            message = message.replace(key, "<redacted>")
        print(f"ERROR: {message}\nSee {Path(args.out).resolve() / 'run.json'} and events.jsonl", flush=True)
        raise SystemExit(1) from None
    print(f"Result: {result['status']} → {Path(args.out).resolve()}", flush=True)
    if result["status"] == "needs_review":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
