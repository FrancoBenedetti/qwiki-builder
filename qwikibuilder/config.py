"""
Configuration management for Qwiki Builder.
Supports multiple named profiles, global system config, local project configs,
and environment variables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def get_global_config_dir() -> Path:
    """Returns the global configuration directory (~/.config/qwiki-builder or %APPDATA%/qwiki-builder)."""
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    config_dir = base / "qwiki-builder"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_global_config_path() -> Path:
    """Returns path to the global config.json file."""
    return get_global_config_dir() / "config.json"


def load_global_config() -> Dict[str, Any]:
    """Loads the global configuration JSON file if it exists, or returns empty dict."""
    path = get_global_config_path()
    if not path.is_file():
        return {"profiles": {}, "default_profile": "default"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"profiles": {}, "default_profile": "default"}
        if "profiles" not in data or not isinstance(data["profiles"], dict):
            data["profiles"] = {}
        if "default_profile" not in data:
            data["default_profile"] = "default"
        return data
    except Exception:
        return {"profiles": {}, "default_profile": "default"}


def save_global_config(config_data: Dict[str, Any]) -> None:
    """Saves the global configuration JSON file safely."""
    path = get_global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    temp_path.replace(path)


def set_profile(
    profile_name: str,
    wiki_url: str,
    api_key: str,
    set_default: bool = False,
) -> None:
    """Adds or updates a named profile in the global configuration."""
    clean_name = profile_name.strip() or "default"
    clean_url = wiki_url.strip().rstrip("/")
    clean_key = api_key.strip()

    cfg = load_global_config()
    cfg["profiles"][clean_name] = {
        "url": clean_url,
        "api_key": clean_key,
    }
    if set_default or "default_profile" not in cfg or not cfg.get("default_profile"):
        cfg["default_profile"] = clean_name
    save_global_config(cfg)


def delete_profile(profile_name: str) -> bool:
    """Deletes a named profile from global config."""
    cfg = load_global_config()
    if profile_name in cfg.get("profiles", {}):
        del cfg["profiles"][profile_name]
        if cfg.get("default_profile") == profile_name:
            remaining = list(cfg["profiles"].keys())
            cfg["default_profile"] = remaining[0] if remaining else "default"
        save_global_config(cfg)
        return True
    return False


def get_profile(profile_name: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Retrieves profile details by name, falling back to default profile."""
    cfg = load_global_config()
    profiles = cfg.get("profiles", {})
    target = profile_name or cfg.get("default_profile", "default")
    return profiles.get(target)


def list_profiles() -> Dict[str, Dict[str, str]]:
    """Returns all stored profiles in global config."""
    cfg = load_global_config()
    return cfg.get("profiles", {})


def resolve_credentials(
    explicit_url: Optional[str] = None,
    explicit_key: Optional[str] = None,
    profile_name: Optional[str] = None,
    project_url: Optional[str] = None,
    project_key: Optional[str] = None,
    project_profile: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Resolves the target Qwiki URL and API Key in priority order:
    1. Explicit CLI arguments (--url, --key)
    2. Explicit CLI profile (--profile)
    3. Project file url / key
    4. Project profile name
    5. Environment variables (QWIKI_URL, QWIKI_API_KEY, QWIKI_PROFILE)
    6. Global default profile from ~/.config/qwiki-builder/config.json
    """
    final_url = (explicit_url or "").strip()
    final_key = (explicit_key or "").strip()

    # Step 1: Check if explicit CLI url and key already provided
    if final_url and final_key:
        return final_url.rstrip("/"), final_key

    # Step 2: Try explicit profile
    target_profile = profile_name or os.getenv("QWIKI_PROFILE") or project_profile
    if target_profile:
        prof = get_profile(target_profile)
        if prof:
            if not final_url and prof.get("url"):
                final_url = prof["url"]
            if not final_key and prof.get("api_key"):
                final_key = prof["api_key"]

    # Step 3: Local project config overrides
    if not final_url and project_url:
        final_url = project_url.strip()
    if not final_key and project_key:
        final_key = project_key.strip()

    # Step 4: Environment variables
    if not final_url:
        final_url = (os.getenv("QWIKI_URL") or os.getenv("QWIKI_BASE_URL") or "").strip()
    if not final_key:
        final_key = (os.getenv("QWIKI_API_KEY") or os.getenv("QWIKI_KEY") or "").strip()

    # Step 5: Global default profile fallback
    if not final_url or not final_key:
        def_prof = get_profile(None)
        if def_prof:
            if not final_url and def_prof.get("url"):
                final_url = def_prof["url"]
            if not final_key and def_prof.get("api_key"):
                final_key = def_prof["api_key"]

    if not final_url:
        raise ValueError(
            "Target Qwiki URL not configured. Specify via --url, in qwiki-project.json, "
            "via QWIKI_URL env var, or configure a profile with 'qwiki-builder config --url <url>'."
        )
    if not final_key:
        raise ValueError(
            "Qwiki API key not configured. Specify via --key, in qwiki-project.json, "
            "via QWIKI_API_KEY env var, or configure a profile with 'qwiki-builder config --key <key>'."
        )

    return final_url.rstrip("/"), final_key
