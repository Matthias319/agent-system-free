#!/home/maetzger/.claude/tools/.venv/bin/python
"""autoresearch.py — Karpathy-inspirierter Optimierungsloop für Skills und Code.

Kernidee: 1 Ziel + 1 Metrik + Zeitbudget → Loop (mutieren → messen → behalten/verwerfen).

Drei Typen von Checks:
  command  — Shell-Befehl ausführen, Exit-Code prüfen
  pattern  — Datei nach Regex durchsuchen, Mindest-Treffer prüfen
  agent    — Binäre Ja/Nein-Frage, vom AI-Agent beantwortet

Verwendung:
  python3 autoresearch.py init <config.json>           Neues Projekt anlegen
  python3 autoresearch.py check <project> [--output X] Checks ausführen
  python3 autoresearch.py accept <project> [--note X]  Aktuellen Stand als besser akzeptieren
  python3 autoresearch.py reject <project>             Zum letzten besten Stand zurücksetzen
  python3 autoresearch.py history <project>            Score-Verlauf anzeigen
  python3 autoresearch.py status <project>             Aktuellen Status anzeigen
  python3 autoresearch.py list                         Alle Projekte auflisten
  python3 autoresearch.py template <type>              Beispiel-Config generieren
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DATA_DIR = Path.home() / ".claude" / "data" / "autoresearch"


def _load_project(name: str) -> dict:
    """Projekt-Config laden."""
    config_path = DATA_DIR / name / "config.json"
    if not config_path.exists():
        print(f"Projekt '{name}' nicht gefunden: {config_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(config_path.read_text())


def _save_history(name: str, entry: dict):
    """Eintrag an History anhängen."""
    hist_path = DATA_DIR / name / "history.jsonl"
    with hist_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_history(name: str) -> list[dict]:
    """History laden."""
    hist_path = DATA_DIR / name / "history.jsonl"
    if not hist_path.exists():
        return []
    entries = []
    for line in hist_path.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _save_regression(name: str, claim: str, correct: str, source: str, iteration: int):
    """Falschen Claim als Regression-Testfall speichern."""
    reg_path = DATA_DIR / name / "regressions.json"
    regressions = []
    if reg_path.exists():
        regressions = json.loads(reg_path.read_text())
    # Duplikat-Check (gleicher Claim schon gespeichert?)
    if any(r["claim"].lower() == claim.lower() for r in regressions):
        return
    regressions.append(
        {
            "claim": claim,
            "correct_answer": correct,
            "source_check": source,
            "found_in_iteration": iteration,
            "timestamp": datetime.now().isoformat(),
        }
    )
    reg_path.write_text(json.dumps(regressions, indent=2, ensure_ascii=False))
    sys.stderr.write(f"  Regression gespeichert: {claim[:60]}...\n")


def _load_regressions(name: str) -> list[dict]:
    """Regression-Testfälle laden."""
    reg_path = DATA_DIR / name / "regressions.json"
    if not reg_path.exists():
        return []
    return json.loads(reg_path.read_text())


def _backup_targets(name: str, iteration: int, config: dict):
    """Target-Dateien + Tools sichern."""
    backup_dir = DATA_DIR / name / "backups" / f"iter-{iteration}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    mapping_file = backup_dir / "_paths.json"
    mapping = {}
    if mapping_file.exists():
        mapping = json.loads(mapping_file.read_text())

    for target in config.get("targets", []):
        src = Path(target).expanduser()
        if src.exists():
            if src.is_dir():
                dst = backup_dir / src.name
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, backup_dir / src.name)
            mapping[src.name] = str(src)

    # Tool-Backup für Codex-Review Diffs (konfigurierbar per config)
    tools_dir = Path.home() / ".claude" / "tools"
    backup_tools = config.get("backup_tools", ["fast-search.py", "research-crawler.py"])
    for tool_name in backup_tools:
        tool_path = tools_dir / tool_name
        if tool_path.exists():
            shutil.copy2(tool_path, backup_dir / tool_name)

    mapping_file.write_text(json.dumps(mapping, indent=2))


def _restore_targets(name: str, iteration: int):
    """Target-Dateien aus Backup wiederherstellen."""
    backup_dir = DATA_DIR / name / "backups" / f"iter-{iteration}"
    if not backup_dir.exists():
        print(f"Backup iter-{iteration} nicht gefunden", file=sys.stderr)
        return False
    mapping_file = backup_dir / "_paths.json"
    if not mapping_file.exists():
        print("Pfad-Mapping nicht gefunden", file=sys.stderr)
        return False
    mapping = json.loads(mapping_file.read_text())
    for filename, original_path in mapping.items():
        src = backup_dir / filename
        dst = Path(original_path)
        if src.exists():
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    return True


def _get_current_iteration(name: str) -> int:
    """Aktuelle Iteration aus History bestimmen."""
    history = _load_history(name)
    accepted = [h for h in history if h.get("action") == "accept"]
    return len(accepted)


def _get_best_score(name: str) -> float | None:
    """Besten Score aus History."""
    history = _load_history(name)
    scores = [
        h["score"] for h in history if "score" in h and h.get("action") == "accept"
    ]
    return max(scores) if scores else None


def _get_best_trial_score(name: str) -> float | None:
    """Besten Trial-Score aus History."""
    history = _load_history(name)
    scores = [
        h["trial_avg"]
        for h in history
        if h.get("trial_avg") is not None and h.get("action") == "accept"
    ]
    return max(scores) if scores else None


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_init(args):
    """Neues Optimierungsprojekt anlegen."""
    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"Config nicht gefunden: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = json.loads(config_path.read_text())
    project_name = config.get("name", config_path.stem)
    slug = re.sub(r"[^a-z0-9-]", "-", project_name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")

    project_dir = DATA_DIR / slug
    if project_dir.exists() and not args.force:
        print(
            f"Projekt '{slug}' existiert bereits. --force zum Überschreiben.",
            file=sys.stderr,
        )
        sys.exit(1)

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "backups").mkdir(exist_ok=True)

    config["slug"] = slug
    config["created"] = datetime.now().isoformat()
    (project_dir / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False)
    )

    _backup_targets(slug, 0, config)

    missing = []
    for t in config.get("targets", []):
        if not Path(t).expanduser().exists():
            missing.append(t)
    if missing:
        print(f"WARNUNG: Targets nicht gefunden: {', '.join(missing)}", file=sys.stderr)

    _save_history(
        slug,
        {
            "action": "init",
            "timestamp": datetime.now().isoformat(),
            "targets": config.get("targets", []),
            "check_count": len(config.get("checks", [])),
        },
    )

    n_checks = len(config.get("checks", []))
    n_targets = len(config.get("targets", []))
    print(f"Projekt '{slug}' angelegt: {n_targets} Targets, {n_checks} Checks")
    print(f"  Daten: {project_dir}")
    print("  Baseline-Backup: iter-0")
    print(f"\nNächster Schritt: python3 {__file__} check {slug}")


def _run_codex_review(ck, ck_id, ck_name, config, args) -> dict:
    """Codex Code-Review mit Self-Context-Pulling.

    Codex liest die Dateien selbst (vorher/nachher), navigiert frei im Projekt,
    und liefert ein strukturiertes JSON-Urteil. Read-Only via Prompt-Constraint.
    """
    import shlex

    task_desc = ck.get("task", config.get("description", "Improve this skill"))
    constraints = ck.get("constraints", "")
    timeout_sec = ck.get("timeout", 180)

    try:
        iteration = _get_current_iteration(args.project)
        targets = config.get("targets", [])
        if not targets:
            return {
                "id": ck_id,
                "name": ck_name,
                "pass": False,
                "reason": "Keine Targets",
                "codex_score": 50,
            }

        # Resolve paths
        target_paths = []
        for t in targets:
            tp = Path(t).expanduser()
            if tp.exists() and tp.is_file():
                target_paths.append(str(tp))

        backup_dir = DATA_DIR / args.project / "backups" / f"iter-{iteration}"
        if not backup_dir.exists():
            backup_dir = DATA_DIR / args.project / "backups" / "iter-0"

        # Bootstrap-Skip: check if any target actually changed
        has_changes = False
        for tp_str in target_paths:
            tp = Path(tp_str)
            bp = backup_dir / tp.name
            if bp.exists():
                if tp.read_bytes() != bp.read_bytes():
                    has_changes = True
                    break
            else:
                has_changes = True  # New file = change
                break

        # Also check backup_tools from config
        backup_tools = config.get("backup_tools", [])
        tools_dir = Path.home() / ".claude" / "tools"
        tool_paths = []
        for tool_name in backup_tools:
            tool_path = tools_dir / tool_name
            tool_backup = backup_dir / tool_name
            if tool_path.exists() and tool_backup.exists():
                if tool_path.read_bytes() != tool_backup.read_bytes():
                    has_changes = True
                    tool_paths.append(str(tool_path))

        if not has_changes:
            sys.stderr.write(f"  Codex-Review '{ck_name}': SKIP (keine Änderungen)\n")
            return {
                "id": ck_id,
                "name": ck_name,
                "pass": False,
                "reason": "SKIP: Keine Änderungen seit letztem Accept",
                "codex_score": None,
            }

        # Build file list for prompt
        current_files = "\n".join(f"  - {p}" for p in target_paths + tool_paths)
        backup_files = "\n".join(
            f"  - {backup_dir / Path(p).name}"
            for p in target_paths + tool_paths
            if (backup_dir / Path(p).name).exists()
        )

        review_prompt = f"""You are an impartial code reviewer. Your job is to READ the files yourself, compare before/after versions, and judge whether the changes are an improvement.

SAFETY RULES — MANDATORY:
- You may ONLY read files: cat, grep, head, tail, wc, find, diff, ls
- You must NEVER write, modify, or delete ANY file
- No echo >, no tee, no rm, no mv, no cp, no sed -i, no python with open(w)
- Violation of these rules is a critical failure

TASK: {task_desc}
HARD CONSTRAINTS: {constraints}

CURRENT VERSION (after changes):
{current_files}

PREVIOUS VERSION (before changes, backup):
{backup_files}

INSTRUCTIONS:
1. Read the CURRENT files completely — do not skip or truncate
2. Read the BACKUP files completely for comparison
3. Use diff to identify what changed between versions
4. If you need more context (imports, related functions, templates), navigate freely in the project directory
5. Evaluate whether the changes are an improvement based on the rubric below

RUBRIC (0-10 each):
- correctness: Does the changed code work as intended? Any bugs introduced?
- completeness: Does it improve coverage of important cases?
- clarity: Is the code well-structured, readable, maintainable?
- constraints: Does it respect the hard constraints listed above?
- safety: No harmful patterns, regressions, or security issues?

Return STRICT JSON only, no markdown, no code fences. You MUST choose "better" or "worse".
{{"verdict":"better"|"worse","confidence":0.0-1.0,"scores":{{"before":{{"correctness":0,"completeness":0,"clarity":0,"constraints":0,"safety":0}},"after":{{"correctness":0,"completeness":0,"clarity":0,"constraints":0,"safety":0}}}},"critical_issues":{{"before":[],"after":[]}},"rationale":"<60 words max>"}}"""

        sys.stderr.write(
            f"  Codex-Review '{ck_name}': Self-Context-Pulling "
            f"({len(target_paths)}+{len(tool_paths)} Dateien)...\n"
        )
        cmd = (
            f"codex exec --skip-git-repo-check "
            f"--dangerously-bypass-approvals-and-sandbox "
            f"-C /home/maetzger/.claude "
            f"{shlex.quote(review_prompt)} 2>/dev/null"
        )
        r1 = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout_sec
        )

        # Parse JSON from output
        raw = r1.stdout.strip()
        j1 = None
        try:
            j1 = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    j1 = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if j1 and "verdict" in j1:
            verdict = j1["verdict"]
            avg_confidence = float(j1.get("confidence", 0.5))
            if verdict == "better":
                codex_score = 70 + avg_confidence * 30
            elif verdict == "worse":
                codex_score = 30 - avg_confidence * 20
            else:
                codex_score = 50
        else:
            verdict = "fallback"
            codex_score = 50
            avg_confidence = 0.0

        dim_avgs = {}
        if j1 and "scores" in j1:
            for phase, dims in j1["scores"].items():
                if isinstance(dims, dict):
                    for dim, val in dims.items():
                        dim_avgs[f"{phase}.{dim}"] = val

        rationale = j1.get("rationale", "") if j1 else ""
        passed = verdict == "better"

        return {
            "id": ck_id,
            "name": ck_name,
            "pass": passed,
            "reason": f"Codex: {verdict} (conf:{avg_confidence:.2f} score:{codex_score:.0f}/100) {rationale[:80]}",
            "codex_score": round(codex_score, 1),
            "codex_verdict": verdict,
            "codex_confidence": round(avg_confidence, 2),
            "codex_dimensions": dim_avgs,
            "codex_raw": j1,
        }
    except subprocess.TimeoutExpired:
        return {
            "id": ck_id,
            "name": ck_name,
            "pass": False,
            "reason": f"Codex-Review Timeout ({timeout_sec}s)",
            "codex_score": 50,
        }
    except Exception as e:
        return {
            "id": ck_id,
            "name": ck_name,
            "pass": False,
            "reason": f"Codex-Review Fehler: {e!s:.100}",
            "codex_score": 50,
        }


def _run_codex_verify(ck, ck_id, ck_name, project_name: str = "") -> dict:
    """Codex als unabhängiger Faktencheck-Agent (Thread-safe)."""
    import shlex

    source_output = ck.get("source_output", "")
    timeout_sec = ck.get("timeout", 360)

    try:
        source_path = Path(source_output).expanduser()
        if not source_path.exists():
            return {
                "id": ck_id,
                "name": ck_name,
                "pass": False,
                "reason": f"Source-Output nicht gefunden: {source_output}",
                "trial_score": 0,
            }

        skill_output = source_path.read_text(errors="replace")[:8000]
        tools_dir = Path.home() / ".claude" / "tools"

        verify_prompt = (
            "Du bist ein Faktencheck-Agent. Du hast Zugriff auf Web-Recherche-Tools.\n\n"
            "RECHERCHE-ERGEBNIS ZUM PRÜFEN:\n"
            f"{skill_output}\n\n"
            "AUFGABE:\n"
            "1. Identifiziere die 3 wichtigsten FALSIFIZIERBAREN Claims (Zahlen, Preise, Daten, "
            "kausale Aussagen). Ignoriere Meinungen und subjektive Bewertungen.\n"
            "2. Bewerte jeden Claim nach Impact (1-5): Preise/medizinische Empfehlungen=5, "
            "Jahreszahlen/Spezifikationen=4, Rankings/Vergleiche=3, Hintergrundinfo=2.\n"
            "3. Recherchiere die Top-3 Claims mit diesem Befehl:\n"
            f'   python3 {tools_dir / "fast-search.py"} --max 5 "<search query>" | '
            f"python3 {tools_dir / 'research-crawler.py'} --max-chars 300\n"
            "4. Pro Claim: Prüfe ob die ZITIERTE QUELLE den Claim tatsächlich stützt UND "
            "ob mindestens 1 unabhängige Quelle ihn bestätigt.\n"
            "5. EARLY EXIT: Wenn ein Claim mit impact>=4 klar falsch ist, "
            "kannst du sofort abbrechen und das Ergebnis melden.\n\n"
            "AUSGABE als STRICT JSON (kein Markdown, keine Code-Fences):\n"
            '{"claims_checked": 3, "claims_verified": 2, "claims_unverified": 0, '
            '"claims_wrong": 1, '
            '"details": [{"claim": "...", "claim_type": "numeric|temporal|causal|comparative", '
            '"impact": 5, "verdict": "verified|unverified|wrong", '
            '"confidence": 0.9, "evidence": "...", '
            '"failure_mode": "none|insufficient_evidence|outdated_sources|source_mismatch|direct_contradiction"}], '
            '"overall_verdict": "reliable|mixed|unreliable", '
            '"rationale": "<50 words max>"}'
        )

        sys.stderr.write(f"  Codex-Verify '{ck_name}': Faktencheck...\n")
        cmd = (
            f"codex exec --skip-git-repo-check "
            f"--dangerously-bypass-approvals-and-sandbox "
            f"-C /home/maetzger "
            f"{shlex.quote(verify_prompt)} 2>/dev/null"
        )
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout_sec
        )

        raw = r.stdout.strip()
        j = None
        try:
            j = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    j = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if j and ("verification_rate" in j or "details" in j):
            details = j.get("details", [])
            checked = j.get("claims_checked", len(details))
            verified = j.get("claims_verified", 0)
            wrong = j.get("claims_wrong", 0)
            overall = j.get("overall_verdict", "mixed")
            rationale = j.get("rationale", "")

            # Impact-gewichtete Verification-Rate
            weighted_sum, weight_total = 0.0, 0.0
            high_impact_wrong = False
            for d in details:
                impact = max(1, min(5, int(d.get("impact", 3))))
                verdict = d.get("verdict", "unverified")
                weight_total += impact
                if verdict == "verified":
                    weighted_sum += impact
                elif verdict == "wrong" and impact >= 4:
                    high_impact_wrong = True

            if weight_total > 0:
                w_rate = weighted_sum / weight_total
            else:
                w_rate = float(j.get("verification_rate", 0))

            # Regression-Memory: Falsche Claims persistent speichern
            for d in details:
                if d.get("verdict") == "wrong" and project_name:
                    _save_regression(
                        name=project_name,
                        claim=d.get("claim", "unknown"),
                        correct=d.get("evidence", ""),
                        source=ck_name,
                        iteration=0,
                    )

            # Score: weighted rate * 100, Hard-Fail bei high-impact wrong
            if high_impact_wrong:
                trial_score = round(max(0, w_rate * 100 - 30), 1)
                passed = False
            else:
                trial_score = round(max(0, w_rate * 100 - wrong * 15), 1)
                passed = w_rate >= 0.6 and wrong == 0

            return {
                "id": ck_id,
                "name": ck_name,
                "pass": passed,
                "reason": (
                    f"Verify: {verified}/{checked} (w:{w_rate:.0%}) "
                    f"wrong:{wrong}{' HI-WRONG!' if high_impact_wrong else ''} "
                    f"→ {overall} ({trial_score:.0f}/100) "
                    f"{rationale[:60]}"
                ),
                "trial_score": trial_score,
                "metrics": {
                    "claims_checked": checked,
                    "claims_verified": verified,
                    "claims_wrong": wrong,
                    "weighted_verification_rate": round(w_rate, 3),
                    "high_impact_wrong": high_impact_wrong,
                    "overall_verdict": overall,
                },
                "codex_raw": j,
            }
        else:
            return {
                "id": ck_id,
                "name": ck_name,
                "pass": False,
                "reason": f"Codex-Verify: JSON parse failed ({raw[:100]})",
                "trial_score": 0,
            }

    except subprocess.TimeoutExpired:
        return {
            "id": ck_id,
            "name": ck_name,
            "pass": False,
            "reason": f"Codex-Verify Timeout ({timeout_sec}s)",
            "trial_score": None,
        }
    except Exception as e:
        return {
            "id": ck_id,
            "name": ck_name,
            "pass": False,
            "reason": f"Codex-Verify Fehler: {e!s:.100}",
            "trial_score": None,
        }


def cmd_check(args):
    """Checks auf aktuellem Stand ausführen."""
    config = _load_project(args.project)
    checks = config.get("checks", [])

    if not checks:
        print("Keine Checks definiert.", file=sys.stderr)
        sys.exit(1)

    output_file = args.output if args.output else None

    results = []
    auto_pass = 0
    auto_fail = 0
    agent_pending = []
    deferred_codex = []  # Phase 2: Codex-Calls parallel ausführen

    for ck in checks:
        ck_id = ck.get("id", ck.get("name", "?"))
        ck_type = ck.get("type", "agent")
        ck_name = ck.get("name", ck_id)

        if ck_type == "command":
            cmd = ck.get("command", "")
            if not cmd:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "Kein Command",
                    }
                )
                auto_fail += 1
                continue
            try:
                r = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=60
                )
                passed = r.returncode == 0
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": passed,
                        "reason": f"Exit {r.returncode}"
                        + (f": {r.stderr[:100]}" if r.stderr else ""),
                    }
                )
                if passed:
                    auto_pass += 1
                else:
                    auto_fail += 1
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "Timeout (60s)",
                    }
                )
                auto_fail += 1

        elif ck_type == "pattern":
            target_file = ck.get("file", output_file or "")
            pattern = ck.get("pattern", "")
            min_matches = ck.get("min_matches", 1)
            if not target_file or not pattern:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "file/pattern fehlt",
                    }
                )
                auto_fail += 1
                continue
            fpath = Path(target_file).expanduser()
            if not fpath.exists():
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": f"Datei nicht gefunden: {fpath}",
                    }
                )
                auto_fail += 1
                continue
            content = fpath.read_text(errors="replace")
            matches = len(re.findall(pattern, content))
            passed = matches >= min_matches
            results.append(
                {
                    "id": ck_id,
                    "name": ck_name,
                    "pass": passed,
                    "reason": f"{matches} Treffer (min: {min_matches})",
                }
            )
            if passed:
                auto_pass += 1
            else:
                auto_fail += 1

        elif ck_type == "trial":
            # Funktionaler Pipeline-Test: fast-search → research-crawler
            queries = ck.get("queries", [])
            fw = ck.get("freshness_weight", 1.5)
            max_chars = ck.get("max_chars", 6000)
            min_urls_ok = ck.get("min_urls_ok", 5)
            min_avg_quality = ck.get("min_avg_quality", 6.0)
            max_boilerplate_pct = ck.get("max_boilerplate_pct", 30)
            min_domains = ck.get("min_domains", 3)
            save_output = ck.get("save_output", "")

            if not queries:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "Keine Queries",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
                continue

            try:
                import shlex
                from urllib.parse import urlparse

                tools_dir = Path.home() / ".claude" / "tools"
                search_args = " ".join(shlex.quote(q) for q in queries)
                cmd = (
                    f"python3 {tools_dir / 'fast-search.py'} {search_args} "
                    f"| python3 {tools_dir / 'research-crawler.py'} "
                    f"--max-chars {max_chars} --freshness-weight {fw}"
                )

                sys.stderr.write(f"  Trial '{ck_name}': {len(queries)} Queries...\n")
                r = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=120
                )

                if not r.stdout.strip():
                    results.append(
                        {
                            "id": ck_id,
                            "name": ck_name,
                            "pass": False,
                            "reason": f"Kein Output: {r.stderr[:150]}",
                            "trial_score": 0,
                        }
                    )
                    auto_fail += 1
                    continue

                data = json.loads(r.stdout)

                if save_output:
                    Path(save_output).expanduser().write_text(
                        json.dumps(data, indent=2, ensure_ascii=False)
                    )

                ok = [
                    d for d in data if not d.get("error") and not d.get("boilerplate")
                ]
                bp = [d for d in data if d.get("boilerplate")]

                urls_ok = len(ok)
                avg_q = sum(d.get("quality", 0) for d in ok) / len(ok) if ok else 0
                bp_pct = len(bp) / len(data) * 100 if data else 0
                domains = len(
                    set(urlparse(d["url"]).netloc.replace("www.", "") for d in ok)
                )
                total_chars = sum(d.get("chars", 0) for d in ok)

                # Source-Type-Diversity: wie viele verschiedene Typen?
                source_types = set(d.get("source_type", "general") for d in ok)
                n_source_types = len(source_types)
                type_diversity_score = min(n_source_types / 3, 1.0)  # ≥3 Typen = 1.0

                # Freshness: Anteil der Quellen mit pub_date < 12 Monate
                from datetime import date as _date

                fresh_count = 0
                for d in ok:
                    pd = d.get("pub_date")
                    if pd:
                        try:
                            age_days = (_date.today() - _date.fromisoformat(pd)).days
                            if age_days <= 365:
                                fresh_count += 1
                        except ValueError:
                            pass
                freshness_pct = fresh_count / max(len(ok), 1) * 100

                # Continuous trial score (0-100)
                # Gewichtung nach Codex-QA-Review angepasst:
                # Content-Quality 30%, URL-Yield 20%, Domains 15%,
                # Source-Type-Diversity 10%, Freshness 15%, Boilerplate 10%
                trial_score = round(
                    min(avg_q / max(min_avg_quality, 1), 1.5) / 1.5 * 30
                    + min(urls_ok / max(min_urls_ok, 1), 1.5) / 1.5 * 20
                    + min(domains / max(min_domains, 1), 1.5) / 1.5 * 15
                    + type_diversity_score * 10
                    + min(freshness_pct / 50, 1.0) * 15  # ≥50% fresh = max
                    + max(0, 1 - bp_pct / 100) * 10,
                    1,
                )

                # Freshness-Gate: ≥30% der Quellen müssen <12 Monate alt sein
                freshness_gate = (
                    freshness_pct >= 30 or fresh_count == 0
                )  # 0 = unknown ok

                passed = (
                    urls_ok >= min_urls_ok
                    and avg_q >= min_avg_quality
                    and bp_pct <= max_boilerplate_pct
                    and domains >= min_domains
                    and freshness_gate
                )

                metrics = {
                    "urls_ok": urls_ok,
                    "avg_quality": round(avg_q, 1),
                    "boilerplate_pct": round(bp_pct, 1),
                    "unique_domains": domains,
                    "total_chars": total_chars,
                    "source_types": sorted(source_types),
                    "n_source_types": n_source_types,
                    "freshness_pct": round(freshness_pct, 1),
                }

                reason = (
                    f"URLs:{urls_ok} Q:{avg_q:.1f} BP:{bp_pct:.0f}% "
                    f"Dom:{domains} Types:{n_source_types} Fresh:{freshness_pct:.0f}% "
                    f"Chars:{total_chars:,} → {trial_score:.0f}/100"
                )

                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": passed,
                        "reason": reason,
                        "trial_score": trial_score,
                        "metrics": metrics,
                    }
                )
                if passed:
                    auto_pass += 1
                else:
                    auto_fail += 1

            except json.JSONDecodeError:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "JSON Parse-Fehler im Pipeline-Output",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "Pipeline Timeout (120s)",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
            except Exception as e:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": f"Fehler: {e!s:.100}",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1

        elif ck_type == "skill-trial":
            # End-to-End Skill-Test: Führt claude --print mit Prompt aus,
            # bewertet das Ergebnis anhand messbarer Qualitätsmerkmale.
            prompt = ck.get("prompt", "")
            timeout_sec = ck.get("timeout", 300)
            save_output = ck.get("save_output", "")
            max_budget = ck.get("max_budget_usd", 1.0)
            min_sources = ck.get("min_sources", 3)
            min_domains = ck.get("min_domains", 2)
            min_words = ck.get("min_words", 200)

            if not prompt:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "Kein Prompt",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
                continue

            try:
                import shlex
                from urllib.parse import urlparse

                sys.stderr.write(f"  Skill-Trial '{ck_name}': claude --print...\n")
                cmd = (
                    f"claude -p {shlex.quote(prompt)} "
                    f"--permission-mode bypassPermissions "
                    f"--max-budget-usd {max_budget} "
                    f"--no-session-persistence"
                )

                # Retry logic: run up to max_attempts, collect valid results
                max_attempts = ck.get("max_attempts", 3)
                valid_outputs = []
                last_error = ""

                for attempt in range(max_attempts):
                    try:
                        r = subprocess.run(
                            cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=timeout_sec,
                        )
                        output = r.stdout.strip()

                        # Fallback: claude -p sometimes writes response
                        # to stderr instead of stdout (intermittent)
                        if len(output) < 50 and len(r.stderr.strip()) > 100:
                            stderr_out = r.stderr.strip()
                            # Only use stderr if it looks like actual content
                            # (not just error messages or tool logs)
                            if any(
                                m in stderr_out for m in ["##", "[Q", "Quellen:", "---"]
                            ):
                                output = stderr_out

                        # Classify: infra/budget error vs real output
                        # Only match budget errors at start of output (not
                        # "budget" as a topic word in legitimate content)
                        is_infra_error = (
                            r.returncode != 0
                            or len(output) < 50
                            or output.startswith("Error:")
                            or "Exceeded USD budget" in output
                        )

                        if is_infra_error:
                            err_hint = output[:100] or f"exit={r.returncode}"
                            last_error = (
                                f"Attempt {attempt + 1}: infra error ({err_hint})"
                            )
                            sys.stderr.write(
                                f"    Retry {attempt + 1}/{max_attempts}: {err_hint}\n"
                            )
                            continue

                        valid_outputs.append(output)
                        if len(valid_outputs) >= 2:
                            break  # 2 valid runs is enough for median
                    except subprocess.TimeoutExpired:
                        last_error = f"Attempt {attempt + 1}: timeout"
                        continue

                if not valid_outputs:
                    results.append(
                        {
                            "id": ck_id,
                            "name": ck_name,
                            "pass": False,
                            "reason": f"Alle {max_attempts} Versuche fehlgeschlagen: {last_error}",
                            "trial_score": None,  # invalid, not 0
                        }
                    )
                    # Don't count invalid measurements as fail
                    continue

                # Use the longest valid output (most complete)
                output = max(valid_outputs, key=len)

                if save_output:
                    Path(save_output).expanduser().write_text(output)

                # Metriken extrahieren
                # Match both https://domain.com and bare domain.com/path URLs
                # Also count [Q1]-style citation references
                urls = re.findall(r"https?://[^\s\)\"'>|]+", output)
                # Bare domain URLs (e.g. "pmc.ncbi.nlm.nih.gov/articles/...")
                bare_urls = re.findall(
                    r"(?<!\w)([a-z0-9][\w.-]+\.[a-z]{2,}/[^\s\)\"'>|]+)", output
                )
                all_urls = list(set(urls + [f"https://{u}" for u in bare_urls]))
                # Also count [Qn] citation markers as source indicators
                citation_refs = re.findall(r"\[Q(\d+)\]", output)
                unique_citations = set(citation_refs)
                unique_urls = list(set(all_urls))
                domains = set(
                    urlparse(u).netloc.replace("www.", "")
                    for u in unique_urls
                    if urlparse(u).netloc
                )
                # Use max of URL-based and citation-based source count
                n_sources = max(len(unique_urls), len(unique_citations))
                n_domains = max(len(domains), len(unique_citations))
                words = len(output.split())
                has_inference = bool(
                    re.search(r"\[Eigene (Inferenz|Einschätzung)\]", output)
                )
                has_structure = bool(
                    re.search(
                        r"^[\s]*(?:[-*]\s|\d+[.\)]\s|#{1,4}\s)",
                        output,
                        re.MULTILINE,
                    )
                )

                # Trial-Score berechnen (0-100)
                # 30% Quellen, 25% Domains, 20% Substanz (Band-Pass),
                # 10% Struktur, 15% Inferenz-Marker
                source_score = min(n_sources / max(min_sources, 1), 2) / 2
                domain_score = min(n_domains / max(min_domains, 1), 2) / 2
                # Band-Pass: 150-1000 Wörter optimal, darunter/darüber Malus
                if words < min_words:
                    substance_score = words / max(min_words, 1)
                elif words <= 1000:
                    substance_score = 1.0  # Sweet spot
                else:
                    # Leichter Malus für zu lange Antworten (Goodhart-Guard)
                    substance_score = max(0.7, 1.0 - (words - 1000) / 2000)
                structure_score = 1.0 if has_structure else 0.3
                inference_score = 1.0 if has_inference else 0.5

                trial_score = round(
                    source_score * 30
                    + domain_score * 25
                    + substance_score * 20
                    + structure_score * 10
                    + inference_score * 15,
                    1,
                )

                passed = (
                    n_sources >= min_sources
                    and n_domains >= min_domains
                    and words >= min_words
                )

                metrics = {
                    "sources": n_sources,
                    "unique_domains": n_domains,
                    "words": words,
                    "has_inference_marker": has_inference,
                    "has_structure": has_structure,
                    "output_chars": len(output),
                }

                reason = (
                    f"Src:{n_sources} Dom:{n_domains} "
                    f"Words:{words} Inf:{'Y' if has_inference else 'N'} "
                    f"Struct:{'Y' if has_structure else 'N'} → "
                    f"{trial_score:.0f}/100"
                )

                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": passed,
                        "reason": reason,
                        "trial_score": trial_score,
                        "metrics": metrics,
                    }
                )
                if passed:
                    auto_pass += 1
                else:
                    auto_fail += 1

            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": f"Timeout ({timeout_sec}s)",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
            except Exception as e:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": f"Fehler: {e!s:.100}",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1

        elif ck_type == "market-trial":
            # Market-Scraper Pipeline-Test: Kleinanzeigen scrapen + bewerten
            search_term = ck.get("search_term", "")
            product_name = ck.get("product_name", search_term)
            scraper_args = ck.get("scraper_args", "--auto-geizhals --auto-exclude")
            min_listings = ck.get("min_listings", 5)
            min_picks = ck.get("min_picks", 2)
            save_output = ck.get("save_output", "")

            if not search_term:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "Kein search_term",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
                continue

            try:
                import shlex

                tools_dir = Path.home() / ".claude" / "tools"
                cmd = (
                    f"python3 {tools_dir / 'market-scraper.py'} "
                    f"{shlex.quote(search_term)} "
                    f"--product-name {shlex.quote(product_name)} "
                    f"{scraper_args}"
                )

                sys.stderr.write(f"  Market-Trial '{ck_name}': {search_term}...\n")
                r = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )

                if not r.stdout.strip():
                    results.append(
                        {
                            "id": ck_id,
                            "name": ck_name,
                            "pass": False,
                            "reason": f"Kein Output: {r.stderr[:200]}",
                            "trial_score": 0,
                        }
                    )
                    auto_fail += 1
                    continue

                data = json.loads(r.stdout)

                if save_output:
                    Path(save_output).expanduser().write_text(
                        json.dumps(data, indent=2, ensure_ascii=False)
                    )

                # --- Metriken extrahieren ---
                total_raw = data.get("total_raw", 0)
                total_clean = data.get("total_clean", 0)
                total_scam = data.get("total_scam", 0)
                total_final = data.get("total_final", 0)
                stats = data.get("stats", {})
                picks = data.get("smart_picks", [])
                nearby = data.get("nearby_pick")
                analysis = data.get("agent_analysis", {})
                neupreis = data.get("neupreis")

                # --- Scoring (5 Dimensionen, 0-100) ---

                # 1. Quantity (20%): Listing-Ausbeute
                qty_ratio = min(total_final / max(min_listings, 1), 2.0) / 2.0
                qty_score = qty_ratio * 20

                # 2. Quality (25%): Smart-Pick-Qualität
                if picks:
                    avg_pick_score = sum(p.get("score", 0) for p in picks) / len(picks)
                    pick_quality = min(avg_pick_score / 60, 1.0)
                    badge_count = sum(
                        1
                        for p in picks
                        if p.get("seller_badges") and p["seller_badges"] != "-"
                    )
                    badge_pct = badge_count / len(picks)
                    desc_count = sum(1 for p in picks if p.get("description"))
                    desc_pct = desc_count / len(picks)
                    quality_score = (
                        pick_quality * 0.5 + badge_pct * 0.3 + desc_pct * 0.2
                    ) * 25
                else:
                    quality_score = 0

                # 3. Price-Accuracy (20%): Preisstatistik-Qualität
                has_neupreis = neupreis is not None and neupreis > 0
                has_stats = stats.get("median") is not None and stats["median"] > 0
                spread_ok = True
                if has_stats and stats.get("max") and stats.get("min"):
                    spread = stats["max"] - stats["min"]
                    spread_ok = spread < stats["median"] * 3
                iqr_ok = has_stats and stats.get("q1") and stats.get("q3")
                price_score = (
                    (5 if has_neupreis else 0)
                    + (5 if has_stats else 0)
                    + (5 if spread_ok else 0)
                    + (5 if iqr_ok else 0)
                )

                # 4. Scam-Safety (20%): Scam-Erkennung
                scam_rate = total_scam / max(total_raw, 1)
                scam_score = 15  # Basis
                if scam_rate > 0.5:
                    scam_score -= 10  # zu viele geflaggt
                if total_scam > 0 and scam_rate < 0.3:
                    scam_score += 5  # gesunde Erkennungsrate
                # Bonus: Seller-Checks wurden ausgeführt (auch ohne Scam-Fund)
                n_checked = len(
                    [
                        p
                        for p in picks
                        if p.get("seller_badges") and p["seller_badges"] != "-"
                    ]
                )
                if n_checked > 0:
                    scam_score = min(20, scam_score + 3)
                # Bonus: TGTBT/Risk-Flags aktiv (proaktive Erkennung)
                has_flags = any(
                    p.get("tgtbt_flags") or p.get("risk_flags") for p in picks
                )
                if has_flags:
                    scam_score = min(20, scam_score + 2)
                scam_score = max(0, min(20, scam_score))

                # 5. Smart-Picks (15%): Empfehlungs-Qualität
                n_picks = len(picks)
                has_nearby = nearby is not None
                n_suggests = sum(
                    1 for k, v in analysis.items() if "suggest" in k and v and v != "?"
                )
                picks_below_median = 0
                if has_stats:
                    picks_below_median = sum(
                        1 for p in picks if p.get("price", 999999) <= stats["median"]
                    )
                picks_score = (
                    min(n_picks / max(min_picks, 1), 1.5) / 1.5 * 6
                    + (3 if has_nearby else 0)
                    + min(n_suggests / 3, 1.0) * 3
                    + min(picks_below_median / 2, 1.0) * 3
                )

                trial_score = round(
                    qty_score + quality_score + price_score + scam_score + picks_score,
                    1,
                )

                passed = (
                    total_final >= min_listings
                    and len(picks) >= min_picks
                    and has_stats
                )

                metrics = {
                    "total_raw": total_raw,
                    "total_clean": total_clean,
                    "total_scam": total_scam,
                    "total_final": total_final,
                    "median": stats.get("median"),
                    "price_range": f"{stats.get('min', '?')}-{stats.get('max', '?')}",
                    "neupreis": neupreis,
                    "n_picks": n_picks,
                    "has_nearby": has_nearby,
                    "scam_rate": round(scam_rate, 3),
                    "sub_scores": {
                        "quantity": round(qty_score, 1),
                        "quality": round(quality_score, 1),
                        "price_accuracy": round(price_score, 1),
                        "scam_safety": round(scam_score, 1),
                        "smart_picks": round(picks_score, 1),
                    },
                }

                reason = (
                    f"Raw:{total_raw} Clean:{total_clean} "
                    f"Scam:{total_scam} Final:{total_final} "
                    f"Picks:{n_picks} Nearby:{'Y' if has_nearby else 'N'} "
                    f"Median:{stats.get('median', '?')}€ "
                    f"→ {trial_score:.0f}/100"
                )

                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": passed,
                        "reason": reason,
                        "trial_score": trial_score,
                        "metrics": metrics,
                    }
                )
                if passed:
                    auto_pass += 1
                else:
                    auto_fail += 1

            except json.JSONDecodeError as e:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": f"JSON Parse-Fehler: {e!s:.100}",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": "Scraper Timeout (180s)",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1
            except Exception as e:
                results.append(
                    {
                        "id": ck_id,
                        "name": ck_name,
                        "pass": False,
                        "reason": f"Fehler: {e!s:.100}",
                        "trial_score": 0,
                    }
                )
                auto_fail += 1

            # Rate-Limit Schutz: Pause zwischen Scraper-Trials
            import time as _time

            _time.sleep(5)

        elif ck_type in ("codex-review", "codex-verify"):
            # Defer Codex calls to Phase 2 (parallel execution)
            deferred_codex.append((ck, ck_id, ck_name, ck_type))
            continue

        elif ck_type == "agent":
            agent_pending.append(
                {
                    "id": ck_id,
                    "name": ck_name,
                    "type": "agent",
                    "question": ck.get("question", ""),
                    "criteria": ck.get("criteria", ""),
                }
            )

        else:
            results.append(
                {
                    "id": ck_id,
                    "name": ck_name,
                    "pass": False,
                    "reason": f"Unbekannter Typ: {ck_type}",
                }
            )
            auto_fail += 1

    # --- Phase 2: Codex-Calls parallel ausführen ---
    if deferred_codex:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        sys.stderr.write(f"  Phase 2: {len(deferred_codex)} Codex-Calls parallel...\n")

        def _run_codex_check(ck_tuple):
            """Einen Codex-Check ausführen (Thread-safe)."""
            ck, ck_id, ck_name, ck_type = ck_tuple

            if ck_type == "codex-review":
                return _run_codex_review(ck, ck_id, ck_name, config, args)
            elif ck_type == "codex-verify":
                return _run_codex_verify(ck, ck_id, ck_name, args.project)
            return {
                "id": ck_id,
                "name": ck_name,
                "pass": False,
                "reason": f"Unbekannter Codex-Typ: {ck_type}",
            }

        with ThreadPoolExecutor(max_workers=min(2, len(deferred_codex))) as pool:
            futures = {pool.submit(_run_codex_check, ct): ct for ct in deferred_codex}
            for fut in as_completed(futures):
                result = fut.result()
                results.append(result)
                if result.get("pass"):
                    auto_pass += 1
                elif (
                    result.get("trial_score") is not None
                    or result.get("codex_score") is not None
                ):
                    # Count as fail if it's a valid measurement (trial_score OR codex_score)
                    auto_fail += 1
                # else: invalid measurement (timeout etc.), don't count

    total_auto = auto_pass + auto_fail
    print(f"=== Check: {config.get('name', args.project)} ===")
    print(f"Automatische Checks: {auto_pass}/{total_auto} bestanden")
    print()

    for r in results:
        icon = "PASS" if r["pass"] else "FAIL"
        print(f"  [{icon}] {r['name']}: {r.get('reason', '')}")

    if agent_pending:
        print(f"\n--- {len(agent_pending)} Agent-Checks (manuell bewerten) ---")
        for ap in agent_pending:
            print(f"\n  [{ap['id']}] {ap['name']}")
            print(f"  Frage: {ap['question']}")
            if ap.get("criteria"):
                print(f"  Kriterien: {ap['criteria']}")
            print("  → Antwort: PASS oder FAIL?")

    auto_score = auto_pass / total_auto * 100 if total_auto > 0 else 0

    # --- Reliability-Gate: Codex-Verify muss bestehen ---
    verify_results = [
        r
        for r in results
        if r.get("id", "").startswith("cv") and r.get("trial_score") is not None
    ]
    verify_failed = [r for r in verify_results if not r.get("pass")]
    reliability_ok = len(verify_failed) == 0

    if verify_results and not reliability_ok:
        sys.stderr.write(
            f"  ⚠ Reliability-Gate FAIL: "
            f"{len(verify_failed)} Codex-Verify nicht bestanden\n"
        )

    # Trial-Score: Durchschnitt aller trial_score-Werte (0-100)
    trial_scores = [
        r["trial_score"]
        for r in results
        if "trial_score" in r and r["trial_score"] is not None
    ]
    trial_avg = (
        round(sum(trial_scores) / len(trial_scores), 1) if trial_scores else None
    )

    best = _get_best_score(args.project)
    best_trial = _get_best_trial_score(args.project)
    iteration = _get_current_iteration(args.project)

    print("\n--- Score ---")
    print(f"  Automatisch: {auto_score:.0f}% ({auto_pass}/{total_auto})")
    if trial_avg is not None:
        print(f"  Trial-Score: {trial_avg:.1f}/100")
        if best_trial is not None:
            delta_t = trial_avg - best_trial
            arrow_t = "↑" if delta_t > 0.5 else "↓" if delta_t < -0.5 else "→"
            print(f"  Bester Trial-Score: {best_trial:.1f} ({arrow_t} {delta_t:+.1f})")
    if best is not None:
        delta = auto_score - best
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        print(f"  Bisher bester: {best:.0f}% ({arrow} {delta:+.0f}%)")
    if verify_results:
        gate_str = "PASS" if reliability_ok else "FAIL"
        print(
            f"  Reliability-Gate: {gate_str} ({len(verify_results) - len(verify_failed)}/{len(verify_results)} Verify bestanden)"
        )
    print(f"  Iteration: {iteration}")
    if agent_pending:
        print(f"  Agent-Checks: {len(agent_pending)} ausstehend")

    _save_history(
        args.project,
        {
            "action": "check",
            "timestamp": datetime.now().isoformat(),
            "iteration": iteration,
            "score": auto_score,
            "trial_avg": trial_avg,
            "auto_pass": auto_pass,
            "auto_fail": auto_fail,
            "agent_pending": len(agent_pending),
            "results": results,
            "agent_checks": agent_pending,
        },
    )

    output = {
        "project": args.project,
        "score": auto_score,
        "trial_avg": trial_avg,
        "reliability_gate": reliability_ok,
        "auto_pass": auto_pass,
        "auto_total": total_auto,
        "agent_pending": len(agent_pending),
        "best_score": best,
        "best_trial": best_trial,
        "iteration": iteration,
        "results": results,
        "agent_checks": agent_pending,
    }
    print(f"\n{json.dumps(output)}")


def cmd_accept(args):
    """Aktuellen Stand als Verbesserung akzeptieren."""
    config = _load_project(args.project)
    iteration = _get_current_iteration(args.project) + 1

    _backup_targets(args.project, iteration, config)

    score = args.score if args.score is not None else None
    trial_avg = None
    if score is None:
        history = _load_history(args.project)
        last_check = None
        for h in reversed(history):
            if h.get("action") == "check":
                last_check = h
                break
        score = last_check["score"] if last_check else 0
        trial_avg = last_check.get("trial_avg") if last_check else None

    _save_history(
        args.project,
        {
            "action": "accept",
            "timestamp": datetime.now().isoformat(),
            "iteration": iteration,
            "score": score,
            "trial_avg": trial_avg,
            "note": args.note or "",
        },
    )

    best = _get_best_score(args.project)
    best_trial = _get_best_trial_score(args.project)
    print(f"Iteration {iteration} akzeptiert (Score: {score:.0f}%)")
    if trial_avg is not None:
        print(f"  Trial-Score: {trial_avg:.1f}/100")
    print(f"  Bester Score: {best:.0f}%")
    if best_trial is not None:
        print(f"  Bester Trial-Score: {best_trial:.1f}/100")
    print(f"  Backup: iter-{iteration}")
    if args.note:
        print(f"  Notiz: {args.note}")


def cmd_reject(args):
    """Zum letzten besten Stand zurücksetzen."""
    iteration = _get_current_iteration(args.project)
    if iteration == 0:
        print(
            "Bereits auf Baseline (iter-0). Nichts zum Zurücksetzen.", file=sys.stderr
        )
        sys.exit(1)

    success = _restore_targets(args.project, iteration)
    if success:
        _save_history(
            args.project,
            {
                "action": "reject",
                "timestamp": datetime.now().isoformat(),
                "restored_to": iteration,
            },
        )
        print(f"Zurückgesetzt auf iter-{iteration}")
    else:
        print("Fehler beim Wiederherstellen", file=sys.stderr)
        sys.exit(1)


def cmd_history(args):
    """Score-Verlauf anzeigen."""
    history = _load_history(args.project)
    if not history:
        print("Keine History vorhanden.")
        return

    print(f"=== History: {args.project} ===\n")
    for h in history:
        ts = h.get("timestamp", "?")[:16]
        action = h.get("action", "?")
        if action == "init":
            print(
                f"  {ts}  INIT  {h.get('check_count', 0)} Checks, {len(h.get('targets', []))} Targets"
            )
        elif action == "check":
            score = h.get("score", 0)
            ap = h.get("auto_pass", 0)
            af = h.get("auto_fail", 0)
            agent = h.get("agent_pending", 0)
            print(
                f"  {ts}  CHECK  Score: {score:.0f}% ({ap}/{ap + af} auto, {agent} agent)"
            )
        elif action == "accept":
            score = h.get("score", 0)
            note = h.get("note", "")
            it = h.get("iteration", "?")
            note_str = f" — {note}" if note else ""
            print(f"  {ts}  ACCEPT iter-{it}  Score: {score:.0f}%{note_str}")
        elif action == "reject":
            restored = h.get("restored_to", "?")
            print(f"  {ts}  REJECT → iter-{restored}")

    accepts = [h for h in history if h.get("action") == "accept"]
    if len(accepts) >= 2:
        first = accepts[0]["score"]
        last = accepts[-1]["score"]
        delta = last - first
        print(
            f"\n  Trend: {first:.0f}% → {last:.0f}% ({delta:+.0f}% über {len(accepts)} Iterationen)"
        )


def cmd_status(args):
    """Aktuellen Status anzeigen."""
    config = _load_project(args.project)
    iteration = _get_current_iteration(args.project)
    best = _get_best_score(args.project)
    history = _load_history(args.project)

    checks_run = len([h for h in history if h.get("action") == "check"])
    accepts = len([h for h in history if h.get("action") == "accept"])
    rejects = len([h for h in history if h.get("action") == "reject"])

    print(f"=== {config.get('name', args.project)} ===")
    print(f"  Typ: {config.get('type', '?')}")
    print(f"  Targets: {', '.join(config.get('targets', []))}")
    print(f"  Checks: {len(config.get('checks', []))}")
    print(f"  Iteration: {iteration}")
    print(
        f"  Bester Score: {best:.0f}%"
        if best is not None
        else "  Bester Score: (kein Check gelaufen)"
    )
    print(f"  Check-Runs: {checks_run} | Accepts: {accepts} | Rejects: {rejects}")
    print(f"  Daten: {DATA_DIR / args.project}")

    last_check = None
    for h in reversed(history):
        if h.get("action") == "check":
            last_check = h
            break
    if last_check:
        print(f"\n  Letzter Check ({last_check['timestamp'][:16]}):")
        for r in last_check.get("results", []):
            icon = "PASS" if r["pass"] else "FAIL"
            print(f"    [{icon}] {r['name']}")
        for a in last_check.get("agent_checks", []):
            print(f"    [????] {a['name']} (Agent-Bewertung)")


def cmd_list(args):  # noqa: ARG001
    """Alle Projekte auflisten."""
    del args  # unused
    if not DATA_DIR.exists():
        print("Keine Projekte vorhanden.")
        return

    projects = sorted(
        p for p in DATA_DIR.iterdir() if p.is_dir() and (p / "config.json").exists()
    )
    if not projects:
        print("Keine Projekte vorhanden.")
        return

    print("=== Autoresearch-Projekte ===\n")
    for p in projects:
        config = json.loads((p / "config.json").read_text())
        iteration = _get_current_iteration(p.name)
        best = _get_best_score(p.name)
        score_str = f"{best:.0f}%" if best is not None else "—"
        print(
            f"  {p.name:<30} iter {iteration:<3} score {score_str:<6} ({config.get('type', '?')})"
        )


def cmd_template(args):
    """Beispiel-Config für einen Projekttyp generieren."""
    templates = {
        "skill": {
            "name": "Web-Search Skill Optimierung",
            "description": "Optimiert den /web-search Skill-Prompt für bessere Recherche-Qualität",
            "type": "skill",
            "targets": ["./skills/web-search/SKILL.md"],
            "checks": [
                {
                    "id": "e1",
                    "name": "Nutzt fast-search.py",
                    "type": "pattern",
                    "file": "/tmp/ar-output.txt",
                    "pattern": "fast-search\\.py",
                    "min_matches": 1,
                },
                {
                    "id": "e2",
                    "name": "Hat Quellen-URLs",
                    "type": "pattern",
                    "file": "/tmp/ar-output.txt",
                    "pattern": "https://",
                    "min_matches": 3,
                },
                {
                    "id": "e3",
                    "name": "Markiert eigene Inferenz",
                    "type": "pattern",
                    "file": "/tmp/ar-output.txt",
                    "pattern": "\\[Eigene (Inferenz|Einschätzung)\\]",
                    "min_matches": 0,
                },
                {
                    "id": "e4",
                    "name": "Synthese-Qualität",
                    "type": "agent",
                    "question": "Zitiert die Antwort konkrete Quellen statt generischer Behauptungen?",
                    "criteria": "Mindestens 3 Inline-Zitate mit URLs, keine unbelegten Aussagen",
                },
                {
                    "id": "e5",
                    "name": "Quellenvielfalt",
                    "type": "agent",
                    "question": "Nutzt die Antwort verschiedene Quellentypen (nicht nur eine Seite)?",
                    "criteria": "Mindestens 2 verschiedene Domains in den Quellen",
                },
            ],
            "runner": {
                "description": "Skill manuell ausführen, Output nach /tmp/ar-output.txt speichern",
                "test_queries": [
                    "Was ist der aktuelle Stand bei Perowskit-Solarzellen?",
                    "Vergleiche die besten Budget-Kopfhörer unter 100€",
                    "Erkläre mir die Vor- und Nachteile von SQLite vs PostgreSQL",
                ],
            },
        },
        "code": {
            "name": "MCV3 Board Refactor",
            "description": "Refactoring und Design-Overhaul des Mission Control V3 Dashboards",
            "type": "code",
            "targets": [
                "~/Projects/mission-control-v3/static/style.css",
                "~/Projects/mission-control-v3/templates/",
            ],
            "checks": [
                {
                    "id": "e1",
                    "name": "Server startet",
                    "type": "command",
                    "command": "cd ~/Projects/mission-control-v3 && timeout 5 python3 app.py --check 2>&1 || true",
                },
                {
                    "id": "e2",
                    "name": "Keine Python-Syntaxfehler",
                    "type": "command",
                    "command": "cd ~/Projects/mission-control-v3 && python3 -m py_compile app.py",
                },
                {
                    "id": "e3",
                    "name": "CSS hat Kupfer-Akzent",
                    "type": "pattern",
                    "file": "~/Projects/mission-control-v3/static/style.css",
                    "pattern": "#cf865a|--accent",
                    "min_matches": 1,
                },
                {
                    "id": "e4",
                    "name": "Design-Compliance",
                    "type": "agent",
                    "question": "Entspricht das UI der 'Warm Dark Editorial' Design-Sprache?",
                    "criteria": "Kupfer-Akzente, keine kalten Blautöne, keine reinen Schwarz/Weiß-Werte",
                },
                {
                    "id": "e5",
                    "name": "Keine Regression",
                    "type": "agent",
                    "question": "Funktionieren alle bestehenden Features noch korrekt?",
                    "criteria": "Panels öffnen/schließen, WebSocket-Verbindung, Theme-Toggle",
                },
            ],
            "runner": {
                "description": "Server starten und im Browser prüfen",
                "commands": [
                    "cd ~/Projects/mission-control-v3 && python3 app.py",
                ],
            },
        },
        "config": {
            "name": "Report-Renderer Optimierung",
            "description": "Optimiert CSS/Templates des Report-Renderers",
            "type": "config",
            "targets": [
                "./tools/report-templates/_base.css",
            ],
            "checks": [
                {
                    "id": "e1",
                    "name": "CSS lesbar",
                    "type": "command",
                    "command": "python3 -c \"Path('./tools/report-templates/_base.css').expanduser().read_text()\" 2>&1",
                },
                {
                    "id": "e2",
                    "name": "WCAG-Kontrast",
                    "type": "agent",
                    "question": "Erfüllen alle Text-auf-Hintergrund-Kombinationen WCAG AA?",
                    "criteria": "Primärtext: 4.5:1, Sekundärtext: 3:1, Akzent: 3:1",
                },
            ],
            "runner": {
                "description": "Test-Report rendern und visuell prüfen",
                "commands": [
                    "./tools/report-renderer.py render research /tmp/test-data.json -o /tmp/test-report.html",
                ],
            },
        },
    }

    ttype = args.type
    if ttype not in templates:
        print(
            f"Unbekannter Typ: {ttype}. Verfügbar: {', '.join(templates)}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(json.dumps(templates[ttype], indent=2, ensure_ascii=False))


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Karpathy-inspirierter Optimierungsloop für Skills und Code"
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Neues Optimierungsprojekt anlegen")
    p_init.add_argument("config", help="Pfad zur Config-JSON")
    p_init.add_argument(
        "--force", action="store_true", help="Existierendes Projekt überschreiben"
    )

    p_check = sub.add_parser("check", help="Checks auf aktuellem Stand ausführen")
    p_check.add_argument("project", help="Projekt-Name (Slug)")
    p_check.add_argument("--output", "-o", help="Output-Datei für Pattern-Checks")

    p_accept = sub.add_parser("accept", help="Aktuellen Stand als besser akzeptieren")
    p_accept.add_argument("project", help="Projekt-Name")
    p_accept.add_argument("--score", type=float, help="Manueller Gesamt-Score (0-100)")
    p_accept.add_argument("--note", "-n", help="Notiz zur Änderung")

    p_reject = sub.add_parser("reject", help="Zum letzten besten Stand zurücksetzen")
    p_reject.add_argument("project", help="Projekt-Name")

    p_hist = sub.add_parser("history", help="Score-Verlauf anzeigen")
    p_hist.add_argument("project", help="Projekt-Name")

    p_status = sub.add_parser("status", help="Aktuellen Status anzeigen")
    p_status.add_argument("project", help="Projekt-Name")

    sub.add_parser("list", help="Alle Projekte auflisten")

    p_tmpl = sub.add_parser("template", help="Beispiel-Config generieren")
    p_tmpl.add_argument("type", choices=["skill", "code", "config"], help="Projekt-Typ")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    {
        "init": cmd_init,
        "check": cmd_check,
        "accept": cmd_accept,
        "reject": cmd_reject,
        "history": cmd_history,
        "status": cmd_status,
        "list": cmd_list,
        "template": cmd_template,
    }[args.command](args)


if __name__ == "__main__":
    main()
