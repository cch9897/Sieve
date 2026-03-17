#!/usr/bin/env python3
"""
Preference classifier: trains on WD14 tags to predict liked/disliked images.
Combines booru-gallery human labels + Twitter liked images.
"""

import json
import sqlite3
import os
import sys
import numpy as np
from collections import Counter
from pathlib import Path

# ============================================================
# Step 1: Collect training data
# ============================================================

_PROJECT_ROOT = Path(__file__).parent.parent

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

def _resolve(env_key, default):
    val = os.environ.get(env_key, default)
    p = Path(val)
    return str(p if p.is_absolute() else _PROJECT_ROOT / p)

LABELS_DB = _resolve("LABELS_DB", "backend/labels.db")
TWITTER_DIR = os.environ.get("TWITTER_DIR", "")
TWITTER_TAGS_DB = os.environ.get("TWITTER_TAGS_DB", "")
MODEL_OUT = _resolve("PREFERENCE_MODEL_PATH", "classifier/model.joblib")
REPORT_OUT = _resolve("REPORT_OUT", "classifier/report.txt")

def load_booru_data():
    """Load booru-gallery labels + auto_tags."""
    conn = sqlite3.connect(LABELS_DB)
    cur = conn.cursor()
    
    # Get labeled images with auto_tags
    cur.execute('''
        SELECT l.image_id, l.verdict, a.general_json, a.rating_json
        FROM labels l
        JOIN auto_tags a ON l.image_id = a.image_id
        WHERE l.verdict IN ('liked', 'disliked')
    ''')
    rows = cur.fetchall()
    conn.close()
    
    data = []
    for image_id, verdict, general_json, rating_json in rows:
        general = json.loads(general_json)
        rating = json.loads(rating_json)
        label = 1 if verdict == 'liked' else 0
        data.append((general, rating, label, f"booru_{image_id}"))
    
    return data

def load_twitter_tags():
    """Load Twitter image tags from pre-computed DB."""
    if not os.path.exists(TWITTER_TAGS_DB):
        print(f"Twitter tags DB not found at {TWITTER_TAGS_DB}")
        print("Run tag_twitter.py first!")
        return []
    
    conn = sqlite3.connect(TWITTER_TAGS_DB)
    cur = conn.cursor()
    cur.execute('SELECT filename, general_json, rating_json FROM tags')
    rows = cur.fetchall()
    conn.close()
    
    data = []
    for filename, general_json, rating_json in rows:
        general = json.loads(general_json)
        rating = json.loads(rating_json)
        # All Twitter liked images are positive samples
        data.append((general, rating, 1, f"twitter_{filename}"))
    
    return data

# ============================================================
# Step 2: Feature engineering
# ============================================================

def build_features(data, min_freq=5):
    """Convert tag dicts to feature matrix."""
    # Collect all tag names
    tag_counter = Counter()
    for general, rating, label, name in data:
        tag_counter.update(general.keys())
    
    # Keep tags that appear at least min_freq times
    tag_vocab = sorted([t for t, c in tag_counter.items() if c >= min_freq])
    tag_to_idx = {t: i for i, t in enumerate(tag_vocab)}
    
    n_tag_features = len(tag_vocab)
    rating_names = ['general', 'sensitive', 'questionable', 'explicit']
    n_features = n_tag_features + len(rating_names) + 2  # +2 for tag_count, max_conf
    
    X = np.zeros((len(data), n_features), dtype=np.float32)
    y = np.zeros(len(data), dtype=np.int32)
    names = []
    
    for i, (general, rating, label, name) in enumerate(data):
        # Tag confidence scores as features
        for tag, conf in general.items():
            if tag in tag_to_idx:
                X[i, tag_to_idx[tag]] = conf
        
        # Rating features
        for j, rname in enumerate(rating_names):
            X[i, n_tag_features + j] = rating.get(rname, 0)
        
        # Meta features
        X[i, n_tag_features + 4] = len(general)  # tag count
        X[i, n_tag_features + 5] = max(general.values()) if general else 0  # max confidence
        
        y[i] = label
        names.append(name)
    
    feature_names = tag_vocab + rating_names + ['tag_count', 'max_confidence']
    return X, y, names, feature_names, tag_vocab

# ============================================================
# Step 3: Train and evaluate
# ============================================================

def train_and_evaluate(X, y, names, feature_names):
    """Train XGBoost/LightGBM classifier with cross-validation."""
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.metrics import classification_report, roc_auc_score
    import joblib
    
    # Try XGBoost first, fall back to sklearn
    try:
        from xgboost import XGBClassifier
        clf = XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=sum(y == 0) / max(sum(y == 1), 1),
            random_state=42,
            eval_metric='logloss',
        )
        model_type = "XGBoost"
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        clf = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42,
        )
        model_type = "GradientBoosting (sklearn)"
    
    print(f"\nUsing {model_type}")
    print(f"Dataset: {len(y)} samples, {sum(y==1)} liked, {sum(y==0)} disliked")
    print(f"Features: {X.shape[1]}")
    
    # Cross-validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_pred_proba = cross_val_predict(clf, X, y, cv=cv, method='predict_proba')[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)
    
    report = classification_report(y, y_pred, target_names=['disliked', 'liked'])
    auc = roc_auc_score(y, y_pred_proba)
    
    print(f"\n=== Cross-Validation Results (5-fold) ===")
    print(report)
    print(f"ROC AUC: {auc:.4f}")
    
    # Train final model on all data
    clf.fit(X, y)
    
    # Feature importance
    if hasattr(clf, 'feature_importances_'):
        importances = clf.feature_importances_
        top_idx = np.argsort(importances)[::-1][:30]
        print(f"\n=== Top 30 Most Important Features ===")
        for rank, idx in enumerate(top_idx, 1):
            print(f"  {rank:2d}. {feature_names[idx]:30s} importance={importances[idx]:.4f}")
    
    # Save model + metadata
    os.makedirs(os.path.dirname(MODEL_OUT), exist_ok=True)
    model_data = {
        'model': clf,
        'feature_names': feature_names,
        'tag_vocab': feature_names[:X.shape[1] - 6],  # exclude rating + meta
        'model_type': model_type,
        'n_samples': len(y),
        'n_liked': int(sum(y == 1)),
        'n_disliked': int(sum(y == 0)),
        'auc': float(auc),
    }
    joblib.dump(model_data, MODEL_OUT)
    print(f"\nModel saved to {MODEL_OUT}")
    
    # Save report
    with open(REPORT_OUT, 'w') as f:
        f.write(f"Model: {model_type}\n")
        f.write(f"Dataset: {len(y)} samples ({sum(y==1)} liked, {sum(y==0)} disliked)\n")
        f.write(f"Features: {X.shape[1]}\n")
        f.write(f"ROC AUC: {auc:.4f}\n\n")
        f.write(report)
        if hasattr(clf, 'feature_importances_'):
            f.write(f"\nTop 30 Features:\n")
            for rank, idx in enumerate(top_idx, 1):
                f.write(f"  {rank:2d}. {feature_names[idx]:30s} {importances[idx]:.4f}\n")
    
    return clf, auc

# ============================================================
# Main
# ============================================================

if __name__ == '__main__':
    print("Loading booru-gallery data...")
    booru_data = load_booru_data()
    print(f"  Booru: {len(booru_data)} samples ({sum(1 for _,_,l,_ in booru_data if l==1)} liked, {sum(1 for _,_,l,_ in booru_data if l==0)} disliked)")
    
    print("\nLoading Twitter data...")
    twitter_data = load_twitter_tags()
    print(f"  Twitter: {len(twitter_data)} samples (all liked)")
    
    all_data = booru_data + twitter_data
    print(f"\nTotal: {len(all_data)} samples")
    
    print("\nBuilding features...")
    X, y, names, feature_names, tag_vocab = build_features(all_data)
    
    print("\nTraining classifier...")
    clf, auc = train_and_evaluate(X, y, names, feature_names)
