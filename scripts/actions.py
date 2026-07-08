#!/usr/bin/env python3
"""Composable build "actions" — GitHub-Actions-style reusable steps that assemble a PKGBUILD.

A package of ``type: actions`` lists ordered ``steps``; each step ``uses`` a reusable
action defined in ``actions/<name>.yaml`` and passes ``with`` params. An action declares
the ``makedepends``/``depends``/``sources`` it contributes plus Jinja2-templated bash for
the ``pkgver``/``prepare``/``build``/``package`` phases. This module resolves each step's
inputs, aggregates the metadata, and renders ``templates/actions.PKGBUILD.j2``.

This is what lets a source project with no releases (clone → build → install) be packaged
by composing small reusable steps instead of one bespoke template per project.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from jinja2 import StrictUndefined, Template  # type: ignore[import-untyped]

_ROOT = Path(__file__).parent.parent
ACTIONS_DIR = _ROOT / "actions"
TEMPLATE = _ROOT / "templates" / "actions.PKGBUILD.j2"

# pkgver is emitted as a pkgver() function; the rest become PKGBUILD phase functions.
PHASES = ("pkgver", "prepare", "build", "package")

# Input `type:` values → the Python types they accept (for optional validation).
_TYPES = {"string": str, "number": (int, float), "boolean": bool, "array": list}


def _load_action(name: str) -> dict[str, Any]:
    path = ACTIONS_DIR / f"{name}.yaml"
    if not path.exists():
        raise RuntimeError(f"Unknown action '{name}' (expected {path})")
    return yaml.safe_load(path.read_text())


def _tmpl(text: str, ctx: dict[str, Any]) -> str:
    # StrictUndefined: referencing an unknown var (e.g. a typo'd step output) is a loud
    # error, not a silent empty string. Bash's ${...} is untouched — Jinja only sees {{ }}.
    t = Template(text, undefined=StrictUndefined)
    # b64: encode a (possibly multi-line) value into a single-line base64 string,
    # so an action can embed a whole launcher script without heredoc/indentation pain.
    t.environment.filters["b64"] = lambda s: base64.b64encode(str(s).encode()).decode()
    return t.render(**ctx)


def _input_spec(spec: Any) -> tuple[Any, bool, Any, Any]:
    """Normalize an input declaration to (default, required, choices, type).

    Two forms are accepted:
      key: <default>                 # scalar shorthand; null default => required
      key: {default, required, choices, type, description}   # explicit
    """
    if isinstance(spec, dict):
        default = spec.get("default")
        return default, spec.get("required", default is None), spec.get("choices"), spec.get("type")
    return spec, spec is None, None, None


def _resolve_inputs(action: dict[str, Any], step: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Merge a step's `with` over the action's declared inputs and enforce the rules.

    Enforces: unknown inputs, required inputs, declared `type`, and `choices`. String
    values are Jinja-rendered against `base` so defaults like "$srcdir/{{ pkgname }}" and
    caller values (including `{{ steps['x'].outputs.y }}`) resolve.
    """
    name = action["name"]
    declared = action.get("inputs", {}) or {}
    given = step.get("with", {}) or {}
    unknown = set(given) - set(declared)
    if unknown:
        raise RuntimeError(f"Action '{name}' got unknown input(s): {sorted(unknown)}")
    params: dict[str, Any] = {}
    for key, spec in declared.items():
        default, required, choices, expected = _input_spec(spec)
        raw = given.get(key, default)
        if raw is None:
            if required:
                raise RuntimeError(f"Action '{name}' requires input '{key}'")
            raw = ""
        if expected and not isinstance(raw, _TYPES[expected]):
            raise RuntimeError(f"Action '{name}' input '{key}' must be {expected}, got {type(raw).__name__}")
        val = _tmpl(raw, base) if isinstance(raw, str) else raw
        if choices is not None and val not in choices:
            raise RuntimeError(f"Action '{name}' input '{key}'={val!r} not in choices {choices}")
        params[key] = val
    return params


def _dedup_extend(dst: list[str], items: Any, ctx: dict[str, Any]) -> None:
    for item in items or []:
        rendered = _tmpl(item, ctx)
        if rendered not in dst:
            dst.append(rendered)


def _truthy(expr: str, ctx: dict[str, Any]) -> bool:
    """Evaluate a step `if:` Jinja expression against ctx (e.g. "arch[0] == 'x86_64'")."""
    return _tmpl("{{ " + expr + " }}", ctx).strip() not in ("", "False", "None", "0")


def _decorate(body: str, name: str, env: dict[str, Any] | None, ctx: dict[str, Any]) -> str:
    """Prefix a phase body with a `# name` comment and any `export KEY="val"` env lines.

    env is emitted per phase because PKGBUILD phase functions are separate shell scopes.
    """
    lines = [f"# {name}"]
    for key, val in (env or {}).items():
        lines.append(f'export {key}="{_tmpl(str(val), ctx)}"')
    lines.append(body)
    return "\n".join(lines)


def _assemble_functions(bodies: dict[str, list[str]]) -> str:
    out: list[str] = []
    for phase in ("pkgver", "prepare", "build", "package"):
        if bodies[phase]:
            out.append(f"{phase}() {{\n" + "\n".join(bodies[phase]) + "\n}")
    return "\n\n".join(out)


def render(cfg: dict[str, Any], pkgver: str) -> str:
    """Render a full PKGBUILD from an ``actions`` package config."""
    # `steps` accumulates each step's outputs so later steps can reference
    # {{ steps['<id>'].outputs.<name> }} in their `with:` values (render-time wiring).
    steps_ctx: dict[str, Any] = {}
    base = {"pkgname": cfg["pkgname"], "pkgver": pkgver,
            "arch": cfg.get("arch", []), "steps": steps_ctx}
    depends = list(cfg.get("depends", []))
    makedepends = list(cfg.get("makedepends", []))
    sources: list[str] = []
    bodies: dict[str, list[str]] = {p: [] for p in PHASES}
    pkg = cfg["pkgname"]

    steps = cfg.get("steps") or []
    if not steps:
        raise RuntimeError(f"{pkg}: type 'actions' requires a non-empty 'steps' list")

    for step in steps:
        if ("uses" in step) == ("run" in step):
            raise RuntimeError(f"{pkg}: each step needs exactly one of 'uses' or 'run'")
        # `if:` — skip the step when its expression is falsy (evaluated at render time).
        if "if" in step and not _truthy(step["if"], base):
            continue
        env = step.get("env")

        # Inline `run:` step — bash appended to one phase, no action file needed.
        if "run" in step:
            phase = step.get("phase", "build")
            if phase not in ("prepare", "build", "package"):
                raise RuntimeError(f"{pkg}: run step phase must be prepare/build/package, got '{phase}'")
            body = _tmpl(step["run"], base).rstrip("\n")
            bodies[phase].append(_decorate(body, step.get("name", "run"), env, base))
            continue

        action = _load_action(step["uses"])
        step_id = step.get("id", step["uses"])
        name = step.get("name", step["uses"])
        ctx = {**base, **_resolve_inputs(action, step, base)}
        _dedup_extend(depends, action.get("depends"), ctx)
        _dedup_extend(makedepends, action.get("makedepends"), ctx)
        for src in action.get("sources", []) or []:
            sources.append(_tmpl(src, ctx))
        for phase in PHASES:
            body = action.get(phase)
            if not body:
                continue
            rendered = _tmpl(body, ctx).rstrip("\n")
            # pkgver() is a standalone function; don't inject comment/env into it.
            bodies[phase].append(rendered if phase == "pkgver" else _decorate(rendered, name, env, ctx))
        # Publish this step's outputs for subsequent steps (mutates steps_ctx in base).
        steps_ctx[step_id] = {"outputs": {
            oname: _tmpl(oexpr, ctx) for oname, oexpr in (action.get("outputs") or {}).items()
        }}

    # ponytail: only git sources are used today, all checksummed SKIP.
    # Add real sha256 resolution here if a non-git source is ever composed in.
    sha256sums = ["SKIP"] * len(sources)

    return Template(TEMPLATE.read_text()).render(
        pkgname=cfg["pkgname"],
        pkgver=pkgver,
        pkgdesc=cfg.get("pkgdesc", ""),
        arch=cfg.get("arch", ["any"]),
        url=cfg.get("url", ""),
        license=cfg.get("license", ["custom"]),
        depends=depends,
        makedepends=makedepends,
        optdepends=cfg.get("optdepends", []),
        options=cfg.get("options", []),
        conflicts=cfg.get("conflicts", []),
        provides=cfg.get("provides", []),
        sources=sources,
        sha256sums=sha256sums,
        functions=_assemble_functions(bodies),
    )
