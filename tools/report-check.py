#!/home/maetzger/.claude/tools/.venv/bin/python
"""Automatischer Self-Check für gerenderte HTML-Reports.

Prüft auf häufige Fehler: SAFE-Leaks, fehlende Quellen-Titel,
kaputte Details-Blöcke, leere Steps, etc.

Usage:
    python3 report-check.py report.html
    python3 report-check.py report.html --fix  # Zeigt Fixes
"""

import re
import sys
from pathlib import Path


def check_report(html_path: str) -> list[dict]:
    """Prüfe Report auf bekannte Fehler. Gibt Liste von Issues zurück."""
    path = Path(html_path)
    if not path.exists():
        return [{"severity": "error", "msg": f"Datei nicht gefunden: {path}"}]

    # Binary-safe lesen
    raw = path.read_bytes()
    html = raw.decode("utf-8", errors="replace")
    issues = []

    # 1. SAFE-Marker Leaks (Null-Byte oder ohne)
    safe_null = raw.count(b"\x00SAFE")
    safe_text = len(re.findall(r"(?<!\x00)SAFE\d+(?!\x00)", html))
    if safe_null > 0:
        issues.append(
            {
                "severity": "error",
                "msg": f"SAFE-Marker mit Null-Bytes gefunden: {safe_null}x",
                "fix": "report-renderer.py md() Restore-Reihenfolge prüfen (reverse!)",
            }
        )
    if safe_text > 0:
        issues.append(
            {
                "severity": "error",
                "msg": f"SAFE-Marker ohne Null-Bytes (Leak): {safe_text}x",
                "fix": "md() Funktion hat Platzhalter nicht korrekt aufgelöst",
            }
        )

    # 2. Leere Source-Links
    empty_links = re.findall(r'class="source-link"></a>', html)
    if empty_links:
        issues.append(
            {
                "severity": "error",
                "msg": f"Quellen ohne Titel: {len(empty_links)}x",
                "fix": "JSON: 'label' → 'title' für Quellen-Einträge",
            }
        )

    # 3. Kaputte Details-Blöcke
    details_open = len(re.findall(r"<details", html))
    details_close = len(re.findall(r"</details>", html))
    if details_open != details_close:
        issues.append(
            {
                "severity": "error",
                "msg": f"Details-Tags unbalanciert: {details_open} open vs {details_close} close",
            }
        )

    # 4. Bilder prüfen (relative Pfade)
    img_srcs = re.findall(r'<img[^>]+src="([^"]+)"', html)
    report_dir = path.parent
    for src in img_srcs:
        if src.startswith(("data:", "http://", "https://")):
            continue
        img_path = report_dir / src
        if not img_path.exists():
            issues.append(
                {
                    "severity": "warning",
                    "msg": f"Bild nicht gefunden: {src}",
                    "fix": f"Datei nach {report_dir}/{src} kopieren",
                }
            )

    # 5. Escaped HTML in Steps (Zeichen wie &lt; wo Tags sein sollten)
    escaped_tags = re.findall(r"&lt;(?:strong|em|br|img|a |details|code)", html)
    if escaped_tags:
        issues.append(
            {
                "severity": "warning",
                "msg": f"Escaped HTML-Tags in Content: {len(escaped_tags)}x ({escaped_tags[:3]})",
                "fix": "md() schützt diese Tags nicht — regex in _protect erweitern",
            }
        )

    # 6. Steps zählen
    steps = re.findall(r'"step-num">\d+', html)
    if steps:
        nums = [int(re.search(r"\d+", s).group()) for s in steps]
        expected = list(range(1, len(nums) + 1))
        if nums != expected:
            issues.append(
                {
                    "severity": "warning",
                    "msg": f"Step-Nummern nicht sequenziell: {nums}",
                }
            )

    return issues


def main():
    if len(sys.argv) < 2:
        print("Usage: report-check.py <report.html>", file=sys.stderr)
        sys.exit(1)

    html_path = sys.argv[1]
    show_fix = "--fix" in sys.argv

    issues = check_report(html_path)

    if not issues:
        print(f"✓ {html_path}: Keine Fehler gefunden")
        sys.exit(0)

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    print(
        f"{'✗' if errors else '⚠'} {html_path}: {errors} Fehler, {warnings} Warnungen"
    )

    for issue in issues:
        icon = "✗" if issue["severity"] == "error" else "⚠"
        print(f"  {icon} {issue['msg']}")
        if show_fix and "fix" in issue:
            print(f"    → Fix: {issue['fix']}")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
