#!/usr/bin/env python3
"""Template selection logic."""

from typing import Any


def select_template(cfg: dict[str, Any]) -> str:
    """Select the appropriate PKGBUILD template based on package configuration.
    
    Args:
        cfg: Package configuration dictionary.
        
    Returns:
        Path to the selected template file.
        
    Raises:
        RuntimeError: If the package type is not supported.
    """
    if cfg["type"] == "appimage":
        return "templates/appimage.PKGBUILD.j2"

    if cfg["type"] == "debian":
        return "templates/debian.PKGBUILD.j2"

    raise RuntimeError("Unknown package type")