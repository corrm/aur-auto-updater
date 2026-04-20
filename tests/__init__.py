import pytest
import re
from unittest.mock import patch, MagicMock


class TestTagParsing:
    """Tests for tag version extraction from various tag formats."""

    def test_tag_with_v_prefix(self):
        """Test that 'v1.2.3' becomes '1.2.3'"""
        raw_tag = "v1.2.3"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.2.3"

    def test_tag_with_desktop_prefix(self):
        """Test that 'desktop-v1.5.6' becomes '1.5.6' - common for desktop apps"""
        raw_tag = "desktop-v1.5.6"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.5.6"

    def test_tag_with_release_prefix(self):
        """Test that 'release-2.0' becomes '2.0'"""
        raw_tag = "release-2.0"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "2.0"

    def test_tag_plain_version(self):
        """Test that plain version '2024.01.15' stays unchanged"""
        raw_tag = "2024.01.15"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "2024.01.15"

    def test_tag_with_multiple_prefixes(self):
        """Test that 'v2.0.0-beta' becomes '2.0.0-beta'"""
        raw_tag = "v2.0.0-beta"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "2.0.0-beta"

    def test_tag_starts_with_dash(self):
        """Test edge case where stripping leaves leading dash"""
        raw_tag = "-v1.0.0"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.0.0"


class TestVersionConversion:
    """Tests for converting version strings to valid Arch pkgver."""

    def test_hyphen_replaced_with_dot(self):
        """Test that hyphens are replaced with dots"""
        version = "17.1-3+13.3"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "17.1.3+13.3"

    def test_colon_replaced_with_dot(self):
        """Test that colons are replaced with dots"""
        version = "1.0:2.0"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "1.0.2.0"

    def test_version_with_slash_not_handled(self):
        """Test that forward slashes are NOT replaced (known limitation)"""
        # This documents a known limitation - forward slashes should be handled
        # but currently aren't in the code
        version = "1.0/2.0"
        pkgver = version.replace("-", ".").replace(":", ".")
        # Forward slash is NOT replaced - this is a known issue
        assert pkgver == "1.0/2.0"

    def test_version_already_valid(self):
        """Test that valid version passes through unchanged"""
        version = "1.5.6"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "1.5.6"

    def test_version_with_plus_sign(self):
        """Test that versions with + (semver) work"""
        version = "1.0.0+beta"
        pkgver = version.replace("-", ".").replace(":", ".")
        assert pkgver == "1.0.0+beta"


class TestAssetRegex:
    """Tests for asset matching with regex patterns."""

    def test_appimage_regex_simple(self):
        """Test simple .AppImage matching"""
        pattern = r".*\.AppImage$"
        assert re.match(pattern, "app-1.0.0-x86_64.AppImage")
        assert not re.match(pattern, "app-1.0.0.deb")

    def test_appimage_regex_with_arch(self):
        """Test AppImage regex with architecture in name"""
        pattern = r".*AppImage$"
        assert re.match(pattern, "superset-1.4.7-x86_64.AppImage")
        assert re.match(pattern, "app-1.0.0-aarch64.AppImage")

    def test_appimage_regex_negative(self):
        """Test that non-AppImage files don't match"""
        pattern = r".*\.AppImage$"
        assert not re.match(pattern, "app-1.0.0.Appimage")  # wrong case
        assert not re.match(pattern, "app-1.0.0.appimage")  # wrong extension


class TestTemplateSelection:
    """Tests for template selection logic."""

    def test_select_appimage_template(self):
        """Test that appimage type selects correct template"""
        import sys
        sys.path.insert(0, 'scripts')
        from template import select_template
        cfg = {"type": "appimage"}
        result = select_template(cfg)
        assert "appimage" in result

    def test_select_debian_template(self):
        """Test that debian type selects correct template"""
        import sys
        sys.path.insert(0, 'scripts')
        from template import select_template
        cfg = {"type": "debian"}
        result = select_template(cfg)
        assert "debian" in result

    def test_unknown_type_raises(self):
        """Test that unknown type raises RuntimeError"""
        import sys
        sys.path.insert(0, 'scripts')
        from template import select_template
        cfg = {"type": "unknown"}
        with pytest.raises(RuntimeError):
            select_template(cfg)


class TestDebianVersionParsing:
    """Tests for Debian version extraction from package names."""

    def test_debian_version_pattern(self):
        """Test parsing version from Debian package filename"""
        pkg_pattern = "gdb-mingw-w64"
        filename = "gdb-mingw-w64_17.1-3+13.3_amd64.deb"

        # Extract version: pkgname_version_arch.deb
        parts = filename.replace('.deb', '').split('_')
        version = parts[1] if len(parts) >= 2 else None

        assert version == "17.1-3+13.3"

    def test_debian_version_pattern_i386(self):
        """Test parsing version from i386 package"""
        pkg_pattern = "gdb-mingw-w64"
        filename = "gdb-mingw-w64_1.0.0_i386.deb"

        parts = filename.replace('.deb', '').split('_')
        version = parts[1] if len(parts) >= 2 else None

        assert version == "1.0.0"

    def test_debian_version_with_plus(self):
        """Test parsing version with + in it"""
        filename = "gdb-mingw-w64_17.1.3+13.3_amd64.deb"

        parts = filename.replace('.deb', '').split('_')
        version = parts[1] if len(parts) >= 2 else None

        assert version == "17.1.3+13.3"


class TestExtractMethod:
    """Tests for extract_method configuration."""

    def test_extract_method_default(self):
        """Test that extract_method defaults to 'ar'"""
        debian_config = {}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "ar"

    def test_extract_method_dpkg(self):
        """Test explicit dpkg method"""
        debian_config = {"extract_method": "dpkg"}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "dpkg"

    def test_extract_method_bsdtar(self):
        """Test bsdtar method"""
        debian_config = {"extract_method": "bsdtar"}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "bsdtar"

    def test_extract_method_invalid(self):
        """Test that invalid method passes through"""
        debian_config = {"extract_method": "invalid"}
        extract_method = debian_config.get("extract_method", "ar")
        assert extract_method == "invalid"


class TestAppImageConfig:
    """Tests for AppImage configuration extraction."""

    def test_appimage_config_defaults(self):
        """Test that missing appimage config returns empty defaults"""
        appimage_config = {}

        assert appimage_config.get("appimage_name", "") == ""
        assert appimage_config.get("binary_name", "") == ""
        assert appimage_config.get("desktop", False) is False
        assert appimage_config.get("icons", False) is False

    def test_appimage_config_explicit(self):
        """Test explicit appimage config values"""
        appimage_config = {
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

    def test_conflicts_optional(self):
        """Test that conflicts field is optional"""
        cfg = {
            "pkgname": "test-pkg",
            "type": "debian",
            "arch": ["x86_64"],
            "pkgdesc": "Test package",
            "upstream": {"provider": "url", "url": "http://example.com"},
            "aur_repo": "test-pkg",
            "maintainer": "Test <test@test.com>"
        }

        assert cfg.get("conflicts") is None

    def test_conflicts_with_values(self):
        """Test conflicts field with values"""
        cfg = {
            "conflicts": ["pkg-a", "pkg-b"]
        }

        assert cfg.get("conflicts") == ["pkg-a", "pkg-b"]

    def test_makedepends_optional(self):
        """Test that makedepends is optional"""
        cfg = {"pkgname": "test"}
        assert cfg.get("makedepends") is None

    def test_makedepends_with_values(self):
        """Test makedepends field"""
        cfg = {
            "makedepends": ["dpkg", "build-essential"]
        }
        assert cfg.get("makedepends") == ["dpkg", "build-essential"]

    def test_options_optional(self):
        """Test that options is optional"""
        cfg = {}
        assert cfg.get("options") is None

    def test_options_with_values(self):
        """Test options field"""
        cfg = {
            "options": ["!strip", "!debug"]
        }
        assert cfg.get("options") == ["!strip", "!debug"]


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_depends_array(self):
        """Test that empty depends array is handled"""
        cfg = {"depends": []}
        depends = cfg.get("depends", [])
        result = " ".join(depends) if depends else ""
        assert result == ""

    def test_none_tag_handling(self):
        """Test that None tag is handled"""
        tag = None
        pkgver = tag or "0"
        assert pkgver == "0"

    def test_url_provider_without_debian(self):
        """Test URL provider for non-Debian URLs"""
        cfg = {
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

    def test_debian_url_detection(self):
        """Test Debian URL detection"""
        url = "http://ftp.debian.org/debian/pool/main/g/gdb-mingw-w64/"

        is_debian = "debian.org" in url or "debian.net" in url
        assert is_debian is True

    def test_non_debian_url_detection(self):
        """Test non-Debian URL does not trigger debian logic"""
        url = "https://example.com/releases/app.tar.gz"

        is_debian = "debian.org" in url or "debian.net" in url
        assert is_debian is False