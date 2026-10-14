"""为每条切片生成视频号封面（1080x1920，文字落在 3:4 安全区内）。

uv run --no-project --with opencc-python-reimplemented --with pillow --with jieba \
    python editing/cover_fb16_clips.py
"""
from __future__ import annotations

import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageStat

import render_fb16_clips as R


def main() -> None:
    spec = R.read_json(R.SPEC_PATH)
    fixes = sorted(spec["fixes"].items(), key=lambda kv: -len(kv[0]))
    tr = R.Transcript(R.ROOT / "data" / spec["job_id"])
    out_dir = R.ROOT / spec["output_dir"]
    source = R.ROOT / "data" / spec["job_id"] / "source.mp4"
    for clip in spec["clips"]:
        items = R.build_items(tr, clip, fixes)
        guest = [it for it in items if it.speaker == "G"]
        picks = [guest[round(k * (len(guest) - 1) / 15)] for k in range(16)]
        frame = out_dir / "_work" / clip["id"] / "cover-src.png"
        best = -1.0
        for k, it in enumerate(picks):
            cand = frame.with_name(f"cover-cand-{k}.png")
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{(it.s + it.e) / 2:.2f}",
                            "-i", str(source), "-frames:v", "1",
                            "-vf", "delogo=x=468:y=1239:w=114:h=92,crop=418:744:475:588,hqdn3d=1.5:1.5:3:3,"
                                   "scale=1080:1922:flags=lanczos,crop=1080:1920:0:0,unsharp=5:5:0.6", str(cand)], check=True)
            face = Image.open(cand).convert("L").crop((240, 200, 840, 1000))
            sharp = ImageStat.Stat(face.filter(ImageFilter.FIND_EDGES)).var[0]
            if sharp > best:
                best = sharp
                cand.replace(frame)
            else:
                cand.unlink()
        img = Image.open(frame).convert("RGBA")
        shade = Image.new("RGBA", img.size)
        d = ImageDraw.Draw(shade)
        for y in range(R.H):
            k = max(0.0, (y - 760) / (R.H - 760))
            d.line((0, y, R.W, y), fill=(0, 0, 0, int(215 * min(1.0, k * 1.5))))
        img.alpha_composite(shade)

        tag = R.panel([("AI与人类未来的8个真相", R.font(R.BOLD, 40), R.BLACK)], R.GOLD, None, padx=30, pady=10, radius=30)
        img.alpha_composite(tag, ((R.W - tag.width) // 2, 1010))
        hook = R.stack([R.text_img(line, R.fit(R.SMILEY, line, 150, 1000), R.WHITE if i == 0 else R.GOLD, stroke=12)
                        for i, line in enumerate(clip["hook"])], gap=-36)
        img.alpha_composite(hook, ((R.W - hook.width) // 2, 1110))
        sub = R.text_img("".join(clip["title"]), R.fit(R.HEAVY, "".join(clip["title"]), 52, 980), R.WHITE, stroke=5)
        img.alpha_composite(sub, ((R.W - sub.width) // 2, 1150 + hook.height - 40))
        names = R.text_img("尹一峰 × monica", R.font(R.BOLD, 36), (255, 255, 255, 220), stroke=3, shadow=False)
        img.alpha_composite(names, ((R.W - names.width) // 2, 1150 + hook.height + sub.height - 20))
        img.convert("RGB").save(out_dir / f"{clip['id']}-cover.jpg", quality=92)
        print("cover", clip["id"])


if __name__ == "__main__":
    main()
