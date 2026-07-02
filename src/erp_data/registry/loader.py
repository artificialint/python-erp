"""Local module manifest registry — scan ``modules/*/module.json``.

Real upload is DISABLED for the MVP ("coming soon"): a developer drops a folder +
manifest and the loader reads it. No arbitrary code execution; signed/versioned
packages come much later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModuleManifest:
    code: str
    name: str
    version: str
    engine_module: str | None
    permissions: list[str]
    path: Path


UPLOAD_ENABLED = False  # MVP: manifest scan only.


def _modules_root() -> Path:
    # src/erp_data/registry/loader.py -> parents[3] == repo root
    return Path(__file__).resolve().parents[3] / "modules"


def load_manifests(modules_root: Path | str | None = None) -> list[ModuleManifest]:
    """Scan ``modules/*/module.json`` and return the parsed manifests."""
    root = Path(modules_root) if modules_root is not None else _modules_root()
    manifests: list[ModuleManifest] = []
    if not root.is_dir():
        return manifests
    for manifest_path in sorted(root.glob("*/module.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        manifests.append(
            ModuleManifest(
                code=str(data.get("code", "")),
                name=str(data.get("name", "")),
                version=str(data.get("version", "")),
                engine_module=data.get("engine_module"),
                permissions=list(data.get("permissions", [])),
                path=manifest_path.parent,
            )
        )
    return manifests


def find_module(code: str, modules_root: Path | str | None = None) -> ModuleManifest | None:
    return next((m for m in load_manifests(modules_root) if m.code == code), None)


def upload_module(*_args: object, **_kwargs: object) -> None:
    raise NotImplementedError("Module upload is disabled in the MVP (manifest scan only).")
