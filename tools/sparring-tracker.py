#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Model Sparring Tracker — Opus vs Codex Difference Tracking

Tracks interesting differences between Opus 4.6 and Codex (GPT-5.4)
from real consultations. Builds empirical model-routing data over time.

Usage:
  sparring-tracker.py add --date 2026-03-18 --domain browser-api ...
  sparring-tracker.py stats
  sparring-tracker.py patterns
  sparring-tracker.py report [--html]
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "data" / "model-sparring.jsonl"

VALID_DOMAINS = [
    "browser-api",
    "css-design",
    "architecture",
    "debugging",
    "code-review",
    "performance",
    "security",
    "devops",
    "data-analysis",
    "research",
    "ux-design",
    "documentation",
    "testing",
    "refactoring",
    "other",
]
VALID_TASK_TYPES = [
    "bug-fix",
    "code-review",
    "greenfield",
    "refactor",
    "design-decision",
    "research",
    "optimization",
    "other",
]
VALID_AGREEMENTS = ["agree", "partial", "disagree"]
VALID_WINNERS = ["opus", "codex", "tie", "both-wrong"]
VALID_CONFIDENCE = ["low", "medium", "high"]


def load_entries():
    if not DB_PATH.exists():
        return []
    entries = []
    for line in DB_PATH.read_text().strip().split("\n"):
        if line.strip():
            entries.append(json.loads(line))
    return entries


def add_entry(args):
    entry = {
        "date": args.date,
        "session": args.session or "",
        "domain": args.domain,
        "task_type": args.task_type,
        "task_summary": args.summary,
        "opus_position": args.opus,
        "codex_position": args.codex,
        "agreement": args.agreement,
        "winner": args.winner,
        "confidence_opus": args.conf_opus,
        "confidence_codex": args.conf_codex,
        "insight": args.insight or "",
    }
    with open(DB_PATH, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"Added entry: {args.summary}")
    print(f"  Winner: {args.winner} | Agreement: {args.agreement}")


def show_stats(_args):
    entries = load_entries()
    if not entries:
        print("Keine Einträge vorhanden.")
        return

    total = len(entries)
    winners = Counter(e["winner"] for e in entries)
    domains = Counter(e["domain"] for e in entries)
    agreements = Counter(e["agreement"] for e in entries)

    print(f"\n{'=' * 50}")
    print(f"  Model Sparring Stats — {total} Konsultationen")
    print(f"{'=' * 50}\n")

    print("Gewinner:")
    for w in VALID_WINNERS:
        count = winners.get(w, 0)
        pct = count / total * 100 if total else 0
        bar = "█" * int(pct / 3)
        print(f"  {w:12s} {count:3d} ({pct:4.1f}%) {bar}")

    print("\nÜbereinstimmung:")
    for a in VALID_AGREEMENTS:
        count = agreements.get(a, 0)
        print(f"  {a:12s} {count:3d}")

    print("\nDomänen:")
    for domain, count in domains.most_common():
        print(f"  {domain:20s} {count:3d}")


def show_patterns(_args):
    entries = load_entries()
    if len(entries) < 3:
        print(
            f"Erst {len(entries)} Einträge — mindestens 3 für Pattern-Erkennung nötig."
        )
        return

    # Winner by domain
    domain_wins = defaultdict(Counter)
    for e in entries:
        domain_wins[e["domain"]][e["winner"]] += 1

    print(f"\n{'=' * 50}")
    print("  Patterns — Wer gewinnt wo?")
    print(f"{'=' * 50}\n")

    for domain, wins in sorted(domain_wins.items()):
        total = sum(wins.values())
        if total < 2:
            continue
        best = wins.most_common(1)[0]
        print(f"  {domain}: {best[0]} führt ({best[1]}/{total})")

    # Confidence calibration
    print("\nKonfidenz-Kalibrierung:")
    for model in ["opus", "codex"]:
        conf_key = f"confidence_{model}"
        high_conf = [e for e in entries if e.get(conf_key) == "high"]
        if high_conf:
            correct = sum(
                1 for e in high_conf if e["winner"] == model or e["winner"] == "tie"
            )
            print(
                f"  {model}: {correct}/{len(high_conf)} korrekt bei hoher Konfidenz ({correct / len(high_conf) * 100:.0f}%)"
            )


def generate_report(args):
    entries = load_entries()
    if not entries:
        print("Keine Einträge.")
        return

    if args.html:
        _generate_html_report(entries)
    else:
        show_stats(args)
        print()
        show_patterns(args)
        print("\nLetzte Insights:")
        for e in entries[-5:]:
            if e.get("insight"):
                print(f"  [{e['date']}] {e['insight']}")


def _generate_html_report(entries):
    total = len(entries)
    winners = Counter(e["winner"] for e in entries)

    rows = ""
    for e in reversed(entries):
        winner_color = {
            "opus": "#B87040",
            "codex": "#2563EB",
            "tie": "#6B7280",
            "both-wrong": "#DC2626",
        }.get(e["winner"], "#6B7280")

        rows += f"""<tr>
            <td>{e["date"]}</td>
            <td><span class="domain">{e["domain"]}</span></td>
            <td>{e["task_summary"]}</td>
            <td style="color:{winner_color};font-weight:600">{e["winner"]}</td>
            <td>{e["agreement"]}</td>
            <td class="insight">{e.get("insight", "")}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Model Sparring Report</title>
<style>
  body {{ font-family: system-ui; max-width: 1200px; margin: 2rem auto; padding: 0 1rem; background: #FAFAF8; color: #2D2D2A; }}
  h1 {{ font-size: 1.8rem; }}
  .stats {{ display: flex; gap: 1.5rem; margin: 1.5rem 0; }}
  .stat-card {{ background: white; border: 1px solid #E5E7EB; border-radius: 10px; padding: 1.5rem; text-align: center; flex: 1; }}
  .stat-card .num {{ font-size: 2.5rem; font-weight: 700; }}
  .stat-card .label {{ color: #6B7280; font-size: 0.9rem; }}
  .opus {{ color: #B87040; }}
  .codex {{ color: #2563EB; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1.5rem; }}
  th {{ text-align: left; padding: 0.7rem; border-bottom: 2px solid #E5E7EB; font-size: 0.85rem; color: #6B7280; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 0.7rem; border-bottom: 1px solid #E5E7EB; font-size: 0.9rem; }}
  .domain {{ background: #F3F4F6; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }}
  .insight {{ font-size: 0.8rem; color: #6B7280; max-width: 300px; }}
</style>
</head>
<body>
  <h1>Model Sparring Report</h1>
  <p>{total} Konsultationen</p>
  <div class="stats">
    <div class="stat-card"><div class="num opus">{winners.get("opus", 0)}</div><div class="label">Opus gewinnt</div></div>
    <div class="stat-card"><div class="num codex">{winners.get("codex", 0)}</div><div class="label">Codex gewinnt</div></div>
    <div class="stat-card"><div class="num">{winners.get("tie", 0)}</div><div class="label">Unentschieden</div></div>
    <div class="stat-card"><div class="num" style="color:#DC2626">{winners.get("both-wrong", 0)}</div><div class="label">Beide falsch</div></div>
  </div>
  <table>
    <tr><th>Datum</th><th>Domäne</th><th>Aufgabe</th><th>Gewinner</th><th>Übereinstimmung</th><th>Insight</th></tr>
    {rows}
  </table>
</body>
</html>"""
    out = Path.home() / "shared" / "reports" / "model-sparring.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"HTML-Report: {out}")


def main():
    parser = argparse.ArgumentParser(description="Model Sparring Tracker")
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add")
    p_add.add_argument("--date", required=True)
    p_add.add_argument("--session", default="")
    p_add.add_argument("--domain", required=True, choices=VALID_DOMAINS)
    p_add.add_argument("--task-type", required=True, choices=VALID_TASK_TYPES)
    p_add.add_argument("--summary", required=True)
    p_add.add_argument("--opus", required=True, help="Opus position/approach")
    p_add.add_argument("--codex", required=True, help="Codex position/approach")
    p_add.add_argument("--agreement", required=True, choices=VALID_AGREEMENTS)
    p_add.add_argument("--winner", required=True, choices=VALID_WINNERS)
    p_add.add_argument("--conf-opus", default="medium", choices=VALID_CONFIDENCE)
    p_add.add_argument("--conf-codex", default="medium", choices=VALID_CONFIDENCE)
    p_add.add_argument("--insight", default="")

    sub.add_parser("stats")
    sub.add_parser("patterns")
    p_report = sub.add_parser("report")
    p_report.add_argument("--html", action="store_true")

    args = parser.parse_args()
    if args.cmd == "add":
        add_entry(args)
    elif args.cmd == "stats":
        show_stats(args)
    elif args.cmd == "patterns":
        show_patterns(args)
    elif args.cmd == "report":
        generate_report(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
