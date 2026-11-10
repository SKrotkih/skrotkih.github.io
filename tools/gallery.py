#!/usr/bin/env python3
"""Emdalex Gallery: rebuilds studio/gallery/gallery.json (read by the apps) and the credits page
studio/gallery/index.html from the files in studio/gallery/. macOS only (uses sips and afinfo).

Layout:
  studio/gallery/images/<category>/<file>.jpg|jpeg|png   pictures (made <= 2560 px, JPEG)
  studio/gallery/images/<category>/thumbs/<file>.jpg     previews, 480 px wide (made by this script)
  studio/gallery/music/<category>/<file>.mp3|m4a         songs
  <category>/_category.json   optional: {"title": "Toy Cars", "order": 3}
  <category>/credits.json     required for every file: {"<file>": {"title": "...", "author": "...",
                              "license": "CC0", "source": "https://..."}}

Only free content: license must be one of ALLOWED_LICENSES (CC0, public domain or our own work).
Usage (from the site repo root):  python3 tools/gallery.py
"""
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "studio" / "gallery"
ALLOWED_LICENSES = {"CC0", "Public Domain", "Emdalex"}
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
MUSIC_EXT = {".mp3", ".m4a"}
MAX_SIDE = 2560
THUMB_WIDTH = 480

errors = []


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def image_size(path):
    out = run("sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path))
    w = int(re.search(r"pixelWidth: (\d+)", out).group(1))
    h = int(re.search(r"pixelHeight: (\d+)", out).group(1))
    return w, h


def audio_duration(path):
    out = run("afinfo", str(path))
    m = re.search(r"estimated duration: ([\d.]+)", out)
    return round(float(m.group(1)), 1) if m else None


def category_meta(folder):
    meta = {"title": folder.name.replace("-", " ").replace("_", " ").title(), "order": 100}
    f = folder / "_category.json"
    if f.exists():
        meta.update(json.loads(f.read_text()))
    return meta


def credits(folder):
    f = folder / "credits.json"
    return json.loads(f.read_text()) if f.exists() else {}


def entry_meta(folder, file, info):
    meta = info.get(file.name)
    if not meta:
        errors.append(f"{file.relative_to(ROOT)}: no entry in credits.json")
        return None
    if meta.get("license") not in ALLOWED_LICENSES:
        errors.append(f"{file.relative_to(ROOT)}: license {meta.get('license')!r} is not one of {sorted(ALLOWED_LICENSES)}")
        return None
    return meta


def build_images(folder):
    info = credits(folder)
    thumbs = folder / "thumbs"
    thumbs.mkdir(exist_ok=True)
    items = []
    for file in sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT):
        meta = entry_meta(folder, file, info)
        if meta is None:
            continue
        w, h = image_size(file)
        if max(w, h) > MAX_SIDE:
            run("sips", "-Z", str(MAX_SIDE), str(file))
            w, h = image_size(file)
        thumb = thumbs / (file.stem + ".jpg")
        if not thumb.exists() or thumb.stat().st_mtime < file.stat().st_mtime:
            run("sips", "-s", "format", "jpeg", "-s", "formatOptions", "75",
                "--resampleWidth", str(THUMB_WIDTH), str(file), "--out", str(thumb))
        rel = file.relative_to(ROOT).as_posix()
        items.append({"id": f"{folder.name}/{file.stem}", "title": meta.get("title") or file.stem,
                      "file": rel, "thumb": thumb.relative_to(ROOT).as_posix(), "width": w, "height": h,
                      "author": meta.get("author"), "license": meta["license"], "source": meta.get("source")})
    return items


def build_music(folder):
    info = credits(folder)
    items = []
    for file in sorted(p for p in folder.iterdir() if p.suffix.lower() in MUSIC_EXT):
        meta = entry_meta(folder, file, info)
        if meta is None:
            continue
        items.append({"id": f"{folder.name}/{file.stem}", "title": meta.get("title") or file.stem,
                      "file": file.relative_to(ROOT).as_posix(), "duration": audio_duration(file),
                      "author": meta.get("author"), "license": meta["license"], "source": meta.get("source")})
    return items


def build(kind, builder):
    base = ROOT / kind
    if not base.exists():
        return []
    cats = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        meta = category_meta(folder)
        items = builder(folder)
        if items:
            cats.append((meta["order"], {"id": folder.name, "title": meta["title"], "items": items}))
    return [c for _, c in sorted(cats, key=lambda c: (c[0], c[1]["title"]))]


def credits_page(manifest):
    def section(title, cats):
        rows = []
        for c in cats:
            rows.append(f"<h3>{html.escape(c['title'])}</h3><ul>")
            for e in c["items"]:
                author = html.escape(e.get("author") or "Unknown")
                src = e.get("source")
                link = f' · <a href="{html.escape(src)}">source</a>' if src else ""
                rows.append(f"<li><a href=\"{html.escape(e['file'])}\">{html.escape(e['title'])}</a>"
                            f" — {author} · {html.escape(e['license'])}{link}</li>")
            rows.append("</ul>")
        return f"<h2>{title}</h2>" + "".join(rows) if cats else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Emdalex Gallery — credits</title>
<style>body{{font:16px/1.5 -apple-system,system-ui,sans-serif;max-width:760px;margin:0 auto;padding:24px 16px;color:#1c1c1e}}
h1{{color:#C8261C}}a{{color:#C8261C}}li{{margin:4px 0}}</style></head>
<body><h1>Emdalex Gallery</h1>
<p>Ready pictures and music for videos made with <a href="/studio/">Emdalex Studio</a>.
Everything here is free to use, also on YouTube: public domain (CC0) or made by Emdalex.
In the app: Images or Sounds → Add from Emdalex Gallery.</p>
{section("Pictures", manifest["images"])}
{section("Music", manifest["music"])}
</body></html>
"""


def main():
    manifest = {"version": 1, "images": build("images", build_images), "music": build("music", build_music)}
    if errors:
        print("Not added (fix and run again):\n  " + "\n  ".join(errors), file=sys.stderr)
    (ROOT / "gallery.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    (ROOT / "index.html").write_text(credits_page(manifest))
    n_img = sum(len(c["items"]) for c in manifest["images"])
    n_mus = sum(len(c["items"]) for c in manifest["music"])
    print(f"gallery.json: {n_img} pictures, {n_mus} songs")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
