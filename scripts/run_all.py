#!/usr/bin/env python3
"""Run builds for all packages and generate a report."""

import glob
import json
import sys
from typing import Any

import yaml  # type: ignore[import-untyped]

from build import build


def main() -> None:
    """Build all packages and generate a report."""
    failures: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []

    for pkgfile in glob.glob("packages/*.yaml"):
        result = build(pkgfile)

        if result is None:
            continue

        if "error" in result:
            failures.append(result)
        else:
            updated.append(result)

    report = {
        "updated": updated,
        "failures": failures
    }

    with open("report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(report)

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()