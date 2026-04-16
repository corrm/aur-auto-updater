#!/usr/bin/env python3
"""Fetch upstream package information from various providers."""

import re
from typing import Any

import requests  # type: ignore[import-untyped]


def github_latest(repo: str, asset_regex: str) -> tuple[str, str, int]:
    """Fetch the latest release information from GitHub.
    
    Args:
        repo: The repository name in format 'owner/repo'.
        asset_regex: Regular expression to match the asset name.
        
    Returns:
        A tuple of (tag, download_url, asset_id).
        
    Raises:
        requests.RequestException: If the API request fails.
        RuntimeError: If no matching asset is found.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    data = r.json()
    tag = data["tag_name"].lstrip("v")

    for a in data["assets"]:
        if re.match(asset_regex, a["name"]):
            return tag, a["browser_download_url"], a["id"]

    raise RuntimeError("No matching asset found")


def fetch(cfg: dict[str, Any]) -> tuple[str | None, str, int | None]:
    """Fetch upstream information based on package configuration.
    
    Args:
        cfg: Package configuration dictionary.
        
    Returns:
        A tuple of (tag, download_url, asset_id).
        
    Raises:
        RuntimeError: If the provider is not supported.
    """
    upstream = cfg["upstream"]

    if upstream["provider"] == "github":
        return github_latest(upstream["repo"], upstream["asset_regex"])

    if upstream["provider"] == "url":
        # minimal direct URL mode
        return None, upstream["url"], None

    raise RuntimeError("Unsupported provider")