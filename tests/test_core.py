"""Unit tests for AUR auto-updater core modules."""
import re
import sys
from typing import Any

import pytest


class TestTagParsing:
    """Tests for tag version extraction from various tag formats."""

    def test_tag_with_v_prefix(self) -> None:
        """Test that 'v1.2.3' becomes '1.2.3'"""
        raw_tag = "v1.2.3"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.2.3"

    def test_tag_with_desktop_prefix(self) -> None:
        """Test that 'desktop-v1.5.6' becomes '1.5.6' - common for desktop apps"""
        raw_tag = "desktop-v1.5.6"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.5.6"

    def test_tag_with_release_prefix(self) -> None:
        """Test that 'release-2.0' becomes '2.0'"""
        raw_tag = "release-2.0"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "2.0"

    def test_tag_plain_version(self) -> None:
        """Test that plain version '2024.01.15' stays unchanged"""
        raw_tag = "2024.01.15"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "2024.01.15"

    def test_tag_with_multiple_prefixes(self) -> None:
        """Test that 'v2.0.0-beta' becomes '2.0.0-beta'"""
        raw_tag = "v2.0.0-beta"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "2.0.0-beta"

    def test_tag_starts_with_dash(self) -> None:
        """Test edge case where stripping leaves leading dash"""
        raw_tag = "-v1.0.0"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.0.0"


class TestVersionConversion:
    """Tests for converting version strings to valid Arch pkgver."""

    def test_hyphen_replaced_with_dot(self) -> None:
        """Test that hyphens are replaced with dots"""
        version = "17.1-3+13.3"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "17.1.3+13.3"

    def test_colon_replaced_with_dot(self) -> None:
        """Test that colons are replaced with dots"""
        version = "1.0:2.0"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "1.0.2.0"

    def test_version_with_slash_not_handled(self) -> None:
        """Test that forward slashes are NOT replaced (known limitation)"""
        version = "1.0/2.0"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "1.0/2.0"

    def test_version_already_valid(self) -> None:
        """Test that valid version passes through unchanged"""
        version = "1.5.6"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "1.5.6"

    def test_version_with_plus_sign(self) -> None:
        """Test that versions with + (semver) work"""
        version = "1.0.0+beta"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "1.0.0+beta"


class TestAssetRegex:
    """Tests for asset matching with regex patterns."""

    def test_appimage_regex_simple(self) -> None:
        """Test simple .AppImage matching"""
        pattern = r".*\.AppImage$"
        assert re.match(pattern, "app-1.0.0-x86_64.AppImage") is not None
        assert re.match(pattern, "app-1.0.0.deb") is None

    def test_appimage_regex_with_arch(self) -> None:
        """Test AppImage regex with architecture in name"""
        pattern = r".*AppImage$"
        assert re.match(pattern, "superset-1.4.7-x86_64.AppImage") is not None
        assert re.match(pattern, "app-1.0.0-aarch64.AppImage") is not None

    def test_appimage_regex_negative(self) -> None:
        """Test that non-AppImage files don't match"""
        pattern = r".*\.AppImage$"
        assert re.match(pattern, "app-1.0.0.Appimage") is None
        assert re.match(pattern, "app-1.0.0.appimage") is None


class TestTemplateSelection:
    """Tests for template selection logic."""

    def test_select_appimage_template(self) -> None:
        """Test that appimage type selects correct template"""
        sys.path.insert(0, 'scripts')
        from template import select_template
        cfg: dict[str, str] = {"type": "appimage"}
        result = select_template(cfg)
        assert "appimage" in result

    def test_select_debian_template(self) -> None:
        """Test that debian type selects correct template"""
        sys.path.insert(0, 'scripts')
        from template import select_template
        cfg: dict[str, str] = {"type": "debian"}
        result = select_template(cfg)
        assert "debian" in result

    def test_unknown_type_raises(self) -> None:
        """Test that unknown type raises RuntimeError"""
        sys.path.insert(0, 'scripts')
        from template import select_template
        cfg: dict[str, str] = {"type": "unknown"}
        with pytest.raises(RuntimeError):
            select_template(cfg)


class TestDebianVersionParsing:
    """Tests for Debian version extraction from package names."""

    def test_debian_version_pattern(self) -> None:
        """Test parsing version from Debian package filename"""
        filename = "gdb-mingw-w64_17.1-3+13.3_amd64.deb"
        parts = filename.replace('.deb', '').split('_')
        version = parts[1] if len(parts) >= 2 else None
        assert version == "17.1-3+13.3"

    def test_debian_version_pattern_i386(self) -> None:
        """Test parsing version from i386 package"""
        filename = "gdb-mingw-w64_1.0.0_i386.deb"
        parts = filename.replace('.deb', '').split('_')
        version = parts[1] if len(parts) >= 2 else None
        assert version == "1.0.0"

    def test_debian_version_with_plus(self) -> None:
        """Test parsing version with + in it"""
        filename = "gdb-mingw-w64_17.1.3+13.3_amd64.deb"
        parts = filename.replace('.deb', '').split('_')
        version = parts[1] if len(parts) >= 2 else None
        assert version == "17.1.3+13.3"


class TestExtractMethod:
    """Tests for extract_method configuration."""

    def test_extract_method_default(self) -> None:
        """Test that extract_method defaults to 'ar'"""
        debian_config: dict[str, str] = {}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "ar"

    def test_extract_method_dpkg(self) -> None:
        """Test explicit dpkg method"""
        debian_config: dict[str, str] = {"extract_method": "dpkg"}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "dpkg"

    def test_extract_method_bsdtar(self) -> None:
        """Test bsdtar method"""
        debian_config: dict[str, str] = {"extract_method": "bsdtar"}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "bsdtar"

    def test_extract_method_invalid(self) -> None:
        """Test that invalid method passes through"""
        debian_config: dict[str, str] = {"extract_method": "invalid"}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "invalid"


class TestAppImageConfig:
    """Tests for AppImage configuration extraction."""

    def test_appimage_config_defaults(self) -> None:
        """Test that missing appimage config returns empty defaults"""
        appimage_config: dict[str, str | bool] = {}
        assert appimage_config.get("appimage_name", "") == ""
        assert appimage_config.get("binary_name", "") == ""
        assert appimage_config.get("desktop", False) is False
        assert appimage_config.get("icons", False) is False

    def test_appimage_config_explicit(self) -> None:
        """Test explicit appimage config values"""
        appimage_config: dict[str, str | bool] = {
            "appimage_name": "app-${pkgver}.AppImage",
            "binary_name": "myapp",
            "desktop": True,
            "icons": True
        }
        assert appimage_config.get("appimage_name", "") == "app-${pkgver}.AppImage"
        assert appimage_config.get("binary_name", "") == "myapp"
        assert appimage_config.get("desktop", False) is True
        assert appimage_config.get("icons", False) is True


class TestYAMLConfig:
    """Tests for YAML configuration handling."""

    def test_conflicts_optional(self) -> None:
        """Test that conflicts field is optional"""
        cfg: dict[str, Any] = {
            "pkgname": "test-pkg",
            "type": "debian",
            "arch": ["x86_64"],
            "pkgdesc": "Test package",
            "upstream": {"provider": "url", "url": "http://example.com"},
            "aur_repo": "test-pkg",
            "maintainer": "Test <test@test.com>"
        }
        assert cfg.get("conflicts") is None

    def test_conflicts_with_values(self) -> None:
        """Test conflicts field with values"""
        cfg: dict[str, list[str]] = {"conflicts": ["pkg-a", "pkg-b"]}
        assert cfg.get("conflicts") == ["pkg-a", "pkg-b"]

    def test_makedepends_optional(self) -> None:
        """Test that makedepends is optional"""
        cfg: dict[str, list[str]] = {"pkgname": "test"}
        assert cfg.get("makedepends") is None

    def test_makedepends_with_values(self) -> None:
        """Test makedepends field"""
        cfg: dict[str, list[str]] = {"makedepends": ["dpkg", "build-essential"]}
        assert cfg.get("makedepends") == ["dpkg", "build-essential"]

    def test_options_optional(self) -> None:
        """Test that options is optional"""
        cfg: dict[str, list[str]] = {}
        assert cfg.get("options") is None

    def test_options_with_values(self) -> None:
        """Test options field"""
        cfg: dict[str, list[str]] = {"options": ["!strip", "!debug"]}
        assert cfg.get("options") == ["!strip", "!debug"]


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_depends_array(self) -> None:
        """Test that empty depends array is handled"""
        cfg: dict[str, list[str]] = {"depends": []}
        depends = cfg.get("depends", [])
        result = " ".join(depends) if depends else ""
        assert result == ""

    def test_none_tag_handling(self) -> None:
        """Test that None tag is handled"""
        tag: str | None = None
        pkgver = tag or "0"
        assert pkgver == "0"

    def test_url_provider_without_debian(self) -> None:
        """Test URL provider for non-Debian URLs"""
        cfg: dict[str, dict[str, str]] = {
            "upstream": {
                "provider": "url",
                "url": "https://example.com/file.tar.gz"
            }
        }
        upstream = cfg["upstream"]
        provider = upstream["provider"]
        assert provider == "url"
        assert "debian.org" not in upstream["url"]
        assert "debian.net" not in upstream["url"]

    def test_debian_url_detection(self) -> None:
        """Test Debian URL detection"""
        url = "http://ftp.debian.org/debian/pool/main/g/gdb-mingw-w64/"
        is_debian = "debian.org" in url or "debian.net" in url
        assert is_debian is True

    def test_non_debian_url_detection(self) -> None:
        """Test non-Debian URL does not trigger debian logic"""
        url = "https://example.com/releases/app.tar.gz"
        is_debian = "debian.org" in url or "debian.net" in url
        assert is_debian is False


class TestAssetRegexInterpolation:
    """Tests for ${arch} and ${pkgver} interpolation in asset_regex."""

    def test_arch_interpolation_single(self) -> None:
        """Test ${arch} interpolation with single arch string"""
        arch = "x86_64"
        asset_regex = ".*-${arch}.AppImage$"
        result = asset_regex.replace("${arch}", arch)
        assert result == ".*-x86_64.AppImage$"

    def test_arch_interpolation_list(self) -> None:
        """Test ${arch} interpolation with arch list"""
        arch = ["x86_64", "aarch64"]
        arch_value = arch[0] if isinstance(arch, list) else arch
        asset_regex = ".*-${arch}.AppImage$"
        result = asset_regex.replace("${arch}", arch_value)
        assert result == ".*-x86_64.AppImage$"

    def test_pkgver_interpolation(self) -> None:
        """Test ${pkgver} interpolation in asset_regex"""
        tag = "1.5.6"
        asset_regex = "app-${pkgver}-${arch}.AppImage$"
        result = asset_regex.replace("${pkgver}", tag)
        result = result.replace("${arch}", "x86_64")
        assert result == "app-1.5.6-x86_64.AppImage$"

    def test_pkgver_from_github_tag(self) -> None:
        """Test extracting pkgver from GitHub tag format"""
        raw_tag = "desktop-v1.5.6"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.5.6"

    def test_no_interpolation_when_not_present(self) -> None:
        """Test asset_regex unchanged when no placeholders"""
        asset_regex = ".*AppImage$"
        result = asset_regex.replace("${pkgver}", "1.0.0")
        result = result.replace("${arch}", "x86_64")
        assert result == ".*AppImage$"
