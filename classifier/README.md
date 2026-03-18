# Preference Classifier

Train a visual preference model: given images you've labeled as "liked" or "disliked", learn to predict your taste.

## Quick Start

### 1. Prepare Data

Organize your images into two directories:

```
my_data/
├── liked/       # images you like
│   ├── img001.jpg
│   └── img002.png
└── disliked/    # images you don't like
    ├── img003.jpg
    └── img004.webp
```

### 2. Pack Dataset

```bash
# From liked/disliked folders
python pack_dataset.py --liked my_data/liked --disliked my_data/disliked

# Or use --data-dir with liked/ and disliked/ subdirectories
python pack_dataset.py --data-dir my_data

# Multiple source directories
python pack_dataset.py --liked ~/pixiv_favs ~/twitter_favs --disliked ~/meh

# Custom resize (default: 512px longer edge)
python pack_dataset.py --data-dir my_data --max-size 384
```

Output: `preference_train.tar.gz` containing `images/`, `manifest.csv`, `train.py`, and `requirements.txt`.

### 3. Train

Transfer the archive to a GPU machine:

```bash
tar xzf preference_train.tar.gz
cd _tmp_pack
pip install -r requirements.txt

# Basic training (ConvNeXt-Tiny, 5-fold CV)
python train.py

# Larger model
python train.py --model convnext_small.fb_in22k_ft_in1k --unfreeze 2

# Advanced: EVA02-Large with DDP multi-GPU
torchrun --nproc_per_node=3 train_ev2_multi_card.py \
  --model eva02_large_patch14_clip_336.merged2b \
  --batch-size 32 --epochs 12
```

### 4. Deploy

Copy the trained `.pt` file back to `classifier/model_aesthetic.pt` (or set `CNN_MODEL_PATH` in `.env`). The Sieve backend auto-loads it on startup.

## Files

### Core (universal)

| File | Description |
|------|-------------|
| `pack_dataset.py` | Pack images into training archive (folder or DB input) |
| `pack_pipeline.sh` | Thin wrapper: loads .env, activates venv, runs pack_dataset.py |
| `train_ev2_multi_card.py` | Advanced DDP multi-GPU training (EVA02/ConvNeXt) |
| `train_classifier.py` | XGBoost tag-based classifier (requires auto-tags) |
| `prefetch_candidates.py` | Pre-screen images with fusion scoring (XGBoost + vision) |
| `retrain.sh` | Re-tag + retrain XGBoost pipeline |

### Integrations (site-specific, optional)

| File | Description |
|------|-------------|
| `integrations/pack_remote.sh` | Remote pack via SSH + DanbooruFinder tar extraction |
| `integrations/extract_disliked_remote.py` | Extract images from DanbooruFinder tar archives |
| `integrations/score_danbooru.py` | Score images from a DanbooruFinder API |
| `integrations/tag_twitter.py` | Auto-tag Twitter liked images with WD14 |

## Architecture

Two models work together via fusion scoring:

- **XGBoost (tag-based)**: Trained on WD14 auto-tags. Fast, needs tag data. (`model.joblib`)
- **Vision (CNN/ViT)**: Trained on raw pixels. Slower, works on any image. (`model_aesthetic.pt`)

Fusion: `score = tag_weight × xgb_score + (1 - tag_weight) × vision_score`

The vision model supports two checkpoint formats:
- **Legacy**: plain timm model with `num_classes=1`
- **PreferenceModel**: timm backbone (`num_classes=0`) + custom head (LayerNorm → Linear → GELU → Linear)

## Configuration

All paths are configurable via environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `CNN_MODEL_PATH` | `classifier/model_aesthetic.pt` | Vision model checkpoint |
| `PREFERENCE_MODEL_PATH` | `classifier/model.joblib` | XGBoost model |
| `CANDIDATES_DB` | `backend/candidates.db` | Pre-screening candidates DB |
| `LABELS_DB` | `backend/labels.db` | Sieve labeling database |
| `CRAWLER_DIR` | — | Booru crawler directory (optional) |
| `TWITTER_DIR` | — | Twitter liked images (optional) |
| `DANBOORU_LIKES_DIR` | `data/danbooru_liked` | Danbooru liked images (optional) |
| `DANBOORU_API` | `http://localhost:5001` | DanbooruFinder API (optional) |

## Tips

- **Minimum data**: ~500 liked + ~500 disliked for decent results. More is better.
- **Image quality**: Mixed resolutions are fine — resize handles everything.
- **Class balance**: The training script auto-adjusts for imbalanced datasets via `pos_weight`.
- **CPU training**: Works but slow. A single GPU (even a 3060) makes a huge difference.
- **Multi-GPU**: Use `train_ev2_multi_card.py` with `torchrun` for DDP training.
