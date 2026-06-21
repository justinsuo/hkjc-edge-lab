"""Configuration loading.

Loads config/config.yaml, applies optional .env overrides (keys prefixed HKJC_,
underscores map to nested keys, e.g. HKJC_HTTP_USER_AGENT -> http.user_agent),
and resolves relative paths against the project root.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# Project root = parent of this package directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@dataclass
class Config:
    """Thin wrapper around the parsed config dict with dotted access + path resolution."""

    raw: dict[str, Any]
    root: Path

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str, default: str | None = None) -> Path:
        """Resolve a config value that is a filesystem path, relative to project root."""
        val = self.get(dotted, default)
        if val is None:
            raise KeyError(f"No path configured at {dotted!r}")
        p = Path(val)
        return p if p.is_absolute() else (self.root / p)

    @property
    def db_path(self) -> Path:
        return self.path("database.path")


def _apply_env_overrides(cfg: dict[str, Any]) -> None:
    """Override nested config from HKJC_* env vars. HKJC_HTTP_USER_AGENT -> http.user_agent.

    We only override keys that ALREADY exist in the YAML (so typos don't silently create
    config), matching by walking the tree and joining nested keys with '_'.
    """
    # Build a lookup from HKJC_<UPPER_JOINED> -> (parent_dict, leaf_key) for existing leaves.
    index: dict[str, tuple[dict[str, Any], str]] = {}

    def walk(node: dict[str, Any], prefix: str) -> None:
        for k, v in node.items():
            joined = f"{prefix}_{k}" if prefix else k
            if isinstance(v, dict):
                walk(v, joined)
            else:
                index["HKJC_" + joined.upper()] = (node, k)

    walk(cfg, "")
    for env_key, (parent, leaf) in index.items():
        if env_key in os.environ:
            raw = os.environ[env_key]
            # Preserve simple types from the existing value.
            existing = parent[leaf]
            try:
                if isinstance(existing, bool):
                    parent[leaf] = raw.strip().lower() in {"1", "true", "yes", "on"}
                elif isinstance(existing, int):
                    parent[leaf] = int(raw)
                elif isinstance(existing, float):
                    parent[leaf] = float(raw)
                else:
                    parent[leaf] = raw
            except ValueError:
                parent[leaf] = raw


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from YAML + .env overrides."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if load_dotenv is not None:
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    with open(cfg_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    _apply_env_overrides(data)
    return Config(raw=data, root=PROJECT_ROOT)
