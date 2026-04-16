#!/usr/bin/env python3
"""Validate all package YAML files against the schema."""

import glob
import json
import sys
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]


def main() -> None:
    """Validate all package YAML files against the schema."""
    schema_path = "schema/package.schema.json"
    
    with open(schema_path) as f:
        schema = json.load(f)
    
    failures: list[dict[str, str]] = []
    validated: list[str] = []
    
    for pkgfile in glob.glob("packages/*.yaml"):
        try:
            with open(pkgfile) as f:
                pkg = yaml.safe_load(f)
            
            jsonschema.validate(instance=pkg, schema=schema)
            validated.append(pkgfile)
            print(f"✓ {pkgfile}")
        except jsonschema.ValidationError as e:
            failures.append({"file": pkgfile, "error": e.message})
            print(f"✗ {pkgfile}: {e.message}")
        except Exception as e:
            failures.append({"file": pkgfile, "error": str(e)})
            print(f"✗ {pkgfile}: {str(e)}")
    
    print(f"\nValidated: {len(validated)}, Failures: {len(failures)}")
    
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
