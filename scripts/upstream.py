#!/usr/bin/env python3
"""Fetch upstream version information for packages."""
from __future__ import annotations

import re
from typing import Any

import requests  # type: ignore[import-untyped]


def github_latest(repo: str, asset_regex: str) -> tuple[str | None, str, int | None]:
    """Fetch latest release info from GitHub.

    Args:
        repo: GitHub repository in format 'owner/repo'
        asset_regex: Regex pattern to match asset name

    Returns:
        Tuple of (tag_name or None, download_url, asset_id or None)

    Raises:
        RuntimeError: If no matching asset is found
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    print(f"  [GitHub] 📡 Fetching latest release from: {repo}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    data = r.json()
    raw_tag = data["tag_name"]
    tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')

    print(f"  [GitHub] 🏷️  Found tag: {tag} (from {raw_tag})")

    for a in data["assets"]:
        if re.match(asset_regex, a["name"]):
            print(f"  [GitHub] ✅ Matching asset: {a['name']}")
            return tag, a["browser_download_url"], a["id"]

    raise RuntimeError(f"No matching asset found (pattern: {asset_regex})")


def pypi_latest(package_name: str) -> tuple[str | None, str, None]:
    """Fetch latest version and download URL from PyPI.

    Args:
        package_name: PyPI package name

    Returns:
        Tuple of (version, download_url, None)

    Raises:
        RuntimeError: If package not found or fetch fails
    """
    print(f"  [PyPI] 📡 Fetching package info: {package_name}")
    url = f"https://pypi.org/pypi/{package_name}/json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    data = r.json()
    info = data["info"]
    version = info["version"]

    print(f"  [PyPI] 🏷️  Found version: {version}")

    if info.get("urls"):
        download_url = info["urls"][0]["filename"]
        wheel_url = f"https://files.pythonhosted.org/packages/{download_url}"
    else:
        pypi_name = package_name.lower().replace("_", "-")
        wheel_url = f"https://files.pythonhosted.org/packages/source/{pypi_name[0]}/{pypi_name}/{pypi_name}-{version}.tar.gz"

    print(f"  [PyPI] ✅ Download URL: {wheel_url}")
    return version, wheel_url, None


def npm_latest(package_name: str) -> tuple[str | None, str, None]:
    """Fetch latest version and download URL from npm.

    Args:
        package_name: npm package name

    Returns:
        Tuple of (version, download_url, None)

    Raises:
        RuntimeError: If package not found or fetch fails
    """
    print(f"  [npm] 📡 Fetching package info: {package_name}")
    url = f"https://registry.npmjs.org/{package_name}/latest"
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    data = r.json()
    version = data["version"]

    print(f"  [npm] 🏷️  Found version: {version}")

    tarball_url = data["dist"]["tarball"]
    print(f"  [npm] ✅ Download URL: {tarball_url}")
    return version, tarball_url, None


def debian_latest(base_url: str, pkg_pattern: str) -> str | None:
    """Fetch latest Debian package version from package listing page.

    Args:
        base_url: Base URL of the Debian package pool directory
        pkg_pattern: Pattern to match package files (e.g., 'gdb-mingw-w64')

    Returns:
        Latest version string in format 'upstream_version-debian_revision'

    Raises:
        RuntimeError: If version cannot be extracted from page
    """
    print(f"  [Debian] 📡 Fetching package list from: {base_url}")
    r = requests.get(base_url, timeout=30)
    r.raise_for_status()

    # Parse HTML to find .deb files and extract versions
    # Pattern matches: pkgname_version_arch.deb
    deb_pattern = re.compile(rf'({re.escape(pkg_pattern)})_([0-9][^"_\s]+(?:\+[0-9][^"_\s]+)?)_.*\.deb')

    versions = []
    for match in deb_pattern.finditer(r.text):
        version = match.group(2)
        versions.append(version)
        print(f"  [Debian] 🔍 Found version: {version}")

    if not versions:
        # Fallback: try simpler pattern for version extraction from links
        link_pattern = re.compile(rf'href="({re.escape(pkg_pattern)}_[^"]+\.deb)"')
        for match in link_pattern.finditer(r.text):
            filename = match.group(1)
            # Extract version from filename: pkgname_version_arch.deb
            parts = filename.replace('.deb', '').split('_')
            if len(parts) >= 2:
                version = parts[1]
                versions.append(version)
                print(f"  [Debian] 🔍 Found version (fallback): {version}")

    if not versions:
        raise RuntimeError(f"No Debian package versions found at {base_url}")

    # Return the last (typically newest) version
    latest = versions[-1]
    print(f"  [Debian] ✅ Latest version: {latest}")
    return latest


def fetch(cfg: dict[str, Any]) -> tuple[str | None, str, int | None]:
    """Fetch upstream version and download URL based on configuration.

    Args:
        cfg: Package configuration dictionary

    Returns:
        Tuple of (version_tag or None, download_url, asset_id or None)

    Raises:
        RuntimeError: If provider is unsupported or fetch fails
    """
    upstream = cfg["upstream"]
    provider = upstream["provider"]

    print(f"\n[Upstream] 🌍 Fetching from provider: {provider}")

    if provider == "github":
        return github_latest(upstream["repo"], upstream["asset_regex"])

    if provider == "pypi":
        pypi_name = upstream.get("pypi_name", cfg["pkgname"])
        return pypi_latest(pypi_name)

    if provider == "npm":
        npm_name = upstream.get("npm_name", cfg["pkgname"])
        return npm_latest(npm_name)

    if provider == "url":
        base_url = upstream["url"]

        # Check if this is a Debian package URL
        if "debian.org" in base_url or "debian.net" in base_url:
            # Extract package pattern from URL or config
            pkg_pattern = upstream.get("pkg_pattern", "gdb-mingw-w64")
            version = debian_latest(base_url, pkg_pattern)

            # Construct the actual .deb download URL
            # Find the actual .deb file URL from the listing page
            print(f"  [Debian] 🔗 Locating .deb file for version {version}...")
            r = requests.get(base_url, timeout=30)
            r.raise_for_status()

            deb_pattern = re.compile(rf'href="({re.escape(pkg_pattern)}_{re.escape(version)}_[^"]+\.deb)"')
            match = deb_pattern.search(r.text)
            if match:
                deb_file = match.group(1)
                # Ensure base_url ends with /
                if not base_url.endswith('/'):
                    base_url += '/'
                download_url = base_url + deb_file
                print(f"  [Debian] ✅ Download URL: {download_url}")
                return version, download_url, None

            raise RuntimeError(f"Could not find .deb file for version {version}")

        # For simple direct URL mode (non-Debian)
        print(f"  [URL] ℹ️  Using direct URL: {base_url}")
        return None, base_url, None

    raise RuntimeError(f"Unsupported provider: {provider}")