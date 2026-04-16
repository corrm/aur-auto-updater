#!/usr/bin/env python3
"""Run build and publish process for all packages and generate report."""
from __future__ import annotations

import glob
import json
import sys
from typing import Any

import yaml  # type: ignore[import-untyped]

from build import build
from aur import publish_all


def main() -> int:
    """Run build and publish process for all packages.

    Returns:
        Exit code (0 for success, 1 if any failures)
    """
    print("\n" + "="*70)
    print("🚀 AUR PACKAGE UPDATE RUNNER")
    print("="*70)

    pkg_files = sorted(glob.glob("packages/*.yaml"))
    print(f"\n📦 Found {len(pkg_files)} package(s) to process\n")

    failures: list[dict[str, Any]] = []
    updated: list[dict[str, str]] = []
    created: list[dict[str, str]] = []
    unchanged: list[str] = []

    for i, pkgfile in enumerate(pkg_files, 1):
        print(f"\n{'='*70}")
        print(f"🔢 [{i}/{len(pkg_files)}] Processing {pkgfile}...")
        print(f"{'='*70}")
        result = build(pkgfile)

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
    if packages_to_publish:
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

    if publish_report.get("published"):
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
    print(f"   🚀 Published:       {len(publish_report.get('published', []))}")
    print(f"   ❌ Failures:        {len(failures)}")
    print("-"*70)

    if failures:
        print("\n⚠️  Build completed with failures!")
        return 1

    print("\n✅ Build and publish completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())