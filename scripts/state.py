#!/usr/bin/env python3
"""State management for package builds."""

import json
import os
from datetime import datetime, timezone
from typing import Any


def default_state(pkgname: str) -> dict[str, Any]:
    """Create a default state dictionary for a package.
    
    Args:
        pkgname: The name of the package.
        
    Returns:
        A dictionary with default state values.
    """
    return {
        "pkgname": pkgname,
        "last_version": None,
        "last_asset_id": None,
        "last_commit_sha": None,
        "last_updated": None,
        "last_success": False,
        "last_error": None,
        "retry_count": 0
    }


def load_state(path: str, pkgname: str) -> dict[str, Any]:
    """Load state from a JSON file or create default state.
    
    Args:
        path: Path to the state JSON file.
        pkgname: The name of the package.
        
    Returns:
        The loaded state dictionary or a new default state.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        return default_state(pkgname)

    return json.load(open(path))


def save_state(path: str, state: dict[str, Any]) -> None:
    """Save state to a JSON file.
    
    Args:
        path: Path to the state JSON file.
        state: The state dictionary to save.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    state["last_updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    json.dump(state, open(path, "w"), indent=2)