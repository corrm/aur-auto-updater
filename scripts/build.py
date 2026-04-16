#!/usr/bin/env python3
"""Build AUR packages from configuration files."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]
from jinja2 import Template  # type: ignore[import-untyped]

from upstream import fetch
from template import select_template
from aur import exists as aur_exists


def sha256(url: str) -> str:
    """Calculate SHA256 checksum of a downloadable file.

    Args:
        url: URL to download

    Returns:
        Hexadecimal SHA256 checksum string

    Raises:
        requests.RequestException: If download fails
    """
    print(f"  [Checksum] Downloading for SHA256: {url}")
    r = requests.get(url, timeout=120, stream=True)
    r.raise_for_status()

    hasher = hashlib.sha256()
    total_size = int(r.headers.get('content-length', 0))
    downloaded = 0

    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            hasher.update(chunk)
            downloaded += len(chunk)
            # Show progress for large files
            if total_size > 0 and downloaded % (10 * 1024 * 1024) < 8192:
                percent = (downloaded / total_size) * 100
                print(f"  [Checksum] Progress: {downloaded // (1024*1024)}MB / {total_size // (1024*1024)}MB ({percent:.1f}%)")

    checksum = hasher.hexdigest()
    print(f"  [Checksum] SHA256: {checksum}")
    return checksum


def build(pkgfile: str) -> dict[str, str] | None:
    """Build a package from configuration file.

    Args:
        pkgfile: Path to YAML package configuration file

    Returns:
        Dictionary with 'pkgname' and 'status'/'error' keys, or None if no update needed

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid YAML
    """
    print(f"\n{'='*60}")
    print(f"[BUILD] Processing: {pkgfile}")
    print(f"{'='*60}")

    cfg = yaml.safe_load(Path(pkgfile).read_text())
    pkgname = cfg["pkgname"]

    print(f"[{pkgname}] Package name: {pkgname}")
    print(f"[{pkgname}] Type: {cfg.get('type', 'unknown')}")

    # Check if package exists in AUR (not just local state)
    print(f"[{pkgname}] 🔍 Checking AUR existence...")
    in_aur = aur_exists(pkgname)
    
    # Handle SSH auth failure case (exists() returns None)
    if in_aur is None:
        print(f"[{pkgname}] ⚠️  Cannot verify AUR existence - SSH auth failed")
        print(f"[{pkgname}] ℹ️  Ensure AUR_SSH_PRIVATE_KEY is set in GitHub secrets")
        print(f"[{pkgname}] ⚠️  Will process package (safe mode: assumes update needed)")
        in_aur = False  # Treat as not in AUR to allow processing
    
    # Determine if this is truly a new package
    last_version = None
    is_new_package = not in_aur
    
    if in_aur:
        print(f"[{pkgname}] 📦 Package EXISTS in AUR")
        # Fetch current version from AUR PKGBUILD to compare
        try:
            import subprocess
            result = subprocess.run(
                ["git", "ls-remote", f"ssh://aur@aur.archlinux.org/{pkgname}.git"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                # Clone temporarily to read PKGBUILD
                temp_repo = f"/tmp/aur-{pkgname}"
                if os.path.exists(temp_repo):
                    shutil.rmtree(temp_repo)
                os.makedirs(temp_repo)
                subprocess.check_call(
                    ["git", "clone", "--depth", "1", f"ssh://aur@aur.archlinux.org/{pkgname}.git", temp_repo],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                pkgbuild_path = f"{temp_repo}/PKGBUILD"
                if os.path.exists(pkgbuild_path):
                    content = Path(pkgbuild_path).read_text()
                    # Extract pkgver from PKGBUILD
                    for line in content.split('\n'):
                        if line.startswith('pkgver='):
                            last_version = line.split('=', 1)[1].strip()
                            break
                    print(f"[{pkgname}] 📦 Current AUR version: {last_version}")
                shutil.rmtree(temp_repo)
        except Exception as e:
            print(f"[{pkgname}] ⚠️  Could not fetch AUR version: {e}")
    else:
        print(f"[{pkgname}] ✨ NEW PACKAGE - Will be created")

    try:
        tag, url, asset_id = fetch(cfg)

        print(f"[{pkgname}] 🌐 Fetched upstream version: {tag}")
        print(f"[{pkgname}] 🔗 Download URL: {url}")

        # Compare versions - skip if version unchanged (only for existing packages)
        if not is_new_package and last_version == tag:
            print(f"[{pkgname}] ✅ UP TO DATE - No changes detected")
            print(f"[{pkgname}] ℹ️  Skipping build (version {tag} already in AUR)")
            return None
        
        if not is_new_package:
            print(f"[{pkgname}] 🔄 Version change detected: {last_version} → {tag}")
        
        if is_new_package:
            print(f"[{pkgname}] 🆕 VERSION CHANGE: None → {tag} (NEW PACKAGE)")
        else:
            print(f"[{pkgname}] 🔄 VERSION CHANGE: {last_version} → {tag}")

        print(f"[{pkgname}] 📥 Calculating SHA256 checksum...")
        checksum = sha256(url)

        tmpl_path = select_template(cfg)
        print(f"[{pkgname}] 📝 Using template: {tmpl_path}")

        tmpl = Template(Path(tmpl_path).read_text())

        pkgver = tag or "0"

        # Pass debian config if available
        debian_config = cfg.get("debian", {})

        print(f"[{pkgname}] 🎨 Rendering PKGBUILD template...")
        rendered = tmpl.render(
            **cfg,
            pkgver=pkgver,
            download_url=url,
            sha256=checksum,
            debian_config=debian_config
        )

        outdir = f"build/{pkgname}"
        os.makedirs(outdir, exist_ok=True)

        pkgbuild_path = f"{outdir}/PKGBUILD"
        Path(pkgbuild_path).write_text(rendered)
        print(f"[{pkgname}] ✅ Generated PKGBUILD at: {pkgbuild_path}")

        # Show PKGBUILD preview
        print(f"[{pkgname}] 📄 PKGBUILD preview (first 10 lines):")
        for i, line in enumerate(rendered.split('\n')[:10], 1):
            print(f"         {line}")
        if len(rendered.split('\n')) > 10:
            print(f"         ... ({len(rendered.split(chr(10))) - 10} more lines)")

        # Determine status based on whether this is a new package or update
        status = "created" if is_new_package else "updated"
        status_emoji = "✨" if is_new_package else "🔄"
        print(f"[{pkgname}] {status_emoji} SUCCESS - Package {status.upper()} (version {tag})")

        return {"pkgname": pkgname, "status": status}

    except Exception as e:
        print(f"[{pkgname}] ❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        print(f"[{pkgname}] 📋 Traceback:")
        for line in traceback.format_exc().split('\n'):
            print(f"         {line}")

        return {"pkgname": pkgname, "error": str(e)}

        return {"pkgname": pkgname, "error": str(e)}