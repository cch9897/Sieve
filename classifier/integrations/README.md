# Integrations

Site-specific scripts for specialized data sources. These are **not required** for the core classifier workflow.

| Script | Requires | Purpose |
|--------|----------|---------|
| `pack_remote.sh` | SSH to a remote server with DanbooruFinder | Resize locally → upload → extract disliked from tar → pull back archive |
| `extract_disliked_remote.py` | DanbooruFinder `tar_index.db` | Extract disliked images from tar-indexed archives |
| `score_danbooru.py` | DanbooruFinder API (`localhost:5001`) | Score random Danbooru images with XGBoost model |
| `tag_twitter.py` | Twitter liked images dir + `imgutils` | Auto-tag images with WD14 SwinV2 for XGBoost training |
