"""Unified model class definitions shared across the project."""

import torch.nn as tnn


class PreferenceModel(tnn.Module):
    """Preference scoring model with a timm backbone and a regression head.

    Handles 4D (B,C,H,W) and 3D (B,S,C) feature tensors from the backbone
    by averaging over spatial/token dimensions before the head.
    """

    def __init__(self, backbone, num_features, dropout=0.2):
        super().__init__()
        self.backbone = backbone
        self.head = tnn.Sequential(
            tnn.LayerNorm(num_features),
            tnn.Dropout(p=dropout),
            tnn.Linear(num_features, 256),
            tnn.GELU(),
            tnn.Dropout(p=dropout * 0.5),
            tnn.Linear(256, 1),
        )

    def forward(self, x):
        feats = self.backbone(x)
        if feats.ndim == 4:
            feats = feats.mean(dim=(2, 3))
        elif feats.ndim == 3:
            feats = feats.mean(dim=1)
        return self.head(feats)


class NaFlexClassifier(tnn.Module):
    """Classifier for SigLIP2 NaFlex models.

    Wraps the vision model from a HuggingFace NaFlex checkpoint and adds
    a classification head. Falls back to mean-pooled last_hidden_state
    when pooler_output is unavailable.
    """

    def __init__(self, hf_model, num_features, dropout=0.2):
        super().__init__()
        self.vision_model = hf_model.vision_model
        self.num_features = num_features
        hidden = 512
        self.head = tnn.Sequential(
            tnn.LayerNorm(num_features),
            tnn.Dropout(dropout),
            tnn.Linear(num_features, hidden),
            tnn.GELU(),
            tnn.LayerNorm(hidden),
            tnn.Dropout(dropout * 0.5),
            tnn.Linear(hidden, 1),
        )

    def forward(self, pixel_values, pixel_attention_mask=None, spatial_shapes=None):
        kwargs = {"pixel_values": pixel_values}
        if pixel_attention_mask is not None:
            kwargs["attention_mask"] = pixel_attention_mask
        if spatial_shapes is not None:
            kwargs["spatial_shapes"] = spatial_shapes
        outputs = self.vision_model(**kwargs)
        feats = outputs.pooler_output
        if feats is None:
            feats = outputs.last_hidden_state.mean(dim=1)
        return self.head(feats)


def build_timm_transform(input_size, mean=None, std=None):
    """Build the canonical timm/EVA02 transform pipeline."""
    from torchvision import transforms as T

    if mean is None:
        mean = [0.485, 0.456, 0.406]
    if std is None:
        std = [0.229, 0.224, 0.225]
    return T.Compose([
        T.Resize(int(input_size * 1.14), interpolation=T.InterpolationMode.BICUBIC),
        T.CenterCrop(input_size),
        T.ToTensor(),
        T.Normalize(mean=mean, std=std),
    ])
