#!/usr/bin/env python3
"""
WaniKani Audio Quiz — Downloader
=================================
Run this ONCE from your Japanese_Study folder.
It fetches all WaniKani vocab + kanji (all 60 levels) and downloads
every audio file to the audio/ subfolder.

If interrupted, just run it again — it skips files already downloaded.

Requirements:  pip install requests --break-system-packages
"""

import json
import os
import sys
import time
import requests

# ── Config ─────────────────────────────────────────────
AUDIO_DIR  = "audio"
DATA_FILE  = "wk_data.js"
API_BASE   = "https://api.wanikani.com/v2"
API_HDR    = {"Wanikani-Revision": "20170710"}
DELAY_API  = 0.4   # seconds between API pages (be polite)
DELAY_DL   = 0.03  # seconds between audio downloads (~33/sec)
# ───────────────────────────────────────────────────────


def api_get(url, token):
    """GET a WaniKani API URL, retrying on rate limit."""
    headers = {**API_HDR, "Authorization": f"Bearer {token}"}
    while True:
        try:
            r = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException as e:
            print(f"\n  Network error: {e}. Retrying in 10s...")
            time.sleep(10)
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 60))
            print(f"\n  Rate limited — waiting {wait}s...")
            time.sleep(wait)
            continue
        if r.status_code == 401:
            sys.exit("\n✗ API token invalid or expired. Check your token.\n")
        r.raise_for_status()
        return r.json()


def fetch_all_subjects(token):
    """Fetch every vocabulary + kanji subject across all levels."""
    subjects = []
    url = f"{API_BASE}/subjects?types=vocabulary,kanji&per_page=500"
    page = 1
    while url:
        data = api_get(url, token)
        batch = data["data"]
        subjects.extend(batch)
        url = data["pages"].get("next_url")
        total = data["total_count"]
        print(f"  Fetched {len(subjects):,} / {total:,} subjects (page {page})...", end="\r")
        page += 1
        if url:
            time.sleep(DELAY_API)
    print(f"\n  ✓ {len(subjects):,} subjects fetched.")
    return subjects


def download_audio_files(subjects, token):
    """Download all MP3 audio files for vocabulary items."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    headers = {**API_HDR, "Authorization": f"Bearer {token}"}

    # Build task list (skip already-downloaded files)
    tasks = []
    for s in subjects:
        if s["object"] != "vocabulary":
            continue
        for a in s["data"].get("pronunciation_audios", []):
            if a["content_type"] != "audio/mpeg":
                continue
            gender_char = "f" if a["metadata"].get("gender") == "female" else "m"
            fname = f"{s['id']}_{gender_char}.mp3"
            fpath = os.path.join(AUDIO_DIR, fname)
            if not os.path.exists(fpath):
                tasks.append((a["url"], fpath))

    already = sum(
        1 for s in subjects if s["object"] == "vocabulary"
        for a in s["data"].get("pronunciation_audios", [])
        if a["content_type"] == "audio/mpeg"
    ) - len(tasks)

    if already:
        print(f"  {already:,} audio files already present, skipping.")
    if not tasks:
        print("  ✓ All audio files already downloaded.")
        return

    print(f"  Downloading {len(tasks):,} audio files — this will take a while...")
    print("  (Safe to Ctrl+C and re-run; it resumes where it left off)")
    print()

    errors = []
    for i, (url, fpath) in enumerate(tasks, 1):
        pct = i / len(tasks) * 100
        bar_len = 30
        filled = int(bar_len * i // len(tasks))
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"  [{bar}] {pct:5.1f}%  {i:,}/{len(tasks):,}", end="\r")

        try:
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(r.content)
        except Exception as e:
            errors.append((fpath, str(e)))

        time.sleep(DELAY_DL)

    print(f"\n  ✓ Done. {len(tasks) - len(errors):,} files saved to ./{AUDIO_DIR}/")
    if errors:
        print(f"  ⚠ {len(errors)} errors (re-run to retry):")
        for fpath, err in errors[:5]:
            print(f"    {os.path.basename(fpath)}: {err}")
        if len(errors) > 5:
            print(f"    ... and {len(errors)-5} more")


def build_data_js(subjects):
    """Write wk_data.js — the local data file the HTML quiz loads."""
    items = []
    for s in subjects:
        d   = s["data"]
        obj = s["object"]

        # Audio local paths (vocab only)
        audio = {}
        if obj == "vocabulary":
            for a in d.get("pronunciation_audios", []):
                if a["content_type"] != "audio/mpeg":
                    continue
                key = "f" if a["metadata"].get("gender") == "female" else "m"
                if key not in audio:
                    audio[key] = f"audio/{s['id']}_{key}.mp3"

        items.append({
            "id":       s["id"],
            "obj":      obj,                                     # "vocabulary" | "kanji"
            "level":    d["level"],
            "char":     d.get("characters") or d.get("slug", ""),
            "meanings": [m["meaning"] for m in d.get("meanings", [])
                         if m.get("accepted_answer", True)],
            "readings": [
                {
                    "r":       r["reading"],
                    "primary": r.get("primary", False),
                    "ok":      r.get("accepted_answer", True),
                    "type":    r.get("type", "")               # onyomi|kunyomi|nanori
                }
                for r in d.get("readings", [])
            ],
            "audio": audio,
        })

    vocab_count = sum(1 for s in subjects if s["object"] == "vocabulary")
    kanji_count = sum(1 for s in subjects if s["object"] == "kanji")

    js = (
        "// WaniKani offline data — generated by download_wk.py\n"
        f"// {len(items):,} items  ({vocab_count:,} vocabulary · {kanji_count:,} kanji)\n"
        f"const WK_DATA = {json.dumps(items, ensure_ascii=False, separators=(',', ':'))};\n"
    )

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        f.write(js)

    size_mb = os.path.getsize(DATA_FILE) / 1_048_576
    print(f"  ✓ {DATA_FILE} written ({len(items):,} items, {size_mb:.1f} MB)")


def main():
    print()
    print("╔══════════════════════════════════════╗")
    print("║  WaniKani Audio Quiz — Downloader    ║")
    print("╚══════════════════════════════════════╝")
    print()

    # Sanity check: are we in the right folder?
    here = os.path.basename(os.getcwd())
    if not os.path.exists("wk_audio_quiz.html"):
        print(f"⚠  wk_audio_quiz.html not found in the current folder ({os.getcwd()}).")
        print("   Make sure to run this script FROM your Japanese_Study folder:")
        print("   cd  C:\\AI_Sandbox\\Japanese_Study")
        print("   python download_wk.py")
        print()

    # Get token
    print("Paste your WaniKani API v2 token and press Enter.")
    print("(Generate one at: wanikani.com → Account → Personal Access Tokens)")
    print()
    token = input("Token: ").strip()
    if not token:
        sys.exit("No token entered. Exiting.")
    print()

    # Step 1 — subjects
    print("Step 1/3 — Fetching all subjects from WaniKani API...")
    subjects = fetch_all_subjects(token)
    print()

    # Step 2 — audio
    print("Step 2/3 — Downloading audio files...")
    download_audio_files(subjects, token)
    print()

    # Step 3 — data JS
    print("Step 3/3 — Writing local data file...")
    build_data_js(subjects)
    print()

    # Done
    print("═" * 42)
    print("✓ All done! Everything is saved locally.")
    print()
    print("Open  wk_audio_quiz.html  in Chrome to start quizzing.")
    print("═" * 42)
    print()


if __name__ == "__main__":
    main()
