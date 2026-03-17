#!/usr/bin/env python3
"""
Score Danbooru images using the trained preference classifier.
Connects to DanbooruFinder API, scores images based on tags, outputs top recommendations.
"""

import argparse
import json
import sys

import joblib
import numpy as np
import requests

import os as _os
from pathlib import Path as _Path
_PROJECT_ROOT = _Path(__file__).parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

_model = _os.environ.get("PREFERENCE_MODEL_PATH", "classifier/model.joblib")
MODEL_PATH = _model if _Path(_model).is_absolute() else str(_PROJECT_ROOT / _model)
_api = _os.environ.get("DANBOORU_API", "http://localhost:5001")
DANBOORU_API = f"{_api}/search"


def load_model(path=MODEL_PATH):
    data = joblib.load(path)
    return data


def build_features_for_image(tags_str: str, rating: str, model_data: dict) -> np.ndarray:
    """Build feature vector for a single Danbooru image.
    
    Args:
        tags_str: space-separated tag string from Danbooru
        rating: single-char rating (g/s/q/e)
        model_data: loaded model dict with tag_vocab, feature_names
    """
    tag_vocab = model_data['tag_vocab']
    feature_names = model_data['feature_names']
    n_features = len(feature_names)
    
    x = np.zeros(n_features, dtype=np.float32)
    
    # Parse tags: Danbooru tags may be comma-separated with underscores
    raw_tags = [t.strip().strip(',') for t in tags_str.split()] if tags_str else []
    # WD14 vocab uses spaces for multi-word tags; Danbooru uses underscores
    image_tags = set()
    for t in raw_tags:
        image_tags.add(t)
        image_tags.add(t.replace('_', ' '))
    
    # Tag features (binary: present=1.0, absent=0.0)
    tag_to_idx = {t: i for i, t in enumerate(tag_vocab)}
    for tag in image_tags:
        if tag in tag_to_idx:
            x[tag_to_idx[tag]] = 1.0
    
    # Rating features (4 dims after tag_vocab)
    n_tags = len(tag_vocab)
    rating_map = {'general': 0, 'sensitive': 1, 'questionable': 2, 'explicit': 3}
    rating_full = {'g': 'general', 's': 'sensitive', 'q': 'questionable', 'e': 'explicit'}
    rating_name = rating_full.get(rating, '')
    if rating_name in rating_map:
        x[n_tags + rating_map[rating_name]] = 1.0
    
    # Meta features
    x[n_tags + 4] = len(raw_tags)  # tag_count (original, not doubled)
    x[n_tags + 5] = 1.0  # max_confidence (binary tags → 1.0)
    
    return x


def score_images(images: list, model_data: dict) -> list:
    """Score a list of Danbooru images, return sorted by preference_score."""
    model = model_data['model']
    
    if not images:
        return []
    
    X = np.array([
        build_features_for_image(img.get('tags', ''), img.get('rating', ''), model_data)
        for img in images
    ])
    
    proba = model.predict_proba(X)[:, 1]
    
    results = []
    for img, score in zip(images, proba):
        results.append({**img, 'preference_score': float(score)})
    
    results.sort(key=lambda x: x['preference_score'], reverse=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="Score Danbooru images with preference classifier")
    parser.add_argument('--top', type=int, default=20, help='Number of top results to show')
    parser.add_argument('--min-score', type=float, default=0.5, help='Minimum preference score')
    parser.add_argument('--rating', type=str, default=None, help='Filter by rating (g/s/q/e)')
    parser.add_argument('--pages', type=int, default=5, help='Number of pages to fetch from API')
    parser.add_argument('--per-page', type=int, default=40, help='Results per API page')
    parser.add_argument('--model', type=str, default=MODEL_PATH, help='Path to model.joblib')
    args = parser.parse_args()
    
    print(f"Loading model from {args.model}...")
    model_data = load_model(args.model)
    print(f"  Model: {model_data['model_type']}, AUC: {model_data['auc']:.4f}, "
          f"Trained on {model_data['n_samples']} samples")
    print(f"  Tag vocab size: {len(model_data['tag_vocab'])}")
    
    # Fetch images from DanbooruFinder
    all_images = []
    for page in range(1, args.pages + 1):
        params = {'page': page, 'per_page': args.per_page, 'order_by': 'random'}
        if args.rating:
            params['rating'] = args.rating
        
        try:
            resp = requests.get(DANBOORU_API, params=params, timeout=10)
            data = resp.json()
            results = data.get('results', [])
            all_images.extend(results)
            print(f"  Fetched page {page}: {len(results)} images")
        except Exception as e:
            print(f"  Error fetching page {page}: {e}", file=sys.stderr)
    
    print(f"\nTotal fetched: {len(all_images)} images")
    
    # Score
    scored = score_images(all_images, model_data)
    
    # Filter and display
    filtered = [img for img in scored if img['preference_score'] >= args.min_score]
    top = filtered[:args.top]
    
    print(f"\n{'='*60}")
    print(f"Top {len(top)} recommendations (min_score={args.min_score}):")
    print(f"{'='*60}")
    
    for i, img in enumerate(top, 1):
        score_pct = img['preference_score'] * 100
        print(f"\n  {i:2d}. ID: {img['id']}")
        print(f"      Score: {score_pct:.1f}% | Danbooru score: {img.get('score', 0)} | Rating: {img.get('rating', '?')}")
        tags = img.get('tags', '')
        if tags:
            tag_list = tags.split()[:10]
            print(f"      Tags: {', '.join(t.replace('_', ' ') for t in tag_list)}")
            if len(tags.split()) > 10:
                print(f"            ... +{len(tags.split()) - 10} more")
    
    print(f"\n{len(filtered)} images scored >= {args.min_score} out of {len(all_images)} total")


if __name__ == '__main__':
    main()
