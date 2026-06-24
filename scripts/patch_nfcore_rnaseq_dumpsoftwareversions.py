#!/usr/bin/env python3
"""Patch nf-core/rnaseq software-version collation for ARM64 toolbox runs.

nf-core/rnaseq 3.14.0 collects many per-process versions.yml files into a
single collated_versions.yml file. With custom ARM64 toolbox images, some tool
version strings can contain non-UTF8 bytes or unquoted colon-separated text
such as Samtools compilation details. PyYAML then fails in the final
CUSTOM_DUMPSOFTWAREVERSIONS task even though the analysis tasks completed.

This script patches the cached nf-core template so generated task scripts read
the collated versions file defensively and quote unsafe scalar values.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable


DEFAULT_GLOB = (
    "/config/nextflow-home/assets/.repos/nf-core/rnaseq/clones/*/"
    "modules/nf-core/custom/dumpsoftwareversions/templates/dumpsoftwareversions.py"
)


OLD_BLOCKS = (
    '''    with open("$versions") as f:
        versions_by_process = yaml.load(f, Loader=yaml.BaseLoader) | versions_this_module
''',
    '''    with open("collated_versions.yml") as f:
        versions_by_process = yaml.load(f, Loader=yaml.BaseLoader) | versions_this_module
''',
)


PATCHED_BLOCK_TEMPLATE = '''    with open({versions_arg}, "rb") as f:
        raw_versions = f.read().decode("utf-8", errors="replace")

    cleaned_lines = []
    for line in raw_versions.splitlines():
        stripped = line.strip()
        if ": " in line and stripped and not stripped.endswith(":"):
            indent = line[:len(line) - len(line.lstrip())]
            key, value = line.lstrip().split(": ", 1)
            if value and not value.startswith(('"', "'", "{{", "[", "|", ">")):
                value = json.dumps(value)
                line = f"{{indent}}{{key}}: {{value}}"
        cleaned_lines.append(line)

    versions_by_process = yaml.load(chr(10).join(cleaned_lines), Loader=yaml.BaseLoader) | versions_this_module
'''


def iter_targets(patterns: Iterable[str]) -> list[Path]:
    targets: list[Path] = []
    for pattern in patterns:
        path = Path(pattern)
        if any(ch in pattern for ch in "*?[]"):
            targets.extend(Path("/").glob(pattern.lstrip("/")))
        elif path.exists():
            targets.append(path)
    return sorted(set(targets))


def patch_file(path: Path, dry_run: bool) -> str:
    original = path.read_text()

    if "raw_versions = f.read().decode" in original and "chr(10).join(cleaned_lines)" in original:
        return "already patched"

    patched = original
    if "import json" not in patched:
        patched = patched.replace("import yaml\n", "import yaml\nimport json\n")

    changed = False
    for old in OLD_BLOCKS:
        if old not in patched:
            continue
        versions_arg = '"$versions"' if '"$versions"' in old else '"collated_versions.yml"'
        patched = patched.replace(old, PATCHED_BLOCK_TEMPLATE.format(versions_arg=versions_arg))
        changed = True

    if not changed:
        return "expected block not found"

    if not dry_run:
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            backup.write_text(original)
        path.write_text(patched)

    return "would patch" if dry_run else "patched"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch cached nf-core/rnaseq dumpsoftwareversions.py templates."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=[DEFAULT_GLOB],
        help="Template file path(s) or glob(s). Defaults to the /config Nextflow cache.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing files.")
    args = parser.parse_args()

    targets = iter_targets(args.targets)
    if not targets:
        print("No dumpsoftwareversions.py templates found.")
        return 1

    failed = False
    for target in targets:
        result = patch_file(target, args.dry_run)
        print(f"{result}: {target}")
        if result == "expected block not found":
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
