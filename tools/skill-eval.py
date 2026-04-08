#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Skill Eval Framework — deterministic eval runner for skill trigger/routing correctness.

Reads eval cases from ./skills/SKILL_NAME/eval-cases.json, calls claude --print
with the SKILL.md as system prompt, and scores activated/route against expected values.

Usage:
    skill-eval.py web-search          # eval one skill
    skill-eval.py --all               # eval all skills that have eval-cases.json
    skill-eval.py --all --verbose      # show per-case details
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude" / "skills"

EVAL_SYSTEM_PROMPT = """You are a skill-activation classifier. You will receive a user prompt.
Your job is to determine whether this skill should be activated for the given user prompt.

RULES:
1. Read the skill description, triggers, and not_for fields carefully.
2. If the user prompt matches a trigger pattern, set activated=true.
3. If the user prompt matches a not_for pattern, set activated=false.
4. If activated=true and the skill has delegates_to, determine if the prompt should be routed
   to a delegated skill instead. If so, set route to that skill name. Otherwise route=null.
5. Respond with ONLY valid JSON, no markdown fences, no explanation.

Response format:
{"activated": true, "route": "route_name_or_null", "reasoning": "one line"}
"""


def find_skills_with_evals() -> list[str]:
    """Find all skills that have eval-cases.json."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "eval-cases.json").exists():
            skills.append(skill_dir.name)
    return skills


def load_eval_cases(skill_name: str) -> list[dict]:
    """Load eval cases for a skill."""
    path = SKILLS_DIR / skill_name / "eval-cases.json"
    if not path.exists():
        print(f"  No eval-cases.json found for {skill_name}", file=sys.stderr)
        return []
    with open(path) as f:
        return json.load(f)


def load_skill_md(skill_name: str) -> str:
    """Load SKILL.md content."""
    path = SKILLS_DIR / skill_name / "SKILL.md"
    if not path.exists():
        return ""
    return path.read_text()


def run_eval_case(skill_name: str, case: dict, skill_md: str) -> dict:
    """Run a single eval case via claude --print."""
    # Build the system prompt: skill content + eval instructions
    system_content = (
        f"# SKILL.md for /{skill_name}\n\n{skill_md}\n\n---\n\n{EVAL_SYSTEM_PROMPT}"
    )

    # Write system prompt to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(system_content)
        system_file = f.name

    try:
        user_prompt = case["input"]
        result = subprocess.run(
            [
                "claude",
                "--print",
                "--model",
                "opus",
                "-p",
                user_prompt,
                "--append-system-prompt-file",
                system_file,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        raw_output = result.stdout.strip()

        # Try to parse JSON from the output
        response = _extract_json(raw_output)
        if response is None:
            return {
                "case_id": case["id"],
                "status": "parse_error",
                "raw_output": raw_output[:500],
                "trigger_correct": False,
                "route_correct": None,
            }

        # Score: compare activated vs expected_trigger
        activated = response.get("activated", False)
        expected_trigger = case["expected_trigger"]
        trigger_correct = activated == expected_trigger

        # Score: compare route vs expected_route (if present)
        route_correct = None
        if "expected_route" in case:
            actual_route = response.get("route")
            # Normalize null/None/"null" comparisons
            expected_route = case["expected_route"]
            if expected_route is None or expected_route == "null":
                expected_route = None
            if actual_route is None or actual_route == "null":
                actual_route = None
            route_correct = actual_route == expected_route

        return {
            "case_id": case["id"],
            "status": "ok",
            "activated": activated,
            "expected_trigger": expected_trigger,
            "trigger_correct": trigger_correct,
            "route": response.get("route"),
            "expected_route": case.get("expected_route"),
            "route_correct": route_correct,
            "reasoning": response.get("reasoning", ""),
        }

    except subprocess.TimeoutExpired:
        return {
            "case_id": case["id"],
            "status": "timeout",
            "trigger_correct": False,
            "route_correct": None,
        }
    except Exception as e:
        return {
            "case_id": case["id"],
            "status": "error",
            "error": str(e),
            "trigger_correct": False,
            "route_correct": None,
        }
    finally:
        os.unlink(system_file)


def _extract_json(text: str) -> dict | None:
    """Extract JSON from claude output, handling markdown fences."""
    # Strip markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


def eval_skill(skill_name: str, verbose: bool = False) -> dict:
    """Evaluate all cases for a skill."""
    cases = load_eval_cases(skill_name)
    if not cases:
        return {"skill": skill_name, "total": 0, "results": []}

    skill_md = load_skill_md(skill_name)
    if not skill_md:
        print(f"  WARNING: No SKILL.md found for {skill_name}", file=sys.stderr)

    results = []
    for case in cases:
        if verbose:
            print(f"  Running case: {case['id']} ...", end=" ", flush=True)
        r = run_eval_case(skill_name, case, skill_md)
        results.append(r)
        if verbose:
            status = "PASS" if r["trigger_correct"] else "FAIL"
            if r.get("route_correct") is not None and not r["route_correct"]:
                status = "FAIL (route)"
            print(status)

    # Compute scores
    total = len(results)
    trigger_correct = sum(1 for r in results if r["trigger_correct"])
    route_cases = [r for r in results if r.get("route_correct") is not None]
    route_correct = sum(1 for r in route_cases if r["route_correct"])
    errors = sum(1 for r in results if r["status"] != "ok")

    # Overall: a case passes if trigger is correct AND (route is correct or not tested)
    passed = sum(
        1
        for r in results
        if r["trigger_correct"]
        and (r.get("route_correct") is None or r["route_correct"])
    )

    return {
        "skill": skill_name,
        "total": total,
        "passed": passed,
        "trigger_correct": trigger_correct,
        "route_tested": len(route_cases),
        "route_correct": route_correct,
        "errors": errors,
        "results": results,
    }


def print_scorecard(score: dict, verbose: bool = False):
    """Print scorecard for a skill."""
    skill = score["skill"]
    total = score["total"]

    if total == 0:
        print(f"\n  {skill}: no eval cases found")
        return

    passed = score["passed"]
    pct = (passed / total * 100) if total > 0 else 0
    icon = "PASS" if passed == total else "FAIL"

    print(f"\n  [{icon}] /{skill}: {passed}/{total} ({pct:.0f}%)")
    print(f"    Trigger: {score['trigger_correct']}/{total} correct")
    if score["route_tested"] > 0:
        print(f"    Route:   {score['route_correct']}/{score['route_tested']} correct")
    if score["errors"] > 0:
        print(f"    Errors:  {score['errors']}")

    if verbose:
        for r in score["results"]:
            status = "PASS" if r["trigger_correct"] else "FAIL"
            if r.get("route_correct") is not None and not r["route_correct"]:
                status = "FAIL"
            detail = f"    {status:4s} | {r['case_id']}"
            if r["status"] != "ok":
                detail += f" ({r['status']})"
            else:
                detail += f" | activated={r['activated']}"
                if r.get("route") is not None:
                    detail += f" route={r['route']}"
                if r.get("reasoning"):
                    detail += f" | {r['reasoning'][:60]}"
            print(detail)


def main():
    parser = argparse.ArgumentParser(
        description="Skill Eval Framework — deterministic trigger/routing eval"
    )
    parser.add_argument(
        "skill",
        nargs="?",
        help="Skill name to evaluate (or use --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate all skills with eval-cases.json",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-case details",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    if not args.skill and not args.all:
        parser.print_help()
        sys.exit(1)

    if args.all:
        skills = find_skills_with_evals()
        if not skills:
            print("No skills with eval-cases.json found.")
            sys.exit(1)
    else:
        skills = [args.skill]

    print(f"Skill Eval — evaluating {len(skills)} skill(s)")
    print("=" * 50)

    all_scores = []
    for skill in skills:
        print(f"\nEvaluating /{skill} ...")
        score = eval_skill(skill, verbose=args.verbose)
        all_scores.append(score)
        print_scorecard(score, verbose=args.verbose)

    # Overall summary
    total_cases = sum(s["total"] for s in all_scores)
    total_passed = sum(s.get("passed", 0) for s in all_scores)
    total_errors = sum(s.get("errors", 0) for s in all_scores)

    print("\n" + "=" * 50)
    print(f"OVERALL: {total_passed}/{total_cases} passed", end="")
    if total_cases > 0:
        print(f" ({total_passed / total_cases * 100:.0f}%)", end="")
    if total_errors > 0:
        print(f" | {total_errors} errors", end="")
    print()

    if args.json:
        # Strip detailed results for cleaner JSON
        for s in all_scores:
            for r in s["results"]:
                r.pop("raw_output", None)
        print(json.dumps(all_scores, indent=2, ensure_ascii=False))

    sys.exit(0 if total_passed == total_cases else 1)


if __name__ == "__main__":
    main()
