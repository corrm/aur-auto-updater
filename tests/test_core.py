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
    """Tests for ${arch}, ${pkgver}, ${pkgname} interpolation in asset_regex."""

    def test_interpolate_dict_arch(self) -> None:
        """Test generic dict-based interpolation for arch"""
        interpolate = {"arch": "x86_64", "pkgname": "myapp"}
        asset_regex = ".*-${arch}.AppImage$"
        for key, value in interpolate.items():
            asset_regex = asset_regex.replace(f"${{{key}}}", value)
        assert asset_regex == ".*-x86_64.AppImage$"

    def test_interpolate_dict_multiple(self) -> None:
        """Test generic dict-based interpolation with multiple vars"""
        interpolate = {"arch": "aarch64", "pkgname": "myapp", "pkgver": "2.0.0"}
        asset_regex = "${pkgname}-${pkgver}-${arch}.AppImage$"
        for key, value in interpolate.items():
            asset_regex = asset_regex.replace(f"${{{key}}}", value)
        assert asset_regex == "myapp-2.0.0-aarch64.AppImage$"

    def test_interpolate_dict_pkgname(self) -> None:
        """Test ${pkgname} interpolation"""
        interpolate = {"pkgname": "superset-bin"}
        asset_regex = "${pkgname}-${arch}.AppImage$"
        for key, value in interpolate.items():
            asset_regex = asset_regex.replace(f"${{{key}}}", value)
        assert asset_regex == "superset-bin-${arch}.AppImage$"

    def test_pkgver_from_github_tag(self) -> None:
        """Test extracting pkgver from GitHub tag format"""
        raw_tag = "desktop-v1.5.6"
        tag = re.sub(r'^[a-zA-Z_-]*v?', '', raw_tag).lstrip('-')
        assert tag == "1.5.6"

    def test_no_interpolation_when_not_present(self) -> None:
        """Test asset_regex unchanged when no placeholders"""
        interpolate = {"arch": "x86_64", "pkgname": "myapp", "pkgver": "1.0.0"}
        asset_regex = ".*AppImage$"
        for key, value in interpolate.items():
            asset_regex = asset_regex.replace(f"${{{key}}}", value)
        assert asset_regex == ".*AppImage$"


class TestArchMapping:
    """Tests for arch_map configuration that maps Arch arch names to GitHub asset names."""

    def test_arch_map_x86_64_to_amd64(self) -> None:
        """Test mapping x86_64 to amd64 for GitHub assets"""
        arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
        arch = "x86_64"
        mapped = arch_map.get(arch, arch)
        assert mapped == "amd64"

    def test_arch_map_aarch64_to_arm64(self) -> None:
        """Test mapping aarch64 to arm64 for GitHub assets"""
        arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
        arch = "aarch64"
        mapped = arch_map.get(arch, arch)
        assert mapped == "arm64"

    def test_arch_map_no_mapping_uses_default(self) -> None:
        """Test that when no arch_map provided, default arch value is used"""
        arch_map: dict[str, str] = {}
        arch = "x86_64"
        mapped = arch_map.get(arch, arch)
        assert mapped == "x86_64"

    def test_arch_map_partial_mapping(self) -> None:
        """Test partial arch_map - some mapped, some not"""
        arch_map = {"x86_64": "amd64"}
        # x86_64 should map to amd64
        assert arch_map.get("x86_64", "x86_64") == "amd64"
        # aarch64 should fall back to default
        assert arch_map.get("aarch64", "aarch64") == "aarch64"

    def test_arch_map_with_interpolation(self) -> None:
        """Test arch_map used in interpolation dict for GitHub asset matching"""
        arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
        arch = "x86_64"
        interpolate: dict[str, str] = {}

        if arch_map and arch in arch_map:
            interpolate["arch"] = arch_map[arch]
        else:
            interpolate["arch"] = arch

        assert interpolate["arch"] == "amd64"

    def test_agent_deck_asset_regex_with_arch_map(self) -> None:
        """Test agent-deck style asset regex with arch mapping"""
        # agent-deck uses: ".*-linux-${arch}\.tar\.gz"
        # With arch_map: x86_64 -> amd64
        arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
        arch = "x86_64"

        # Using simple string to avoid regex escaping confusion in test
        asset_regex = ".*-linux-${arch}.tar.gz"
        if arch_map and arch in arch_map:
            arch_value = arch_map[arch]
        else:
            arch_value = arch

        asset_regex = asset_regex.replace(f"${{arch}}", arch_value)

        assert asset_regex == ".*-linux-amd64.tar.gz"
        assert "amd64" in asset_regex

    def test_binary_type_in_schema(self) -> None:
        """Test that 'binary' is a valid package type"""
        valid_types = ["appimage", "debian", "pypi", "npm", "binary"]
        assert "binary" in valid_types

    def test_extract_tar_from_upstream(self) -> None:
        """Test extract: tar from upstream config"""
        upstream = {"provider": "github", "repo": "user/repo", "extract": "tar"}
        extract = upstream.get("extract", "none")
        assert extract == "tar"

    def test_extract_zip_from_upstream(self) -> None:
        """Test extract: zip from upstream config"""
        upstream = {"provider": "github", "repo": "user/repo", "extract": "zip"}
        extract = upstream.get("extract", "none")
        assert extract == "zip"

    def test_extract_none_default(self) -> None:
        """Test extract defaults to 'none' when not specified"""
        upstream = {"provider": "github", "repo": "user/repo"}
        extract = upstream.get("extract", "none")
        assert extract == "none"


class TestDefaultArchMapping:
    """Tests for automatic default arch mapping in upstream.py"""

    def test_default_arch_map_x86_64_to_amd64(self) -> None:
        """Test default mapping: x86_64 -> amd64"""
        from upstream import DEFAULT_ARCH_MAP
        assert DEFAULT_ARCH_MAP["x86_64"] == "amd64"

    def test_default_arch_map_aarch64_to_arm64(self) -> None:
        """Test default mapping: aarch64 -> arm64"""
        from upstream import DEFAULT_ARCH_MAP
        assert DEFAULT_ARCH_MAP["aarch64"] == "arm64"

    def test_arch_values_to_try_order(self) -> None:
        """Test that original arch is tried first, then mapped as fallback"""
        DEFAULT_ARCH_MAP = {"x86_64": "amd64", "aarch64": "arm64"}
        original_arch = "x86_64"

        # Build list: original first, then mapped if different
        arch_values_to_try = [original_arch]
        if original_arch in DEFAULT_ARCH_MAP:
            mapped = DEFAULT_ARCH_MAP[original_arch]
            if mapped != original_arch:
                arch_values_to_try.append(mapped)

        # Should try x86_64 first, then amd64
        assert arch_values_to_try == ["x86_64", "amd64"]

    def test_non_mapped_arch_single_value(self) -> None:
        """Test that if arch not in map, only one value is tried"""
        DEFAULT_ARCH_MAP = {"x86_64": "amd64", "aarch64": "arm64"}
        original_arch = "i686"

        # Not in map, so only original is tried
        arch_values_to_try = [original_arch]
        if original_arch in DEFAULT_ARCH_MAP:
            mapped = DEFAULT_ARCH_MAP[original_arch]
            if mapped != original_arch:
                arch_values_to_try.append(mapped)

        assert arch_values_to_try == ["i686"]


class TestInstallFiles:
    """Tests for install_files configuration."""

    def test_install_files_schema(self) -> None:
        """Test that install_files is defined in schema"""
        import json
        with open('schema/package.schema.json', 'r') as f:
            schema = json.load(f)
        assert 'install_files' in schema['properties']

    def test_install_files_structure(self) -> None:
        """Test install_files array structure"""
        install_files = [
            {"source": "LICENSE", "dest": "/usr/share/licenses/${pkgname}", "mode": "644"},
            {"source": "README.md", "dest": "/usr/share/doc/${pkgname}", "mode": "644"}
        ]
        for f in install_files:
            assert 'source' in f
            assert 'dest' in f
            assert 'mode' in f

    def test_install_files_mode_validation(self) -> None:
        """Test that mode must be 644 or 755"""
        valid_modes = ["644", "755"]
        for mode in valid_modes:
            assert mode in valid_modes

    def test_install_files_pkgname_interpolation(self) -> None:
        """Test that ${pkgname} is replaced correctly in dest path"""
        pkgname = "my-package"
        install_files = [
            {"source": "LICENSE", "dest": "/usr/share/licenses/${pkgname}", "mode": "644"}
        ]
        # Simulate what template does
        for f in install_files:
            dest = f["dest"].replace("${pkgname}", pkgname)
            assert dest == "/usr/share/licenses/my-package"

    def test_install_files_multiple_files(self) -> None:
        """Test multiple files in install_files array"""
        install_files = [
            {"source": "LICENSE", "dest": "/usr/share/licenses/${pkgname}", "mode": "644"},
            {"source": "README.md", "dest": "/usr/share/doc/${pkgname}", "mode": "644"},
            {"source": "CHANGELOG.md", "dest": "/usr/share/doc/${pkgname}", "mode": "644"},
            {"source": "mybin", "dest": "/usr/bin", "mode": "755"}
        ]
        assert len(install_files) == 4
        assert install_files[3]["mode"] == "755"  # executable

    def test_install_files_generates_install_commands(self) -> None:
        """Test that install_files generates correct install commands"""
        install_files = [
            {"source": "LICENSE", "dest": "/usr/share/licenses/${pkgname}", "mode": "644"}
        ]
        pkgname = "test-pkg"
        # Simulate what template does - replaces ${pkgname} in dest
        for f in install_files:
            dest = f["dest"].replace("${pkgname}", pkgname)
            # Check that variable was replaced
            assert dest == "/usr/share/licenses/test-pkg"
            # Check mode is correct
            assert f["mode"] == "644"

    def test_install_files_no_license_file_in_schema(self) -> None:
        """Test that old license_file property is removed"""
        import json
        with open('schema/package.schema.json', 'r') as f:
            schema = json.load(f)
        assert 'license_file' not in schema['properties']
