from __future__ import annotations

from importlib import import_module
from typing import Any

import httpx

from ai_dashboard.source_catalog import SOURCE_CATALOG

_ADAPTER_SPECS: dict[str, tuple[str, str]] = {
    source.kind: (source.module, source.class_name) for source in SOURCE_CATALOG
}


def _load_adapter(kind: str) -> type:
    module_name, class_name = _ADAPTER_SPECS[kind]
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class if isinstance(adapter_class, type) else type(adapter_class)


def build_adapter(kind: str, http: httpx.AsyncClient, options: dict[str, Any]) -> Any:
    if kind not in _ADAPTER_SPECS:
        raise ValueError(
            f"Unknown source kind: {kind!r}. Known: {sorted(_ADAPTER_SPECS)}"
        )
    return _load_adapter(kind)(http=http, options=options)


def available_kinds() -> list[str]:
    return sorted(_ADAPTER_SPECS)
