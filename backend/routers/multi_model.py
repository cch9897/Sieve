from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import state

router = APIRouter()


@router.get("/api/models")
async def list_models():
    """List all loaded vision models and their info."""
    result = {}
    for key, info in state._models.items():
        result[key] = {
            "model_name": info.get("model_name"),
            "model_class": info.get("model_class"),
            "type": info.get("type"),
            "cv_auc": info.get("cv_auc", 0),
            "n_samples": info.get("n_samples", 0),
            "input_size": info.get("input_size"),
            "fold_aucs": info.get("fold_aucs", []),
            "is_active": key == state._active_model,
            "loaded_in_memory": key == state._loaded_model_key,
        }
    return {"models": result, "active_model": state._active_model, "loaded_in_memory": state._loaded_model_key}


class SetActiveModelRequest(BaseModel):
    model_key: str


@router.post("/api/models/active")
async def set_active_model(req: SetActiveModelRequest):
    """Switch the active model for scoring and display."""
    if req.model_key not in state._models:
        raise HTTPException(
            status_code=400, detail=f"Unknown model: {req.model_key}. Available: {list(state._models.keys())}"
        )
    with state._active_model_lock:
        state._active_model = req.model_key
    return {"active_model": state._active_model}
