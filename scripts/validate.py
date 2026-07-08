#!/usr/bin/env python3
"""Validate all package and action YAML files against their schemas.

Package configs are checked against schema/package.schema.json; action definitions
against schema/action.schema.json. For `type: actions` packages we additionally
dry-run the actions engine, which enforces the runtime rules (unknown/required inputs,
choices, types, unknown actions, output references).
"""

import glob
import json
import sys
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

sys.path.insert(0, "scripts")
import actions  # noqa: E402


def _validate(files: list[str], schema: dict[str, Any], failures: list[dict[str, str]],
              extra: Any = None) -> list[str]:
    """Validate each YAML file against `schema`; run optional `extra(path, data)` check."""
    validated: list[str] = []
    for path in files:
        try:
            data = yaml.safe_load(open(path))
            jsonschema.validate(instance=data, schema=schema)
            if extra:
                extra(path, data)
            validated.append(path)
            print(f"✓ {path}")
        except jsonschema.ValidationError as e:
            failures.append({"file": path, "error": e.message})
            print(f"✗ {path}: {e.message}")
        except Exception as e:
            failures.append({"file": path, "error": str(e)})
            print(f"✗ {path}: {e}")
    return validated


def _dry_run_actions(path: str, pkg: dict[str, Any]) -> None:
    """Compose the PKGBUILD to surface any actions-engine rule violation as an error."""
    if pkg.get("type") == "actions":
        actions.render(pkg, pkgver="0")


def main() -> None:
    """Validate all package and action YAML files against their schemas."""
    package_schema = json.load(open("schema/package.schema.json"))
    action_schema = json.load(open("schema/action.schema.json"))

    failures: list[dict[str, str]] = []

    print("Packages:")
    pkgs = _validate(sorted(glob.glob("packages/*.yaml")), package_schema, failures, _dry_run_actions)
    print("\nActions:")
    acts = _validate(sorted(glob.glob("actions/*.yaml")), action_schema, failures)

    print(f"\nValidated: {len(pkgs) + len(acts)} ({len(pkgs)} packages, {len(acts)} actions), "
          f"Failures: {len(failures)}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
