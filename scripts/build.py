#!/usr/bin/env python3
"""Build AUR packages from configuration files."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]
from jinja2 import Template  # type: ignore[import-untyped]

from upstream import fetch
import aur


def select_template(cfg: dict[str, Any]) -> str:
    if cfg["type"] == "appimage":
        return "templates/appimage.PKGBUILD.j2"
    if cfg["type"] == "debian":
        return "templates/debian.PKGBUILD.j2"
    if cfg["type"] == "pypi":
        return "templates/pypi.PKGBUILD.j2"
    if cfg["type"] == "npm":
        return "templates/npm.PKGBUILD.j2"
    if cfg["type"] == "binary":
        return "templates/binary.PKGBUILD.j2"
    raise RuntimeError("Unknown package type")


def default_state(pkgname: str) -> dict[str, Any]:
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        return default_state(pkgname)
    return json.load(open(path))


def save_state(path: str, state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state["last_updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    json.dump(state, open(path, "w"), indent=2)


def _process_shell_wrapper(cfg: dict[str, Any]) -> dict[str, str] | None:
    if not cfg:
        return None
    name = cfg.get("name", "")
    entry = cfg.get("entry", "")
    interpreter = cfg.get("interpreter", "bun")
    if not name or not entry:
        return None
    content = f'#!/bin/bash\nexec {interpreter} run {entry} "$@"'
    return {"name": name, "content": content}


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


def render_pkgbuild(cfg: dict[str, Any], pkgver: str, pkgrel: int, download_url: str, checksum: str) -> str:
    """Render a package's full PKGBUILD text (pure — no writing, no state, no network).

    Dispatches to the actions engine for ``type: actions``, otherwise renders the
    per-type Jinja template. Kept side-effect free so it can be called both to compare
    against the AUR's live PKGBUILD and to produce the final artifact.
    """
    if cfg["type"] == "actions":
        from actions import render as render_actions
        return render_actions(cfg, pkgver, pkgrel)

    project_root = Path(__file__).parent.parent
    tmpl_path = select_template(cfg)
    if not Path(tmpl_path).is_absolute():
        tmpl_path = project_root / tmpl_path
    tmpl = Template(Path(tmpl_path).read_text())

    debian_config = cfg.get("debian", {})
    appimage_config = cfg.get("appimage", {})
    binary_config = cfg.get("binary", {})

    cfg_copy = {k: v for k, v in cfg.items() if k not in ("pypi", "npm", "appimage", "debian", "binary", "upstream", "install_files", "systemd_service", "shell_wrapper")}
    for key in ("depends", "makedepends", "options", "conflicts", "provides"):
        cfg_copy.setdefault(key, [])
    return tmpl.render(
        **cfg_copy,
        pkgver=pkgver,
        pkgrel=pkgrel,
        download_url=download_url,
        sha256=checksum,
        debian_config=debian_config,
        deb_version=debian_config.get("deb_version", ""),
        extract_method=debian_config.get("extract_method", "ar"),
        appimage_name=appimage_config.get("appimage_name", f"{appimage_config.get('binary_name', 'app')}.AppImage"),
        binary_name=cfg.get("npm", {}).get("binary_name", "") or appimage_config.get("binary_name", "") or binary_config.get("binary_name", ""),
        desktop=appimage_config.get("desktop", False),
        icons=appimage_config.get("icons", False),
        package_manager=(cfg.get("pypi", {}) or {}).get("package_manager", "pip") if cfg.get("type") == "pypi" else (cfg.get("npm", {}) or {}).get("package_manager", "npm"),
        pypi_name=cfg.get("upstream", {}).get("pypi_name", ""),
        npm_name=cfg.get("upstream", {}).get("npm_name", ""),
        _pypi_name=cfg.get("upstream", {}).get("pypi_name", cfg.get("pkgname", "")),
        install_files=cfg.get("install_files", []),
        systemd_service=cfg.get("systemd_service", ""),
        extract=(cfg.get("upstream", {}) or {}).get("extract", "none"),
    )


def _pkgbuild_signature(text: str) -> str:
    """Normalize a PKGBUILD for change detection: drop pkgrel/checksum lines and blanks.

    Two PKGBUILDs with the same signature package the same thing — only pkgrel or the
    source checksum differs, which never on its own warrants a republish.
    """
    skip = ("pkgrel=", "sha256sums=", "sha512sums=", "b2sums=", "md5sums=")
    return "\n".join(
        s for s in (line.strip() for line in text.splitlines())
        if s and not s.startswith(skip)
    )


def _split_version(version: str) -> tuple[str | None, int]:
    """Split an AUR 'pkgver-pkgrel' string into (pkgver, pkgrel int). Defaults pkgrel=1."""
    if not version:
        return None, 1
    if "-" in version:
        ver, rel = version.rsplit("-", 1)
        try:
            return ver, int(rel)
        except ValueError:
            return ver, 1
    return version, 1


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

    project_root = Path(__file__).parent.parent
    state_path = project_root / "state" / f"{pkgname}.json"
    state = load_state(str(state_path), pkgname)

    # Determine if this is truly a new package
    last_version = state.get("last_version")

    if last_version is not None:
        print(f"[{pkgname}] 📦 Last known version: {last_version}")

    try:
        fetch_result = fetch(cfg)
        # Handle both 3-tuple (old) and 4-tuple (new with sha256)
        if len(fetch_result) == 4:
            tag, url, asset_id, upstream_sha256 = fetch_result
        else:
            tag, url, asset_id = fetch_result
            upstream_sha256 = None

        print(f"[{pkgname}] 🌐 Fetched upstream version: {tag}")
        print(f"[{pkgname}] 🔗 Download URL: {url}")

        # Target pkgver (Arch cannot contain hyphens/colons/slashes/whitespace).
        pkgver = (tag or "0").replace("-", ".").replace(":", ".")

        project_root = Path(__file__).parent.parent
        outdir = project_root / "build" / pkgname

        # Render what we WOULD publish (pkgrel/checksum-agnostic) to get a comparable
        # signature. Cheap — no source download happens for this comparison render.
        compare = render_pkgbuild(cfg, pkgver, 1, url, upstream_sha256 or "SKIP")
        sig = _pkgbuild_signature(compare)

        # Authoritative, clone-free decision from what the AUR actually has (RPC for the
        # version, cgit for the live PKGBUILD — no clone, no local-state dependence):
        #   not published          -> create (pkgrel 1)
        #   published, identical    -> skip (covers unchanged -git/VCS packages)
        #   published, differs:
        #       same pkgver         -> packaging changed: bump pkgrel (republish the fix)
        #       new pkgver          -> upstream update: pkgrel 1
        aur_ver, aur_rel, in_aur, live = None, 1, False, None
        try:
            aur_data = aur.info(pkgname)
            if aur_data:
                in_aur = True
                aur_ver, aur_rel = _split_version(aur_data.get("Version", ""))
                live = aur.remote_pkgbuild(pkgname)
        except Exception as e:
            print(f"[{pkgname}] ⚠️  AUR check failed ({e}); treating as needing publish")

        if in_aur and live is not None and _pkgbuild_signature(live) == sig:
            print(f"[{pkgname}] ✅ AUR already up to date at {aur_ver}-{aur_rel} - skipping (no clone)")
            state.update({"last_version": tag, "last_success": True, "last_error": None})
            save_state(state_path, state)
            return None

        is_new_package = not in_aur
        if not in_aur:
            pkgrel = 1
            print(f"[{pkgname}] ✨ NEW PACKAGE - Will be created ({pkgver})")
        elif aur_ver == pkgver:
            pkgrel = aur_rel + 1
            print(f"[{pkgname}] 🩹 Same version {pkgver}, packaging changed → pkgrel {aur_rel} → {pkgrel}")
        else:
            pkgrel = 1
            print(f"[{pkgname}] 🔄 VERSION CHANGE: {aur_ver} → {pkgver}")

        # Real checksum (download only now that we know we're publishing).
        if upstream_sha256:
            checksum = upstream_sha256
        else:
            print(f"[{pkgname}] 📥 Calculating SHA256 checksum...")
            checksum = sha256(url)

        print(f"[{pkgname}] 🎨 Rendering PKGBUILD (pkgrel={pkgrel})...")
        rendered = render_pkgbuild(cfg, pkgver, pkgrel, url, checksum)

        os.makedirs(outdir, exist_ok=True)
        pkgbuild_path = outdir / "PKGBUILD"
        Path(pkgbuild_path).write_text(rendered)
        print(f"[{pkgname}] ✅ Generated PKGBUILD at: {pkgbuild_path}")

        print(f"[{pkgname}] 📄 PKGBUILD preview (first 10 lines):")
        for line in rendered.split('\n')[:10]:
            print(f"         {line}")

        state.update({
            "last_version": tag,
            "last_asset_id": asset_id,
            "last_success": True,
            "last_error": None,
            "retry_count": 0
        })
        save_state(state_path, state)

        status = "created" if is_new_package else "updated"
        print(f"[{pkgname}] ✅ SUCCESS - Package {status.upper()} (version {tag}-{pkgrel})")
        return {"pkgname": pkgname, "status": status}

    except Exception as e:
        print(f"[{pkgname}] ❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        print(f"[{pkgname}] 📋 Traceback:")
        for line in traceback.format_exc().split('\n'):
            print(f"         {line}")
        state["last_success"] = False
        state["last_error"] = str(e)
        state["retry_count"] += 1

        save_state(state_path, state)

        return {"pkgname": pkgname, "error": str(e)}