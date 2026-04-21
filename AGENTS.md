# AUR Auto-Updater

## Architecture

- **Package types**: `debian` (extract .deb), `appimage` (AppImage)
- **Templates**: `templates/*.PKGBUILD.j2`
- **Package configs**: `packages/*.yaml`
- **Schema**: `schema/package.schema.json`

## Key Commands

```bash
# Run sync locally
python scripts/run_all.py

# Validate YAML packages
python scripts/validate.py

# Run tests
python -m pytest tests/ -v
```

## Scripts Structure

- `run_all.py` - Main orchestrator (entry point)
- `build.py` - Build packages from YAML config (includes state + template logic)
- `aur.py` - AUR repository operations
- `makepkg_wrapper.py` - Makepkg wrapper
- `upstream.py` - Fetch upstream versions (GitHub, Debian)
- `validate.py` - Validate YAML against schema
- `template.py` - Re-exports from build (backwards compat)

## Workflows

- `aur-autosync`: Runs every 6 hours or manually - builds and publishes to AUR
- `validate-packages`: Validates YAML configs against schema
- `Run Tests`: Runs unit tests on `scripts/` and `tests/` changes

## Critical Gotchas

1. **makepkg as non-root**: Uses `builder` user to avoid makepkg refusing to run as root
2. **Tag parsing**: Regex `^[a-zA-Z_-]*v?` strips prefixes like `desktop-v`, `release-`, `v`
3. **Version format**: Replace `-` and `:` with `.` for valid Arch pkgver
4. **noextract order**: Must define `_appimage` variable BEFORE `noextract` line in template
5. **extract_method**: Supports `ar` (default), `dpkg`, `bsdtar` - adds dpkg to makedepends automatically if used

## Package YAML Structure

```yaml
pkgname: pkg-name
type: debian | appimage
arch: [x86_64]
pkgdesc: Description
url: https://...
depends: []
makedepends: []
options: []
conflicts: []
upstream:
  provider: github | url
  repo: owner/repo  # for github
  url: http://...   # for url
  asset_regex: ".*AppImage$"  # for github

# For debian type:
debian:
  extract_method: ar | dpkg | bsdtar

# For appimage type:
appimage:
  appimage_name: "${pkgver}.AppImage"
  binary_name: myapp
  desktop: true
  icons: true
```

## Testing

Tests are in `tests/test_core.py` - run with:
```bash
python -m pytest tests/ -v
```

## Dependencies

- Python packages via `uv`: pytest, pyyaml, requests, jsonschema, jinja2
- Arch packages: git, base-devel, openssh