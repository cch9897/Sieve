import numpy as np

N_META_FEATURES = 6


def build_tag_features(tags_str, rating, model_data):
    tag_vocab = model_data['tag_vocab']
    feature_names = model_data['feature_names']
    n_features = len(feature_names)

    x = np.zeros(n_features, dtype=np.float32)
    raw_tags = [t.strip().strip(',') for t in tags_str.split()] if tags_str else []
    image_tags = set()
    for t in raw_tags:
        image_tags.add(t)
        image_tags.add(t.replace('_', ' '))

    tag_to_idx = {t: i for i, t in enumerate(tag_vocab)}
    for tag in image_tags:
        if tag in tag_to_idx:
            x[tag_to_idx[tag]] = 1.0

    n_tags = len(tag_vocab)
    rating_map = {'general': 0, 'sensitive': 1, 'questionable': 2, 'explicit': 3}
    rating_full = {'g': 'general', 's': 'sensitive', 'q': 'questionable', 'e': 'explicit'}
    rating_name = rating_full.get(rating, '')
    if rating_name in rating_map:
        x[n_tags + rating_map[rating_name]] = 1.0

    x[n_tags + 4] = len(raw_tags)
    # max_confidence: Danbooru tags are human-curated (not ML-generated), so each
    # tag is effectively confidence 1.0. This differs from training where
    # WD14-generated tags have actual confidence values (0..1).
    # Setting 1.0 here matches the semantics of binary human tags.
    x[n_tags + 5] = 1.0
    return x


def validate_feature_dims(tag_vocab, feature_names):
    expected = len(tag_vocab) + N_META_FEATURES
    if len(feature_names) != expected:
        raise ValueError(f"Feature dimension mismatch: got {len(feature_names)} feature_names, expected {expected} ({len(tag_vocab)} tags + {N_META_FEATURES} meta)")
