# Sieve

A personal artwork curation tool that learns your taste. Browse, label, auto-tag, and train preference models to surface art you'll love from booru sources.

> **Note:** This project is entirely AI-generated — code, documentation, and all. Built through conversations with Claude (Anthropic) via [OpenClaw](https://github.com/openclaw/openclaw).

## Features

- **Image Gallery**: Browse crawled images with infinite scroll, filtering by source/date/media type, and lightbox viewer
- **Novel Reader**: Browse and read crawled novels with search and sorting
- **Image Labeler**: Tinder-style image review (like/dislike/skip) with keyboard shortcuts
- **Auto-Tagging**: WD14 SwinV2_v3 automatic tagging for all images
- **Preference Classifier**: XGBoost (tag-based) + CNN (ConvNeXt, image-based) fusion model for predicting user preferences
- **AI Recommendations**: Pre-screened Danbooru candidates sorted by predicted preference score
- **Export**: Download labeled images as ZIP with metadata

## Architecture

```
sieve/
├── backend/              # FastAPI backend
│   ├── main.py           # API server
│   ├── config.py         # Configuration (env-based)
│   ├── auto_tagger.py    # WD14 auto-tagging script
│   └── run_auto_tagger.sh
├── classifier/           # Preference ML pipeline
│   ├── pack_dataset.py        # Dataset packaging (folder or DB input)
│   ├── pack_pipeline.sh       # Pack wrapper (loads .env + venv)
│   ├── train_ev2_multi_card.py # DDP multi-GPU training (EVA02/ConvNeXt)
│   ├── train_classifier.py    # XGBoost tag-based training
│   ├── prefetch_candidates.py # Continuous AI pre-screening
│   ├── retrain.sh             # One-click retrain pipeline
│   └── integrations/          # Site-specific scripts (optional)
├── frontend/             # React + TypeScript + Tailwind
│   └── src/
│       ├── App.tsx
│       └── components/   # UI components
├── .env.example          # Configuration template
└── start.sh              # Quick start script
```

## Setup

1. **Clone and configure:**
   ```bash
   cp .env.example .env
   # Edit .env with your paths
   ```

2. **Backend:**
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Frontend:**
   ```bash
   cd frontend
   npm install
   npm run build
   ```

4. **Run:**
   ```bash
   ./start.sh
   # Or manually: cd backend && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8780
   ```

## Configuration

All paths are configured via environment variables (see `.env.example`). Key settings:

| Variable | Description | Default |
|---|---|---|
| `CRAWLER_DIR` | Path to booru-crawler data directory | (required) |
| `DANBOORU_API` | DanbooruFinder API endpoint | `http://localhost:5001` |
| `PORT` | Server port | `8780` |
| `PREFERENCE_MODEL_PATH` | XGBoost model path | `classifier/model.joblib` |
| `CNN_MODEL_PATH` | Vision model path | `classifier/model_aesthetic.pt` |
| `TWITTER_DIR` | Twitter liked images (training data) | (optional) |

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `G` | Gallery view |
| `N` | Novel list |
| `D` | Labeler |
| `S` | Statistics |
| `←` / `H` | Dislike |
| `→` / `L` | Like |
| `↓` / `Space` | Skip |
| `T` | Add tags |
| `Ctrl+Z` | Undo |
| `F` | Toggle filters |
| `J` / `K` | Page navigation |
| `?` | Show shortcuts help |

## ML Pipeline

### Training
```bash
# Retrain XGBoost on all labeled data
cd classifier && bash retrain.sh

# Pack dataset for GPU CNN training
bash pack_pipeline.sh
# Transfer .tar.gz to GPU machine, extract, and run train.py
```

### Pre-screening
```bash
# Start continuous AI candidate pre-screening
cd backend && source venv/bin/activate
python ../classifier/prefetch_candidates.py
```

## Dependencies

**Backend:** FastAPI, uvicorn, aiosqlite, Pillow, httpx, joblib, numpy, xgboost, torch, timm  
**Frontend:** React, TypeScript, Vite, Tailwind CSS  
**Auto-tagger:** dghs-imgutils, onnxruntime

## License

MIT
