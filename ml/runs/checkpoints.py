from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping

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
