"""Unit tests for the composable 'actions' PKGBUILD engine.

Run from repo root: `uv run pytest tests/test_actions.py -v`
"""
import base64
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, "scripts")
import actions  # noqa: E402


def _render_pkg(name: str) -> str:
    cfg = yaml.safe_load(Path(f"packages/{name}.yaml").read_text())
    return actions.render(cfg, pkgver="r20260708.abc1234")


class TestRenderRealPackage:
    """Render the shipped 3dgenstudio-git package end to end (no network)."""

    def setup_method(self) -> None:
        self.out = _render_pkg("3dgenstudio-git")

    def test_metadata(self) -> None:
        assert "pkgname=3dgenstudio-git" in self.out
        assert "pkgver=r20260708.abc1234" in self.out
        assert 'depends=("nodejs" "xdg-utils")' in self.out
        assert 'optdepends=("python: local 3D-generation backend (python-server)")' in self.out

    def test_git_source_and_skip_checksum(self) -> None:
        assert '"3dgenstudio-git::git+https://github.com/visualbruno/3DGenStudio.git#branch=main"' in self.out
        assert "sha256sums=('SKIP')" in self.out

    def test_pkgver_function_present(self) -> None:
        assert "pkgver() {" in self.out
        assert "git rev-list --count HEAD" in self.out

    def test_build_phase_runs_npm(self) -> None:
        assert "build() {" in self.out
        assert "npm ci" in self.out
        assert "npm run build" in self.out

    def test_package_installs_prod_tree_and_launcher(self) -> None:
        assert "package() {" in self.out
        assert 'install -d "$pkgdir/opt/3dgenstudio-git"' in self.out
        assert "npm prune --omit=dev" in self.out          # production deps only
        assert 'cp -a --no-target-directory . "$pkgdir/opt/3dgenstudio-git"' in self.out
        assert "rm -rf .git .env src" in self.out           # dev source dropped
        assert '/usr/bin/3dgenstudio' in self.out

    def test_launcher_script_roundtrips_through_b64(self) -> None:
        # The launcher body is embedded base64; decoding must yield the real script.
        line = next(l for l in self.out.splitlines() if "base64 -d" in l)
        b64 = line.split('<<< "')[1].rstrip('"')
        script = base64.b64decode(b64).decode()
        assert script.startswith("#!/bin/bash")
        assert 'node "$app/server.js"' in script            # runs the production server


class TestDesktopEntry:
    def test_desktop_entry_and_icon(self) -> None:
        cfg = {"pkgname": "myapp", "type": "actions", "steps": [
            {"uses": "git-source", "with": {"url": "u"}},
            {"uses": "desktop-entry", "with": {
                "name": "myapp", "title": "My App", "exec": "myapp",
                "comment": "does things", "categories": "Utility;",
                "icon_source": "dist/favicon.png", "icon_size": "128x128"}},
        ]}
        out = actions.render(cfg, "1")
        assert "/usr/share/applications/myapp.desktop" in out
        assert "'Name=My App'" in out
        assert "'Exec=myapp'" in out
        assert "/usr/share/icons/hicolor/128x128/apps/myapp.png" in out

    def test_desktop_entry_without_icon(self) -> None:
        cfg = {"pkgname": "x", "type": "actions", "steps": [
            {"uses": "desktop-entry", "with": {"name": "x", "title": "X", "exec": "x"}},
        ]}
        out = actions.render(cfg, "1")
        assert "myapp.png" not in out
        assert "hicolor" not in out  # no icon installed when icon_source omitted


class TestRepublishLogic:
    """Force-republish (pkgrel bump) mechanics."""

    def test_pkgrel_threads_into_render(self) -> None:
        cfg = {"pkgname": "x", "type": "actions",
               "steps": [{"uses": "git-source", "with": {"url": "u"}}]}
        assert "pkgrel=3" in actions.render(cfg, "1", pkgrel=3)

    def test_signature_ignores_pkgrel_and_checksum(self) -> None:
        pytest.importorskip("requests")
        import build
        a = "pkgname=x\npkgver=1\npkgrel=1\nsha256sums=('AAA')\nbuild() { make; }"
        b = "pkgname=x\npkgver=1\npkgrel=9\nsha256sums=('BBB')\nbuild() { make; }"
        c = "pkgname=x\npkgver=1\npkgrel=1\nbuild() { make install; }"
        assert build._pkgbuild_signature(a) == build._pkgbuild_signature(b)  # only pkgrel/sum differ
        assert build._pkgbuild_signature(a) != build._pkgbuild_signature(c)  # real change

    def test_split_version(self) -> None:
        pytest.importorskip("requests")
        import build
        assert build._split_version("1.2.3-4") == ("1.2.3", 4)
        assert build._split_version("r8d4b6a2-1") == ("r8d4b6a2", 1)
        assert build._split_version("") == (None, 1)


class TestInputResolution:
    def test_unknown_action_raises(self) -> None:
        cfg = {"pkgname": "x", "type": "actions", "steps": [{"uses": "does-not-exist"}]}
        with pytest.raises(RuntimeError, match="Unknown action"):
            actions.render(cfg, "1")

    def test_missing_required_input_raises(self) -> None:
        # git-source requires 'url'
        cfg = {"pkgname": "x", "type": "actions", "steps": [{"uses": "git-source"}]}
        with pytest.raises(RuntimeError, match="requires input 'url'"):
            actions.render(cfg, "1")

    def test_unknown_input_raises(self) -> None:
        cfg = {"pkgname": "x", "type": "actions",
               "steps": [{"uses": "git-source", "with": {"url": "u", "bogus": 1}}]}
        with pytest.raises(RuntimeError, match="unknown input"):
            actions.render(cfg, "1")

    def test_empty_steps_raises(self) -> None:
        cfg = {"pkgname": "x", "type": "actions", "steps": []}
        with pytest.raises(RuntimeError, match="non-empty 'steps'"):
            actions.render(cfg, "1")

    def test_default_workdir_expands_pkgname(self) -> None:
        # npm-build's default workdir "$srcdir/{{ pkgname }}" must resolve pkgname.
        cfg = {"pkgname": "myapp", "type": "actions",
               "steps": [{"uses": "git-source", "with": {"url": "u"}},
                         {"uses": "npm-build"}]}
        out = actions.render(cfg, "1")
        assert 'cd "$srcdir/myapp"' in out
        assert "{{ pkgname }}" not in out


class TestChoicesAndTypes:
    def test_valid_choice_accepted(self) -> None:
        cfg = {"pkgname": "x", "type": "actions",
               "steps": [{"uses": "git-source", "with": {"url": "u"}},
                         {"uses": "npm-build", "with": {"package_manager": "bun"}}]}
        out = actions.render(cfg, "1")
        assert "bun install --frozen-lockfile" in out
        assert '"bun"' in out  # makedepends

    def test_invalid_choice_rejected(self) -> None:
        cfg = {"pkgname": "x", "type": "actions",
               "steps": [{"uses": "npm-build", "with": {"package_manager": "yarn"}}]}
        with pytest.raises(RuntimeError, match="not in choices"):
            actions.render(cfg, "1")

    def test_wrong_type_rejected(self) -> None:
        # build_script is declared type: string; a list must be rejected.
        cfg = {"pkgname": "x", "type": "actions",
               "steps": [{"uses": "npm-build", "with": {"build_script": ["a", "b"]}}]}
        with pytest.raises(RuntimeError, match="must be string"):
            actions.render(cfg, "1")


class TestOutputs:
    def test_step_output_consumed_by_later_step(self) -> None:
        # git-source publishes outputs.dir; a later step reads it via steps['git-source'].
        cfg = {"pkgname": "app", "type": "actions",
               "steps": [
                   {"uses": "git-source", "with": {"url": "u"}},
                   {"uses": "install-tree",
                    "with": {"workdir": "{{ steps['git-source'].outputs.dir }}",
                             "paths": "dist"}},
               ]}
        out = actions.render(cfg, "1")
        assert 'cd "$srcdir/app"' in out  # resolved from the git-source output

    def test_unknown_output_reference_is_loud(self) -> None:
        cfg = {"pkgname": "app", "type": "actions",
               "steps": [{"uses": "install-tree",
                          "with": {"workdir": "{{ steps['nope'].outputs.dir }}",
                                   "paths": "dist"}}]}
        with pytest.raises(Exception):  # StrictUndefined -> error, not silent ""
            actions.render(cfg, "1")


class TestGithubStyleSteps:
    def test_inline_run_step(self) -> None:
        cfg = {"pkgname": "app", "type": "actions",
               "steps": [{"uses": "git-source", "with": {"url": "u"}},
                         {"run": "echo hello > $srcdir/marker", "phase": "prepare",
                          "name": "drop a marker"}]}
        out = actions.render(cfg, "1")
        assert "prepare() {" in out
        assert "# drop a marker" in out
        assert "echo hello > $srcdir/marker" in out

    def test_run_step_defaults_to_build_phase(self) -> None:
        cfg = {"pkgname": "app", "type": "actions", "steps": [{"run": "make"}]}
        out = actions.render(cfg, "1")
        assert "build() {" in out and "make" in out

    def test_if_false_skips_step(self) -> None:
        cfg = {"pkgname": "app", "type": "actions", "arch": ["aarch64"],
               "steps": [{"run": "echo only-on-x86", "if": "arch[0] == 'x86_64'"}]}
        out = actions.render(cfg, "1")
        assert "only-on-x86" not in out

    def test_if_true_keeps_step(self) -> None:
        cfg = {"pkgname": "app", "type": "actions", "arch": ["x86_64"],
               "steps": [{"run": "echo only-on-x86", "if": "arch[0] == 'x86_64'"}]}
        out = actions.render(cfg, "1")
        assert "only-on-x86" in out

    def test_env_exported_before_body(self) -> None:
        cfg = {"pkgname": "app", "type": "actions",
               "steps": [{"run": "npm run build", "env": {"NODE_ENV": "production"}}]}
        out = actions.render(cfg, "1")
        assert 'export NODE_ENV="production"' in out

    def test_step_needs_exactly_one_of_uses_or_run(self) -> None:
        cfg = {"pkgname": "app", "type": "actions",
               "steps": [{"uses": "git-source", "run": "echo x", "with": {"url": "u"}}]}
        with pytest.raises(RuntimeError, match="exactly one of 'uses' or 'run'"):
            actions.render(cfg, "1")

    def test_run_rejects_bad_phase(self) -> None:
        cfg = {"pkgname": "app", "type": "actions",
               "steps": [{"run": "echo x", "phase": "pkgver"}]}
        with pytest.raises(RuntimeError, match="phase must be"):
            actions.render(cfg, "1")
