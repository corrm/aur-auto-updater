#!/usr/bin/env python3
"""Fetch upstream version information for packages."""
from __future__ import annotations

import re
from typing import Any

import requests  # type: ignore[import-untyped]

# Default arch mapping: Arch names -> GitHub asset names
DEFAULT_ARCH_MAP = {
    "x86_64": "amd64",
    "aarch64": "arm64",
}


def github_latest(repo: str, asset_regex: str, interpolate: dict[str, str] | None = None) -> tuple[str | None, str, int | None, str | None]:
    """Fetch latest release info from GitHub.

    Args:
        repo: GitHub repository in format 'owner/repo'
        asset_regex: Regex pattern to match asset name (may include ${var} placeholders)
        interpolate: Optional dict of {var_name: value} for interpolation (e.g., {arch: x86_64})

    Returns:
        Tuple of (tag_name or None, download_url, asset_id or None, sha256 or None)

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

    # Build list of arch values to try: original first, then mapped fallback
    arch_values_to_try = []
    if interpolate and "arch" in interpolate:
        original_arch = interpolate["arch"]
        arch_values_to_try.append(original_arch)
        # Try mapped arch if different
        if original_arch in DEFAULT_ARCH_MAP:
            mapped = DEFAULT_ARCH_MAP[original_arch]
            if mapped != original_arch:
                arch_values_to_try.append(mapped)

    # If no interpolation, try once with original regex
    if not arch_values_to_try:
        arch_values_to_try = [None]

    # Try each arch value until we find a match
    for arch_value in arch_values_to_try:
        asset_regex_try = asset_regex
        if arch_value:
            for key, value in {"arch": arch_value}.items():
                placeholder = f"${{{key}}}"
                if placeholder in asset_regex_try:
                    asset_regex_try = asset_regex_try.replace(placeholder, value)

            print(f"  [GitHub] 🔄 Trying arch: {asset_regex_try}")

        for a in data["assets"]:
            if re.match(asset_regex_try, a["name"]):
                # Extract SHA256 from digest field (format: "sha256:...")
                sha256 = None
                digest = a.get("digest", "")
                if digest.startswith("sha256:"):
                    sha256 = digest[7:]  # Remove "sha256:" prefix
                print(f"  [GitHub] ✅ Matching asset: {a['name']}")
                return tag, a["browser_download_url"], a["id"], sha256

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
        asset_regex = upstream["asset_regex"]
        # Build interpolation dict from cfg
        interpolate: dict[str, str] = {}
        arch = cfg.get("arch", ["any"])
        interpolate["arch"] = arch[0] if isinstance(arch, list) else arch
        interpolate["pkgname"] = cfg.get("pkgname", "")
        return github_latest(upstream["repo"], asset_regex, interpolate)

    if provider == "pypi":
        pypi_name = upstream.get("pypi_name", cfg["pkgname"])
        return pypi_latest(pypi_name)

    if provider == "npm":
        npm_name = upstream.get("npm_name", cfg["pkgname"])
        return npm_latest(npm_name)

    if provider == "url":
        base_url = upstream["url"]
        method = upstream.get("method", "GET").upper()
        response_header = upstream.get("response_header")
        
        # Support arch interpolation in URL (e.g., ${arch})
        arch = cfg.get("arch", ["any"])
        arch_value = arch[0] if isinstance(arch, list) else arch
        
        # Apply arch_map if provided
        arch_map = upstream.get("arch_map", {})
        if arch_value in arch_map:
            arch_value = arch_map[arch_value]
        
        base_url = base_url.replace("${arch}", arch_value)

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

        # For URL-based mode with optional header extraction
        # When response_header is specified, always use GET to get proper redirect headers
        if response_header:
            print(f"  [URL] 📡 Fetching with GET (to extract {response_header} header)")
            r = requests.get(base_url, allow_redirects=False, timeout=30)
        else:
            print(f"  [URL] 📡 Fetching with method: {method}")
            if method == "HEAD":
                r = requests.head(base_url, allow_redirects=True, timeout=30)
            else:
                r = requests.get(base_url, allow_redirects=True, timeout=30, stream=True)
        r.raise_for_status()

        # Extract URL from response header if specified
        if response_header:
            download_url = r.headers.get(response_header)
            if not download_url:
                raise RuntimeError(f"Response header '{response_header}' not found in response")
            print(f"  [URL] 🔗 Extracted from {response_header}: {download_url}")
        else:
            download_url = r.url if hasattr(r, 'url') else base_url
            print(f"  [URL] ℹ️  Using direct URL: {download_url}")

        # Extract version from URL if version_pattern is specified
        version = None
        if "version_pattern" in upstream:
            version_match = re.search(upstream["version_pattern"], download_url)
            if version_match:
                version = version_match.group(1)
                print(f"  [URL] 🏷️  Found version: {version}")

        return version, download_url, None

    raise RuntimeError(f"Unsupported provider: {provider}")