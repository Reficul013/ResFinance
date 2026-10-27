from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor, nn


def deterministic_checkpoint(model: nn.Module, *, model_config: Mapping[str, object]) -> bytes:
    tensors: dict[str, object] = {}
    for name, tensor in sorted(model.state_dict().items()):
        contiguous = tensor.detach().cpu().contiguous()
        array = contiguous.numpy()
        tensors[name] = {
            "dtype": str(array.dtype),
            "shape": list(array.shape),
            "data_b64": base64.b64encode(array.tobytes(order="C")).decode("ascii"),
        }
    document = {"schema_version": 1, "model_config": dict(model_config), "tensors": tensors}
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def restore_checkpoint(model: nn.Module, content: bytes) -> str:
    value = json.loads(content)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported checkpoint schema")
    tensors = value.get("tensors")
    if not isinstance(tensors, dict):
        raise ValueError("checkpoint tensors must be an object")
    state: dict[str, Tensor] = {}
    for name, item in tensors.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            raise ValueError("checkpoint tensor entry is invalid")
        shape = item.get("shape")
        dtype = item.get("dtype")
        data_b64 = item.get("data_b64")
        if (
            not isinstance(shape, list)
            or not isinstance(dtype, str)
            or not isinstance(data_b64, str)
        ):
            raise ValueError("checkpoint tensor metadata is invalid")
        raw = base64.b64decode(data_b64, validate=True)
        array = (
            np.frombuffer(raw, dtype=np.dtype(dtype))
            .copy()
            .reshape(tuple(int(x) for x in shape))
        )
        state[name] = torch.from_numpy(array)
    model.load_state_dict(state, strict=True)
    return hashlib.sha256(content).hexdigest()


def ensemble_checkpoint(
    models: Sequence[nn.Module], *, model_config: Mapping[str, object]
) -> bytes:
    """One deterministic artifact holding every seed's checkpoint, so it has a single hash."""
    if not models:
        raise ValueError("an ensemble checkpoint needs at least one model")
    members = [
        json.loads(deterministic_checkpoint(model, model_config=model_config)) for model in models
    ]
    document = {
        "schema_version": 1,
        "kind": "seed-ensemble",
        "model_config": dict(model_config),
        "members": members,
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def restore_models(factory: Callable[[], nn.Module], content: bytes) -> tuple[list[nn.Module], str]:
    """Restore a seed-ensemble or single checkpoint; returns the models and the content hash."""
    value = json.loads(content)
    if isinstance(value, dict) and value.get("kind") == "seed-ensemble":
        members = value.get("members")
        if value.get("schema_version") != 1 or not isinstance(members, list) or not members:
            raise ValueError("unsupported ensemble checkpoint schema")
        models = []
        for member in members:
            model = factory()
            restore_checkpoint(
                model,
                json.dumps(
                    member, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ).encode(),
            )
            models.append(model)
        return models, hashlib.sha256(content).hexdigest()
    model = factory()
    return [model], restore_checkpoint(model, content)
