# AUR Auto-Updater

## Architecture

- **Package types**: `debian` (extract .deb), `appimage` (AppImage), `binary` (extracted tar/zip), `pypi`, `npm`, `actions` (compose reusable build steps)
- **Templates**: `templates/*.PKGBUILD.j2`
- **Actions**: `actions/*.yaml` — reusable, parameterized build steps (GitHub-Actions-style) for `type: actions`
- **Package configs**: `packages/*.yaml`
- **Schema**: `schema/package.schema.json`

## Actions (type: actions)

For source projects with no releases (clone → build → install). A package lists ordered
`steps`; each `uses` an action from `actions/<name>.yaml` and passes `with` params.
`scripts/actions.py` resolves inputs and renders `templates/actions.PKGBUILD.j2`. Paired
with the `git` upstream provider (tracks a branch head → VCS pkgver, sources use `SKIP`
checksums). Example: `packages/3dgenstudio-git.yaml`. Tests: `tests/test_actions.py`.

An action file (`actions/*.yaml`, schema `schema/action.schema.json`) declares:

- `inputs` — each input is either a scalar default (`ref: HEAD`; `null` = required) or an
  explicit spec: `{default, required, choices, type, description}`. `choices` and `type`
  (`string`/`number`/`boolean`/`array`) are enforced at render time.
- `makedepends` / `depends` / `sources` — contributed to the package (deduped, Jinja-templated).
- `pkgver` / `prepare` / `build` / `package` — Jinja-templated bash appended to that PKGBUILD phase.
- `outputs` — named Jinja strings published as `steps['<id>'].outputs.<name>` for later steps
  to reference in their `with:` values. A step's id defaults to its `uses` name; set `id:` to
  disambiguate. Unknown references are a hard error (StrictUndefined), not a silent empty string.

Each step (GitHub-Actions-inspired) supports:

- `uses:` a reusable action **or** `run:` inline bash (exactly one). A `run:` step appends
  bash to `phase:` (`prepare`/`build`/`package`, default `build`) — no action file needed.
- `name:` — label emitted as a `# comment` above the step's bash in the PKGBUILD.
- `if:` — Jinja expression; the step is skipped when falsy (e.g. `if: "arch[0] == 'x86_64'"`).
  Expressions see `pkgname`, `pkgver`, `arch`, and `steps` (prior outputs).
- `env:` — `KEY: value` map exported before the step's bash (per phase, since phase functions
  are separate shell scopes).
- `id:` / `with:` — as above.

`scripts/validate.py` checks packages against `package.schema.json`, actions against
`action.schema.json`, and dry-runs every `type: actions` package through the engine so
rule violations (bad choice, wrong type, missing/unknown input, unknown action, `if`/`run`
misuse) fail CI.

Outputs are render-time only (values known while generating the PKGBUILD). Build-time shell
outputs (values computed *during* makepkg and passed between phases) are intentionally not
implemented — no action needs them, and it would force a temp-file protocol + auto-sourced
preamble into every phase. Add a `$srcdir/.actions-outputs` sourced-preamble convention if one
ever does.

## Key Commands

```bash
# Run sync locally (ALWAYS use uv run)
uv run python scripts/run_all.py

# Validate YAML packages (ALWAYS use uv run)
uv run python scripts/validate.py

# Run tests (ALWAYS use uv run)
uv run pytest tests/ -v
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

1. **ALWAYS use `uv run`** for all Python commands - the project uses uv for dependency management
2. **makepkg as non-root**: Uses `builder` user to avoid makepkg refusing to run as root
3. **Tag parsing**: Regex `^[a-zA-Z_-]*v?` strips prefixes like `desktop-v`, `release-`, `v`
4. **Version format**: Replace `-` and `:` with `.` for valid Arch pkgver
5. **noextract order**: Must define `_appimage` variable BEFORE `noextract` line in template
6. **extract_method**: Supports `ar` (default), `dpkg`, `bsdtar` - adds dpkg to makedepends automatically if used
7. **Default arch mapping**: Some releases use `amd64`/`arm64`, Arch uses `x86_64`/`aarch64`. The system tries original arch first, then falls back to mapped if no asset matches. GitHub provider gets SHA256 from API - no download needed!

## Package YAML Structure

```yaml
pkgname: pkg-name
type: debian | appimage | binary
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
  extract: tar | zip | none  # for binary type - extracts compressed downloads

# For debian type:
debian:
  extract_method: ar | dpkg | bsdtar

# For appimage type:
appimage:
  appimage_name: "${pkgver}.AppImage"
  binary_name: myapp
  desktop: true
  icons: true

# For binary type (extracted tar/zip):
binary:
  binary_name: myapp
```

## Testing

Tests are in `tests/test_core.py` - run with:
```bash
uv run pytest tests/ -v
```

## Dependencies

- Python packages via `uv`: pytest, pyyaml, requests, jsonschema, jinja2
- Arch packages: git, base-devel, openssh

## Lessons Learned (Common Issues)

1. **Empty arrays in templates**: Always wrap `makedepends`, `options`, etc. in `{% if ... %}` to avoid emitting empty arrays
2. **Extra blank lines**: Use Jinja2 whitespace control (`{%-` and `-%}`) to trim unnecessary newlines
3. **Arch mapping fallback**: When GitHub asset uses different naming than Arch (e.g., amd64 vs x86_64), the system tries mapped value first, then falls back to original arch value if no asset matches
4. **noextract syntax**: Use `noextract=("${_appimage}")` with quotes, not `noextract=()` which is incorrect