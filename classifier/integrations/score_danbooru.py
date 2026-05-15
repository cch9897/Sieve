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
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "classifier"))
from feature_utils import build_tag_features
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
    """Build feature vector for a single Danbooru image."""
    return build_tag_features(tags_str, rating, model_data)


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
