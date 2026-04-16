#!/usr/bin/env python3
"""Build package PKGBUILD files from YAML configurations."""

import hashlib
import os
from typing import Any

import requests  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]
from jinja2 import Template  # type: ignore[import-untyped]

from upstream import fetch
from state import load_state, save_state
from template import select_template


def sha256(url: str) -> str:
    """Download a file from URL and return its SHA256 hash.
    
    Args:
        url: The URL to download from.
        
    Returns:
        SHA256 hash of the downloaded content.
        
    Raises:
        requests.RequestException: If the download fails.
    """
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return hashlib.sha256(r.content).hexdigest()


def build(pkgfile: str) -> dict[str, Any] | None:
    """Build a PKGBUILD file for the given package configuration.
    
    Args:
        pkgfile: Path to the package YAML file.
        
    Returns:
        A dictionary with status information, or None if no update needed.
    """
    cfg = yaml.safe_load(open(pkgfile))

    pkgname = cfg["pkgname"]
    state_path = f"state/{pkgname}.json"

    state = load_state(state_path, pkgname)

    try:
        tag, url, asset_id = fetch(cfg)

        if state.get("last_version") == tag:
            state["last_success"] = True
            state["last_error"] = None
            save_state(state_path, state)
            return None

        checksum = sha256(url)

        tmpl_path = select_template(cfg)
        tmpl = Template(open(tmpl_path).read())

        pkgver = tag or "0"

        rendered = tmpl.render(
            **cfg,
            pkgver=pkgver,
            download_url=url,
            sha256=checksum,
            debian_config=cfg.get("debian", {})
        )

        outdir = f"build/{pkgname}"
        os.makedirs(outdir, exist_ok=True)

        open(f"{outdir}/PKGBUILD", "w").write(rendered)

        state.update({
            "last_version": tag,
            "last_asset_id": asset_id,
            "last_success": True,
            "last_error": None,
            "retry_count": 0
        })

        save_state(state_path, state)

        return {"pkgname": pkgname, "status": "updated"}

    except Exception as e:
        state["last_success"] = False
        state["last_error"] = str(e)
        state["retry_count"] += 1

        save_state(state_path, state)

        return {"pkgname": pkgname, "error": str(e)}