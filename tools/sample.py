#!/usr/bin/env python3
"""Emdalex Studio sample video: turns a video's folder from the iPhone into the package the app
downloads into an account's empty Videos (studio/sample/sample.json + files; iOS `SampleVideo`).

Make the video in the app (clips, cover, sound, Create Video), then copy the app's videos off the
phone connected by cable (any folder; the video's folder is the one whose project.json has the
right "name"):
  xcrun devicectl list devices
  xcrun devicectl device copy from --device <UDID> --domain-type appDataContainer \
      --domain-identifier com.emdalex.studio --source "Library/Application Support/Projects" \
      --destination ~/Desktop/Projects
The folder must hold assembled.mp4 made after the last change.

Usage (from the site repo root):  python3 tools/sample.py <video folder> [--keep]
By default the videos are made smaller with ffmpeg (brew install ffmpeg): each clip is cut to
the part the video uses and every video becomes HEVC (clips ~4 Mbit/s, the created video
~3.5 Mbit/s), same size and frame rate. --keep copies the files as they are.
Replaces studio/sample/ entirely. Only our own footage or CC0 / public domain (as the gallery).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "studio" / "sample"
SKIP = {"project.json", "assembled-new.mp4", ".DS_Store"}
SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_TOTAL = 60 * 1024 * 1024   # the app downloads it on any network: keep it small
VIDEO_EXT = {".mov", ".mp4", ".m4v"}
CLIP_BITRATE = "4M"
EXPORT_BITRATE = "3500k"


def safe_name(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem if dot else name).strip("-") or "file"
    return f"{stem}.{ext}" if dot else stem


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def encode(src: Path, dst: Path, bitrate: str, start: float = 0, end: float | None = None) -> None:
    """HEVC (hvc1, plays everywhere on Apple devices), audio AAC; frame-accurate cut."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src)]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-map", "0:v:0", "-map", "0:a?", "-c:v", "hevc_videotoolbox", "-b:v", bitrate,
            "-tag:v", "hvc1", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)


def compress(src: Path, project: dict, work: Path) -> dict[str, Path]:
    """Smaller copies of the clips (cut to what the video uses; keptRanges moved to match) and of
    the created video. Returns {relative path: file to publish instead of the original}."""
    replaced: dict[str, Path] = {}
    clips_by_file: dict[str, list[dict]] = {}
    for clip in project.get("clips", []):
        clips_by_file.setdefault(clip["fileName"], []).append(clip)
    for file_name, clips in clips_by_file.items():
        source = src / file_name
        if source.suffix.lower() not in VIDEO_EXT or not source.exists():
            continue
        whole = duration(source)
        # The part of the file any clip uses (a file shared by clips after Replace keeps all)
        spans = []
        for clip in clips:
            ranges = clip.get("keptRanges") or [{"start": 0, "end": whole}]
            spans += [(r["start"], r["end"]) for r in ranges]
        start = max(0.0, min(s for s, _ in spans))
        end = min(whole, max(e for _, e in spans))
        target = work / file_name
        encode(source, target, CLIP_BITRATE, start, end if end < whole - 0.05 else None)
        new_length = duration(target)
        for clip in clips:
            if start > 0 or clip.get("keptRanges"):
                ranges = clip.get("keptRanges") or [{"start": 0, "end": whole}]
                clip["keptRanges"] = [{"start": max(0, r["start"] - start),
                                       "end": min(new_length, r["end"] - start)} for r in ranges]
            clip["fileDuration"] = new_length
        replaced[file_name] = target
        print(f"  {file_name}: {source.stat().st_size / 1e6:.1f} → {target.stat().st_size / 1e6:.1f} MB")
    export = src / "assembled.mp4"
    target = work / "assembled.mp4"
    encode(export, target, EXPORT_BITRATE)
    replaced["assembled.mp4"] = target
    print(f"  assembled.mp4: {export.stat().st_size / 1e6:.1f} → {target.stat().st_size / 1e6:.1f} MB")
    return replaced


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = "--keep" in sys.argv[1:]
    if len(args) != 1:
        sys.exit(__doc__)
    src = Path(args[0]).expanduser().resolve()
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

    with tempfile.TemporaryDirectory() as tmp:
        replaced = {} if keep else compress(src, project, Path(tmp))
        files = []
        for path in sorted(p for p in src.rglob("*") if p.is_file() and p.name not in SKIP):
            rel = path.relative_to(src).as_posix()
            path = replaced.get(rel, path)
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
