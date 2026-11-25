#!/usr/bin/env python3
"""Run build and publish process for all packages and generate report."""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from typing import Any

import yaml  # type: ignore[import-untyped]

from build import build
from aur import publish_all


def changed_files_since(ref: str) -> list[str] | None:
    """Files changed between `ref` and HEAD, or None when that diff cannot be taken."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{ref}...HEAD"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"⚠️  Could not diff against {ref} ({e})")
        return None
    return [line for line in proc.stdout.splitlines() if line]


def select_packages(changed: list[str], all_packages: list[str]) -> list[str]:
    """Pick which package configs a set of changed files affects.

    Anything outside packages/ is render-engine input (scripts/, templates/, actions/,
    schema/) and can change every package's PKGBUILD, so every config is checked. A
    change confined to packages/ only affects the configs it touches.
    """
    if any(not f.startswith("packages/") for f in changed):
        return all_packages
    return sorted(f for f in changed if f in all_packages)


def main() -> int:
    """Run build and publish process for all packages.

    Returns:
        Exit code (0 for success, 1 if any failures)
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report what would be published to AUR without downloading sources, "
            "writing local state, or publishing anything (used by PR checks)."
        ),
    )
    parser.add_argument(
        "--changed-since",
        metavar="REF",
        help=(
            "Only process the packages a change since REF affects: the touched "
            "packages/*.yaml, or every package when the render engine (scripts, "
            "templates, actions, schema) changed."
        ),
    )
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    print("\n" + "="*70)
    print("🧪 AUR PACKAGE DRY RUN (no publish)" if dry_run else "🚀 AUR PACKAGE UPDATE RUNNER")
    print("="*70)

    pkg_files = sorted(glob.glob("packages/*.yaml"))
    if args.changed_since:
        changed = changed_files_since(args.changed_since)
        if changed is not None:
            pkg_files = select_packages(changed, pkg_files)
            print(f"\n🔍 Scope: {len(changed)} file(s) changed since {args.changed_since}")
            if not pkg_files:
                print("   No package configs affected - nothing to do")

    print(f"\n📦 Found {len(pkg_files)} package(s) to process\n")

    failures: list[dict[str, Any]] = []
    updated: list[dict[str, str]] = []
    created: list[dict[str, str]] = []
    unchanged: list[str] = []

    for i, pkgfile in enumerate(pkg_files, 1):
        print(f"\n{'='*70}")
        print(f"🔢 [{i}/{len(pkg_files)}] Processing {pkgfile}...")
        print(f"{'='*70}")
        result = build(pkgfile, dry_run=dry_run)

        if result is None:
            pkgname = yaml.safe_load(open(pkgfile))["pkgname"]
            unchanged.append(pkgname)
            continue

        if "error" in result:
            failures.append(result)
        elif result.get("status") == "created":
            created.append(result)
        else:
            updated.append(result)

    # Publish packages that were created or updated
    packages_to_publish = created + updated

    publish_report = {"published": [], "publish_failures": []}
    if packages_to_publish and not dry_run:
        print("\n\n" + "="*70)
        print("🚀 PUBLISHING PACKAGES TO AUR")
        print("="*70)
        publish_report = publish_all(packages_to_publish)

        # Add publish failures to main failures list
        for fail in publish_report.get("failures", []):
            failures.append(fail)

    # Generate comprehensive report
    report = {
        "summary": {
            "dry_run": dry_run,
            "total_packages": len(pkg_files),
            "created": len(created),
            "updated": len(updated),
            "unchanged": len(unchanged),
            "failures": len(failures),
            "published": len(publish_report.get("published", [])),
            "publish_failures": len(publish_report.get("publish_failures", []))
        },
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "failures": failures,
        "published": publish_report.get("published", []),
        "publish_failures": publish_report.get("publish_failures", [])
    }

    with open("report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Print summary with enhanced formatting
    print("\n\n" + "="*70)
    print("📊 FINAL SUMMARY REPORT")
    print("="*70)

    if created:
        print(f"\n✨ NEW PACKAGES CREATED ({len(created)}):")
        for pkg in created:
            print(f"   🎉 {pkg['pkgname']}")

    if updated:
        print(f"\n🔄 PACKAGES UPDATED ({len(updated)}):")
        for pkg in updated:
            print(f"   ✅ {pkg['pkgname']}")

    if unchanged:
        print(f"\n⏭️  PACKAGES UNCHANGED ({len(unchanged)}):")
        for pkgname in unchanged:
            print(f"   ✔️  {pkgname}")

    if dry_run:
        if packages_to_publish:
            print(f"\n🧪 WOULD PUBLISH TO AUR ({len(packages_to_publish)}):")
            for pkg in packages_to_publish:
                print(f"   📤 {pkg['pkgname']} ({pkg['status']})")
        else:
            print("\n🧪 WOULD PUBLISH TO AUR (0): every package is already up to date")
    elif publish_report.get("published"):
        print(f"\n🚀 PACKAGES PUBLISHED TO AUR ({len(publish_report['published'])}):")
        for pkg in publish_report["published"]:
            print(f"   📤 {pkg['pkgname']}")

    if failures:
        print(f"\n❌ BUILD/PUBLISH FAILURES ({len(failures)}):")
        for fail in failures:
            print(f"   💥 {fail['pkgname']}: {fail['error']}")

    print("\n" + "-"*70)
    print(f"📈 STATISTICS:")
    print(f"   Total Packages:    {len(pkg_files)}")
    print(f"   ✨ Created:         {len(created)}")
    print(f"   🔄 Updated:         {len(updated)}")
    print(f"   ⏭️  Unchanged:      {len(unchanged)}")
    if dry_run:
        print(f"   🧪 Would publish:   {len(packages_to_publish)}")
    else:
        print(f"   🚀 Published:       {len(publish_report.get('published', []))}")
    print(f"   ❌ Failures:        {len(failures)}")
    print("-"*70)

    if failures:
        print("\n⚠️  Build completed with failures!")
        return 1

    if dry_run:
        print("\n✅ Dry run complete - nothing was published to AUR.")
        return 0

    print("\n✅ Build and publish completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())