#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Skill Maintenance — automated checks after skill changes.

Runs:
1. Routing table sync (update CLAUDE.md from frontmatter)
2. Frontmatter validation (required fields present)
3. Eval case runner (trigger/routing correctness)

Usage:
    skill-maintenance.py              # all checks, no evals (fast)
    skill-maintenance.py --with-eval  # all checks + eval runner (slow, needs claude CLI)
    skill-maintenance.py --check-only # dry-run, no writes
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

SKILLS_DIR = Path.home() / ".claude" / "skills"
CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
TOOLS_DIR = Path.home() / ".claude" / "tools"

REQUIRED_FIELDS = ["name", "description", "triggers", "not_for"]


def parse_frontmatter(skill_md: Path) -> dict | None:
    text = skill_md.read_text()
    match = re.match(r"^---\s*\n(.+?)\n---", text, re.DOTALL)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
        return data if isinstance(data, dict) else None
    except yaml.YAMLError:
        return None


def validate_frontmatter() -> list[str]:
    """Check all skills have required frontmatter fields."""
    issues = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        fm = parse_frontmatter(skill_md)
        if not fm:
            issues.append(f"{skill_dir.name}: no valid frontmatter")
            continue

        for field in REQUIRED_FIELDS:
            if field not in fm:
                issues.append(f"{skill_dir.name}: missing '{field}'")

        # Check triggers is a list
        triggers = fm.get("triggers")
        if triggers and not isinstance(triggers, list):
            issues.append(f"{skill_dir.name}: 'triggers' should be a list")

    return issues


def check_json_companions() -> list[str]:
    """Validate SKILL.json files are valid JSON with required fields."""
    issues = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        json_file = skill_dir / "SKILL.json"
        if not json_file.exists():
            continue

        try:
            data = json.loads(json_file.read_text())
        except json.JSONDecodeError as e:
            issues.append(f"{skill_dir.name}/SKILL.json: invalid JSON ({e})")
            continue

        if "activation" not in data:
            issues.append(f"{skill_dir.name}/SKILL.json: missing 'activation'")

    return issues


def sync_routing_table(dry_run: bool = False) -> bool:
    """Run skill-router.py update-claude-md."""
    if dry_run:
        result = subprocess.run(
            ["uv", "run", str(TOOLS_DIR / "skill-router.py"), "generate-table"],
            capture_output=True,
            text=True,
        )
        print("  [DRY-RUN] Would update CLAUDE.md routing table:")
        print(f"  {result.stdout.count(chr(10))} rows generated")
        return True

    result = subprocess.run(
        ["uv", "run", str(TOOLS_DIR / "skill-router.py"), "update-claude-md"],
        capture_output=True,
        text=True,
    )
    print(f"  {result.stdout.strip()}")
    return result.returncode == 0


def run_evals() -> dict:
    """Run skill-eval.py --all --json."""
    result = subprocess.run(
        ["uv", "run", str(TOOLS_DIR / "skill-eval.py"), "--all", "--json"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        print(f"  Eval runner failed: {result.stderr[:200]}")
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("  Could not parse eval output")
        return {}


def main():
    parser = argparse.ArgumentParser(description="Skill maintenance checks")
    parser.add_argument(
        "--with-eval",
        action="store_true",
        help="Also run eval cases (slow, needs claude CLI)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Dry-run, no writes",
    )
    args = parser.parse_args()

    print("=== Skill Maintenance ===\n")
    all_ok = True

    # 1. Validate frontmatter
    print("1. Frontmatter validation...")
    issues = validate_frontmatter()
    if issues:
        all_ok = False
        for issue in issues:
            print(f"  ⚠ {issue}")
    else:
        print("  ✓ All skills have valid frontmatter")

    # 2. Validate JSON companions
    print("\n2. JSON companion validation...")
    json_issues = check_json_companions()
    if json_issues:
        all_ok = False
        for issue in json_issues:
            print(f"  ⚠ {issue}")
    else:
        json_count = sum(
            1
            for d in SKILLS_DIR.iterdir()
            if d.is_dir() and (d / "SKILL.json").exists()
        )
        print(f"  ✓ {json_count} JSON companions valid")

    # 3. Sync routing table
    print("\n3. Routing table sync...")
    sync_routing_table(dry_run=args.check_only)

    # 4. Run evals (optional)
    if args.with_eval:
        print("\n4. Running evals...")
        results = run_evals()
        if results:
            for skill, data in results.items():
                passed = data.get("passed", 0)
                total = data.get("total", 0)
                status = "✓" if passed == total else "⚠"
                print(f"  {status} {skill}: {passed}/{total}")
        else:
            print("  ⚠ No eval results")
            all_ok = False

    print(f"\n{'✓ All checks passed' if all_ok else '⚠ Issues found'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
