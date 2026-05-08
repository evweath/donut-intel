"""
Configuration management for Donut Intel Platform.
Loads settings.yaml and supports environment variable overrides.
DB path is fully configurable to support Google Drive shared storage.
"""
import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

# Environment variable overrides: ENV_VAR -> yaml key path
_ENV_OVERRIDES = {
    "DONUT_INTEL_DB_PATH": ["database", "path"],
    "DONUT_INTEL_PORT": ["app", "port"],
    "DONUT_INTEL_HOST": ["app", "host"],
    "DONUT_INTEL_SECRET": ["app", "secret_key"],
    "ANTHROPIC_API_KEY": ["anthropic", "api_key"],
    "DONUT_INTEL_LOG_LEVEL": ["logging", "level"],
}


def _deep_get(d: dict, *keys, default=None) -> Any:
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
        if d is None:
            return default
    return d


def _deep_set(d: dict, keys: list, value: Any) -> None:
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


class Config:
    _instance: Optional["Config"] = None
    _settings: Dict[str, Any]

    def __new__(cls) -> "Config":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._settings = {}
            instance._load()
            cls._instance = instance
        return cls._instance

    def _load(self) -> None:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh)
                self._settings = loaded if isinstance(loaded, dict) else {}
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        for env_var, keys in _ENV_OVERRIDES.items():
            val = os.environ.get(env_var)
            if val is not None:
                _deep_set(self._settings, keys, val)

    def get(self, *keys: str, default: Any = None) -> Any:
        return _deep_get(self._settings, *keys, default=default)

    def set(self, *keys_and_value: Any) -> None:
        """Usage: config.set("section", "key", value)"""
        if len(keys_and_value) < 2:
            raise ValueError("set() requires at least one key and a value")
        keys = list(keys_and_value[:-1])
        value = keys_and_value[-1]
        _deep_set(self._settings, keys, value)
        self._save()

    def _save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            yaml.dump(
                self._settings,
                fh,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    def reload(self) -> None:
        self._load()

    def all(self) -> Dict[str, Any]:
        return copy.deepcopy(self._settings)

    def db_path(self) -> Path:
        """Return resolved, absolute DB path. Expands ~ for home directory."""
        raw = self.get("database", "path", default="./data/donut_intel.db")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            # Resolve relative to project root
            path = (CONFIG_PATH.parent.parent / path).resolve()
        return path

    def is_feature_enabled(self, feature_key: str) -> bool:
        return bool(self.get("features", feature_key, default=True))


# Module-level singleton
config = Config()
