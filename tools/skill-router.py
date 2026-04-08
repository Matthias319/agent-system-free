#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Skill Router — auto-generates routing table from SKILL.md frontmatter.

Two modes:
    skill-router.py generate-table   — markdown table for CLAUDE.md
    skill-router.py route "query"    — score skills by trigger keyword overlap

Parses YAML frontmatter from all SKILL.md files (triggers, not_for, delegates_to, bundle).
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

SKILLS_DIR = Path.home() / ".claude" / "skills"


def parse_frontmatter(skill_dir: Path) -> dict | None:
    """Parse YAML frontmatter from SKILL.md."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    text = skill_md.read_text()

    # Match YAML frontmatter between --- delimiters
    match = re.match(r"^---\s*\n(.+?)\n---", text, re.DOTALL)
    if not match:
        return None

    try:
        data = yaml.safe_load(match.group(1))
        if not isinstance(data, dict):
            return None
        data["_dir"] = skill_dir.name
        return data
    except yaml.YAMLError:
        return None


def load_all_skills() -> list[dict]:
    """Load frontmatter from all skills."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if skill_dir.is_dir():
            fm = parse_frontmatter(skill_dir)
            if fm:
                skills.append(fm)
    return skills


def generate_table(skills: list[dict]):
    """Generate markdown routing table from skill frontmatter."""
    print("| Trigger | Skill | Statt |")
    print("|---------|-------|-------|")

    for skill in skills:
        name = skill.get("name", skill["_dir"])
        triggers = skill.get("triggers", [])
        not_for = skill.get("not_for", [])
        delegates_to = skill.get("delegates_to", [])

        # Build trigger column: join trigger keywords, shortened
        trigger_str = ", ".join(triggers[:5])
        if len(triggers) > 5:
            trigger_str += ", ..."

        # Build "Statt" column from not_for
        statt_str = ", ".join(not_for[:3]) if not_for else "—"

        # Add delegation info if present
        delegates_note = ""
        if delegates_to:
            delegates_note = f" (→ {', '.join(delegates_to)})"

        print(f"| {trigger_str} | /{name}{delegates_note} | {statt_str} |")


def tokenize(text: str) -> set[str]:
    """Split text into lowercase tokens."""
    return set(re.findall(r"[a-zäöüß]+", text.lower()))


def score_skill(skill: dict, query_tokens: set[str], query_lower: str) -> float:
    """Score a skill against query tokens. Higher = better match."""
    triggers = skill.get("triggers", [])
    not_for = skill.get("not_for", [])

    score = 0.0

    # Check triggers
    for trigger in triggers:
        trigger_lower = trigger.lower()
        trigger_tokens = tokenize(trigger)

        # Exact substring match in query (strongest signal)
        if trigger_lower in query_lower:
            score += 3.0
            continue

        # Token overlap
        overlap = query_tokens & trigger_tokens
        if overlap:
            # Score by fraction of trigger tokens matched
            match_ratio = len(overlap) / max(len(trigger_tokens), 1)
            score += match_ratio * 2.0

    # Penalize if query matches not_for patterns
    for nf in not_for:
        nf_lower = nf.lower()
        if nf_lower in query_lower:
            score -= 2.0
            continue
        nf_tokens = tokenize(nf)
        overlap = query_tokens & nf_tokens
        if len(overlap) >= 2:
            score -= 1.0

    return max(score, 0.0)


def route_query(skills: list[dict], query: str, top_n: int = 3):
    """Score all skills against a query and return top matches."""
    query_lower = query.lower()
    query_tokens = tokenize(query)

    scored = []
    for skill in skills:
        s = score_skill(skill, query_tokens, query_lower)
        if s > 0:
            scored.append((skill, s))

    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        print(f'No matching skills for: "{query}"')
        return

    print(f'Top matches for: "{query}"')
    print("-" * 50)

    for i, (skill, s) in enumerate(scored[:top_n], 1):
        name = skill.get("name", skill["_dir"])
        desc = skill.get("description", "")
        triggers = ", ".join(skill.get("triggers", [])[:4])
        delegates = skill.get("delegates_to", [])

        print(f"  {i}. /{name} (score: {s:.1f})")
        print(f"     {desc}")
        print(f"     Triggers: {triggers}")
        if delegates:
            print(f"     Delegates to: {', '.join(delegates)}")
        print()


CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
TABLE_START = "| Trigger | Skill | Statt |"
TABLE_END_MARKER = "\n### "  # Next section after the table


def update_claude_md(skills: list[dict]) -> bool:
    """Replace the routing table in CLAUDE.md with auto-generated version."""
    if not CLAUDE_MD.exists():
        print("CLAUDE.md not found", file=sys.stderr)
        return False

    content = CLAUDE_MD.read_text()

    # Find the table
    start_idx = content.find(TABLE_START)
    if start_idx == -1:
        print("Routing table not found in CLAUDE.md", file=sys.stderr)
        return False

    # Find the end of the table (next ### heading or empty line after table)
    after_table = content[start_idx:]
    lines = after_table.split("\n")
    table_lines = []
    for i, line in enumerate(lines):
        if i == 0 or line.startswith("|") or line.strip() == "":
            table_lines.append(line)
        else:
            break

    # Remove trailing empty lines from table
    while table_lines and table_lines[-1].strip() == "":
        table_lines.pop()

    old_table = "\n".join(table_lines)

    # Generate new table
    import io

    buf = io.StringIO()
    _old_stdout = sys.stdout
    sys.stdout = buf
    generate_table(skills)
    sys.stdout = _old_stdout
    new_table = buf.getvalue().rstrip()

    # Replace
    new_content = content.replace(old_table, new_table)
    if new_content == content:
        print("Table unchanged")
        return False

    CLAUDE_MD.write_text(new_content)
    print(f"Updated routing table in CLAUDE.md ({len(skills)} skills)")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Skill Router — auto-routing from SKILL.md frontmatter"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser(
        "generate-table",
        help="Generate markdown routing table to stdout",
    )

    subparsers.add_parser(
        "update-claude-md",
        help="Update the routing table in ./CLAUDE.md in-place",
    )

    route_parser = subparsers.add_parser(
        "route",
        help="Route a user query to matching skills",
    )
    route_parser.add_argument("query", help="User query to route")
    route_parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of top matches to show (default: 3)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    skills = load_all_skills()
    if not skills:
        print("No skills found in", SKILLS_DIR, file=sys.stderr)
        sys.exit(1)

    if args.command == "generate-table":
        generate_table(skills)
    elif args.command == "update-claude-md":
        update_claude_md(skills)
    elif args.command == "route":
        route_query(skills, args.query, top_n=args.top)


if __name__ == "__main__":
    main()
