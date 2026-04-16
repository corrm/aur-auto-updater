import glob
import yaml
import json
import sys
from build import build

failures = []
updated = []

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