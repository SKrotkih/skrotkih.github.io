#!/usr/bin/env python3
"""Emdalex Studio sample video: turns a video's folder from the iPhone into the package the app
downloads into an account's empty Videos (studio/sample/sample.json + files; iOS `SampleVideo`).

Make the video in the app (clips, cover, sound, Create Video), then take its folder off the phone:
Xcode → Window → Devices and Simulators → the iPhone → Emdalex Studio → ⋯ → Download Container →
Show Package Contents → AppData/Library/Application Support/Projects/<video id>/ (the one whose
project.json has the right "name"). The folder must hold assembled.mp4 made after the last change.

Usage (from the site repo root):  python3 tools/sample.py <video folder>
Replaces studio/sample/ entirely. Only our own footage or CC0 / public domain (as the gallery).
"""
import json
import re
import shutil
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "studio" / "sample"
SKIP = {"project.json", "assembled-new.mp4", ".DS_Store"}
SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_TOTAL = 60 * 1024 * 1024   # the app downloads it on any network: keep it small


def safe_name(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem if dot else name).strip("-") or "file"
    return f"{stem}.{ext}" if dot else stem


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1]).expanduser().resolve()
    project = json.loads((src / "project.json").read_text())
    if not (src / "assembled.mp4").exists():
        sys.exit("No assembled.mp4: tap Create Video in the app first.")

    # This phone's own fields: the app sets the owner, YouTube uploads and streams stay behind
    for key in ("owner", "youTube", "scheduledStreams", "scheduledStream"):
        project.pop(key, None)

    # Sound files may carry the picked file's name: URL-safe names, project.json follows
    renames = {}
    sound = project.get("sound") or {}
    tracks = ([sound["music"]] if sound.get("music") else []) + sound.get("voices", [])
    for track in tracks:
        old = track["fileName"]
        if not SAFE.match(old):
            new = safe_name(old)
            renames[f"Sound/{old}"] = f"Sound/{new}"
            track["fileName"] = new

    files = []
    for path in sorted(p for p in src.rglob("*") if p.is_file() and p.name not in SKIP):
        rel = path.relative_to(src).as_posix()
        rel = renames.get(rel, rel)
        if not all(SAFE.match(part) for part in rel.split("/")):
            sys.exit(f"Not a URL-safe path: {rel}")
        files.append((path, rel))

    total = sum(p.stat().st_size for p, _ in files)
    if total > MAX_TOTAL:
        sys.exit(f"{total / 1e6:.1f} MB is too big (limit {MAX_TOTAL / 1e6:.0f} MB): shorter clips or 720p.")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for path, rel in files:
        target = OUT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    manifest = {
        "version": 1,
        "project": project,
        "files": [{"path": rel, "bytes": path.stat().st_size} for path, rel in files],
    }
    (OUT / "sample.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(f"studio/sample/: \"{project['name']}\", {len(project.get('clips', []))} clips, "
          f"{len(files)} files, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
