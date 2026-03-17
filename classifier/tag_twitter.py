#!/usr/bin/env python3
"""
Tag Twitter liked images using WD14 SwinV2_v3 tagger.
Filters out non-illustration images (photos, screenshots, etc.)
Stores results in twitter_tags.db.
"""

import os
import sys
import json
import sqlite3
import time
from pathlib import Path

import os as _os
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

TWITTER_DIR = _os.environ.get("TWITTER_DIR", "")
TAGS_DB = _os.environ.get("TWITTER_TAGS_DB", "")
MODEL_NAME = "SwinV2_v3"
GENERAL_THRESHOLD = 0.35

# Minimum illustration confidence: if none of the anime/illustration tags are above
# this threshold, skip the image (likely a photo or non-illustration)
ILLUSTRATION_TAGS = {'1girl', '1boy', 'no_humans', 'multiple_girls', 'multiple_boys',
                     '2girls', '3girls', '2boys', 'solo', 'scenery', 'landscape',
                     'comic', 'manga', '4koma', 'monochrome', 'chibi'}
MIN_ILLUSTRATION_SCORE = 0.3

def init_db():
    conn = sqlite3.connect(TAGS_DB)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS tags (
        filename TEXT PRIMARY KEY,
        rating_json TEXT NOT NULL,
        general_json TEXT NOT NULL,
        character_json TEXT NOT NULL,
        top_tags TEXT NOT NULL,
        is_illustration INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn

def get_already_tagged(conn):
    cur = conn.cursor()
    cur.execute('SELECT filename FROM tags')
    return {row[0] for row in cur.fetchall()}

def get_image_files():
    exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    files = []
    for f in os.listdir(TWITTER_DIR):
        if Path(f).suffix.lower() in exts:
            files.append(f)
    return sorted(files)

def tag_images():
    from imgutils.tagging import get_wd14_tags
    
    conn = init_db()
    already_tagged = get_already_tagged(conn)
    all_files = get_image_files()
    
    to_tag = [f for f in all_files if f not in already_tagged]
    print(f"Total images: {len(all_files)}, already tagged: {len(already_tagged)}, to tag: {len(to_tag)}")
    
    if not to_tag:
        print("All images already tagged!")
        show_stats(conn)
        return
    
    tagged = 0
    skipped_non_illust = 0
    errors = 0
    start = time.time()
    
    for i, filename in enumerate(to_tag):
        filepath = os.path.join(TWITTER_DIR, filename)
        try:
            rating, general, character = get_wd14_tags(
                filepath,
                model_name=MODEL_NAME,
                general_threshold=GENERAL_THRESHOLD,
            )
            
            # Check if it's an illustration
            is_illust = 1
            illust_scores = [general.get(t, 0) for t in ILLUSTRATION_TAGS]
            if not illust_scores or max(illust_scores) < MIN_ILLUSTRATION_SCORE:
                # Also check if any general tag has high confidence (illustration-like)
                if general and max(general.values()) < 0.5:
                    is_illust = 0
                    skipped_non_illust += 1
            
            # Sort tags by confidence
            sorted_tags = sorted(general.items(), key=lambda x: -x[1])
            top_tags = ', '.join(t for t, _ in sorted_tags[:30])
            
            conn.execute('''INSERT OR REPLACE INTO tags 
                (filename, rating_json, general_json, character_json, top_tags, is_illustration)
                VALUES (?, ?, ?, ?, ?, ?)''',
                (filename,
                 json.dumps(rating),
                 json.dumps(general),
                 json.dumps(character),
                 top_tags,
                 is_illust))
            
            tagged += 1
            if tagged % 10 == 0:
                conn.commit()
                elapsed = time.time() - start
                rate = tagged / elapsed
                eta = (len(to_tag) - i - 1) / rate if rate > 0 else 0
                print(f"  [{i+1}/{len(to_tag)}] {filename} | "
                      f"{'ILLUST' if is_illust else 'SKIP'} | "
                      f"{rate:.1f} img/s | ETA {eta/60:.0f}min")
                
        except Exception as e:
            errors += 1
            print(f"  ERROR {filename}: {e}")
    
    conn.commit()
    elapsed = time.time() - start
    
    print(f"\nDone in {elapsed/60:.1f} min")
    print(f"Tagged: {tagged}, Non-illustration: {skipped_non_illust}, Errors: {errors}")
    
    show_stats(conn)
    conn.close()

def show_stats(conn):
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM tags')
    total = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM tags WHERE is_illustration = 1')
    illust = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM tags WHERE is_illustration = 0')
    non_illust = cur.fetchone()[0]
    print(f"\n=== Stats ===")
    print(f"Total tagged: {total}")
    print(f"Illustrations: {illust}")
    print(f"Non-illustrations: {non_illust}")

if __name__ == '__main__':
    tag_images()
