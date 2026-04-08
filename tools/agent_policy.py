#!/usr/bin/env python3
"""Agent Policy Engine — Single Source of Truth for agent guardrails.

All enforcement rules are defined here. Hooks import this module.
Nightly agent reads escalation state and adjusts severities.

Usage from hooks:
    from agent_policy import check, log_event, track_read, was_read

Usage from CLI:
    agent_policy.py stats          # Violation stats (7 days)
    agent_policy.py rules          # List all rules with current severity
    agent_policy.py escalate       # Auto-escalate based on thresholds
    agent_policy.py top-violations # Top 3 for session-start priming
"""

import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse  # noqa: F401 — used in WebFetchBlockRule.match()

# --- Paths ---
TRACKER_DB = Path.home() / ".claude/tools/skill-tracker.db"
STATE_FILE = Path.home() / ".claude/data/policy-state.json"
READ_STATE = Path("/tmp/claude-read-files.txt")


# --- Severity Levels ---
ALLOW = "allow"
WARN = "warn"
BLOCK = "block"
BLOCK_REWRITE = "block_with_rewrite"

# Escalation order
SEVERITY_ORDER = [ALLOW, WARN, BLOCK, BLOCK_REWRITE]


# --- Rule Definition ---
@dataclass
class Rule:
    id: str
    scope: str  # Tool name: "Bash", "Edit", "Write", "Grep", "Agent", "WebSearch", "WebFetch"
    description: str
    base_severity: str
    rewrite_hint: str | None = None
    escalation_threshold: int = 3  # violations in 7 days → auto-escalate
    exceptions: list[str] = field(default_factory=list)

    def match(self, tool_input: dict) -> bool:
        """Override in subclasses."""
        return False

    @property
    def severity(self) -> str:
        """Current severity = max(base, escalation override)."""
        overrides = _load_overrides()
        override = overrides.get(self.id)
        if override and SEVERITY_ORDER.index(override) > SEVERITY_ORDER.index(
            self.base_severity
        ):
            return override
        return self.base_severity


# --- Rule Implementations ---


class BashCatRule(Rule):
    """Block cat/head/tail with file arguments → use Read tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        if not re.search(r"\b(cat|head|tail)\s+(-[a-zA-Z0-9]*\s+)*[~/$.\w]", cmd):
            return False
        # Exceptions: heredoc, /dev/, tail -f, process substitution
        if re.search(r"\bcat\s*<<|/dev/|\btail\s+-[fF]\b|<\(", cmd):
            return False
        return True


class BashGrepRule(Rule):
    """Block grep/rg as primary command → use Grep tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        first_seg = cmd.split("|")[0]
        return bool(re.search(r"(^\s*|&&\s*|;\s*)\s*(grep|rg)\s+", first_seg))


class BashFindRule(Rule):
    """Block find as primary command → use Glob tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        first_seg = cmd.split("|")[0]
        return bool(re.search(r"(^\s*|&&\s*|;\s*)\s*find\s+", first_seg))


class BashSedRule(Rule):
    """Block sed -i → use Edit tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        first_seg = cmd.split("|")[0]
        return bool(re.search(r"\bsed\s+.*-i", first_seg))


class BashAwkRule(Rule):
    """Block awk/perl read-mode with file arguments → use Read or Grep tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        first_seg = cmd.split("|")[0]
        # Don't match perl -pi (in-place edit) — that's BashPerlEditRule
        if re.search(r"\bperl\s+.*-[a-zA-Z]*p[a-zA-Z]*i", first_seg):
            return False
        return bool(re.search(r"\b(awk|perl)\s+.*['\"].*['\"]\s+[~/$.\w]", first_seg))


class BashPerlEditRule(Rule):
    """Block perl -pi / perl -i (in-place file edit) → use Edit tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        first_seg = cmd.split("|")[0]
        return bool(
            re.search(r"\bperl\s+.*-[a-zA-Z]*[pi][a-zA-Z]*i?\s", first_seg)
            and re.search(r"-[a-zA-Z]*i", first_seg)
        )


class BashPythonReadRule(Rule):
    """Block python -c 'open(...)' → use Read tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        return bool(re.search(r"python3?\s+-c\s+['\"].*\bopen\s*\(", cmd))


class BashLsTreeRule(Rule):
    """Block ls -R / tree for file discovery → use Glob tool."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        first_seg = cmd.split("|")[0]
        return bool(re.search(r"\b(ls\s+-[a-zA-Z]*R|tree(\s|$))", first_seg))


class EditWithoutReadRule(Rule):
    """Block Edit/Write on files not Read in this session."""

    def match(self, tool_input: dict) -> bool:
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return False
        # Write to new files is OK
        if self.scope == "Write" and not os.path.exists(file_path):
            return False
        return not was_read(file_path)


class WebSearchBlockRule(Rule):
    """Block native WebSearch → use /web-search skill."""

    def match(self, tool_input: dict) -> bool:
        query = tool_input.get("query", "") or tool_input.get("search_query", "")
        # Allow site:-queries
        if re.search(r"\bsite:", query):
            return False
        return True


class WebFetchBlockRule(Rule):
    """Block native WebFetch except docs/API/GitHub/localhost."""

    _ALLOWED_HOSTS = {
        "github.com",
        "raw.githubusercontent.com",
        "localhost",
        "127.0.0.1",
        "pypi.org",
        "npmjs.com",
        "googleapis.com",
        "google.dev",
    }
    _ALLOWED_PREFIXES = ("docs.", "api.")

    def match(self, tool_input: dict) -> bool:
        url = tool_input.get("url", "")
        try:
            hostname = urlparse(url).hostname or ""
        except Exception:
            return True  # Block unparseable URLs
        # Exact match or suffix match for subdomains
        for allowed in self._ALLOWED_HOSTS:
            if hostname == allowed or hostname.endswith(f".{allowed}"):
                return False
        # Prefix match for docs.*, api.*
        for prefix in self._ALLOWED_PREFIXES:
            if hostname.startswith(prefix):
                return False
        return True


# --- Security Rules ---


class BashDangerousCommandRule(Rule):
    """Block dangerous shell patterns: curl|bash, wget|sh, base64 decode pipes."""

    _PATTERNS = [
        r"\bcurl\b.*\|\s*(sudo\s+)?\b(ba)?sh\b",
        r"\bwget\b.*\|\s*(sudo\s+)?\b(ba)?sh\b",
        r"\bcurl\b.*\|\s*python",
        r"\bbase64\s+-d\b.*\|\s*(sudo\s+)?\b(ba)?sh\b",
        r"\beval\s*\$\(curl",
        r"\beval\s*\$\(wget",
    ]

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        return any(re.search(p, cmd) for p in self._PATTERNS)


class BashCriticalFileModRule(Rule):
    """Block modifications to security-critical files."""

    _PROTECTED = [
        r"\.ssh/authorized_keys",
        r"\.ssh/config",
        r"\.claude/settings\.json",
        r"\.claude/hooks/guard-policy\.py",
        r"\.claude/tools/agent_policy\.py",
        r"/etc/ssh/sshd_config",
        r"/etc/sudoers",
        r"/etc/shadow",
        r"/etc/passwd",
    ]

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        # Detect write operations to protected files
        write_patterns = [
            r"\btee\b",
            r">>?\s",
            r"\bsed\s+-i",
            r"\bchmod\b",
            r"\bchown\b",
        ]
        has_write = any(re.search(wp, cmd) for wp in write_patterns)
        if not has_write:
            return False
        return any(re.search(pf, cmd) for pf in self._PROTECTED)


class BashPackageInstallRule(Rule):
    """Warn on package installations — supply chain risk."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        # npm install (but not npm audit, npm list, etc.)
        if re.search(r"\bnpm\s+install\b", cmd):
            return True
        # pip install (but not pip list, pip audit)
        if re.search(r"\bpip\s+install\b", cmd):
            return True
        # uv add
        if re.search(r"\buv\s+add\b", cmd):
            return True
        # curl to unknown script
        if re.search(r"\bcurl\b.*-[sOL].*\bsh\b", cmd):
            return True
        return False


class BashCredentialExfilRule(Rule):
    """Block commands that could exfiltrate credentials."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        # Detect: cat/read .env piped to curl/wget/nc
        if re.search(r"\.env\b", cmd) and re.search(r"\b(curl|wget|nc|ncat)\b", cmd):
            return True
        # Detect: env/printenv piped to network tools
        if re.search(r"\b(env|printenv)\b", cmd) and re.search(
            r"\|\s*(curl|wget|nc)", cmd
        ):
            return True
        # Detect: sending SSH keys
        if re.search(r"\.ssh/", cmd) and re.search(r"\b(curl|wget|nc|scp)\b", cmd):
            return True
        return False


class BashPersistenceRule(Rule):
    """Warn on commands that establish persistence."""

    def match(self, tool_input: dict) -> bool:
        cmd = tool_input.get("command", "")
        # Detect: systemctl enable (new services)
        if re.search(r"\bsystemctl\s+enable\b", cmd):
            return True
        # Detect: crontab modifications
        if re.search(r"\bcrontab\s+(-[a-zA-Z]*\s+)*[^-l]", cmd):
            # Allow crontab -l (list)
            if not re.search(r"\bcrontab\s+-l\b", cmd):
                return True
        return False


class EditCriticalFileRule(Rule):
    """Block Edit/Write to security-critical files."""

    _PROTECTED_PATHS = [
        ".ssh/authorized_keys",
        ".claude/settings.json",
        ".claude/hooks/guard-policy.py",
        ".claude/tools/agent_policy.py",
        ".claude/tools/integrity-monitor.py",
    ]

    def match(self, tool_input: dict) -> bool:
        file_path = tool_input.get("file_path", "")
        return any(p in file_path for p in self._PROTECTED_PATHS)


# --- Rule Registry ---

RULES: list[Rule] = [
    # Bash scope
    BashCatRule(
        id="bash_cat",
        scope="Bash",
        description="Verwende das Read-Tool statt cat/head/tail.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="Read-Tool mit file_path und ggf. offset/limit",
    ),
    BashGrepRule(
        id="bash_grep",
        scope="Bash",
        description="Verwende das Grep-Tool statt Bash grep/rg.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="Grep-Tool mit pattern, path, output_mode",
    ),
    BashFindRule(
        id="bash_find",
        scope="Bash",
        description="Verwende das Glob-Tool statt find.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="Glob-Tool mit pattern (z.B. '**/*.py')",
    ),
    BashSedRule(
        id="bash_sed",
        scope="Bash",
        description="Verwende das Edit-Tool statt sed -i.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="Edit-Tool mit old_string/new_string",
    ),
    BashAwkRule(
        id="bash_awk",
        scope="Bash",
        description="Verwende Read oder Grep statt awk/perl mit Dateiargument.",
        base_severity=WARN,
        rewrite_hint="Read-Tool oder Grep-Tool je nach Anwendungsfall",
        escalation_threshold=5,
    ),
    BashPerlEditRule(
        id="bash_perl_edit",
        scope="Bash",
        description="Verwende das Edit-Tool statt perl -pi (in-place edit).",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="Edit-Tool mit old_string/new_string",
    ),
    BashPythonReadRule(
        id="bash_python_read",
        scope="Bash",
        description="Verwende das Read-Tool statt python -c 'open(...)'.",
        base_severity=WARN,
        rewrite_hint="Read-Tool mit file_path",
        escalation_threshold=3,
    ),
    BashLsTreeRule(
        id="bash_ls_tree",
        scope="Bash",
        description="Verwende das Glob-Tool statt ls -R / tree.",
        base_severity=WARN,
        rewrite_hint="Glob-Tool mit pattern",
        escalation_threshold=3,
    ),
    # Edit/Write scope
    EditWithoutReadRule(
        id="edit_without_read",
        scope="Edit",
        description="Datei wurde noch nicht gelesen.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="Erst Read-Tool, dann Edit",
    ),
    EditWithoutReadRule(
        id="write_without_read",
        scope="Write",
        description="Datei wurde noch nicht gelesen.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="Erst Read-Tool, dann Write (oder Write nur für neue Dateien)",
    ),
    # WebSearch/WebFetch scope
    WebSearchBlockRule(
        id="web_search_block",
        scope="WebSearch",
        description="Verwende /web-search Skill statt natives WebSearch.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="/web-search Skill (60x schneller, mit research-crawler)",
    ),
    WebFetchBlockRule(
        id="web_fetch_block",
        scope="WebFetch",
        description="Verwende /web-search Skill für Web-Research.",
        base_severity=BLOCK_REWRITE,
        rewrite_hint="/web-search Skill. Natives WebFetch nur für docs/API/GitHub/localhost",
    ),
    # Security rules
    BashDangerousCommandRule(
        id="sec_dangerous_cmd",
        scope="Bash",
        description="⚠ SECURITY: curl|bash, wget|sh oder base64-Pipe erkannt. Niemals remote Scripts direkt ausführen!",
        base_severity=BLOCK,
    ),
    BashCriticalFileModRule(
        id="sec_critical_file_mod",
        scope="Bash",
        description="⚠ SECURITY: Modifikation einer sicherheitskritischen Datei erkannt.",
        base_severity=BLOCK,
    ),
    BashPackageInstallRule(
        id="sec_package_install",
        scope="Bash",
        description="⚠ Supply-Chain-Risiko: Paket-Installation. Prüfe das Paket vor Installation (Downloads, Alter, Maintainer).",
        base_severity=WARN,
        escalation_threshold=5,
    ),
    BashCredentialExfilRule(
        id="sec_credential_exfil",
        scope="Bash",
        description="⚠ SECURITY: Mögliche Credential-Exfiltration erkannt! .env/SSH-Daten an externe Dienste senden ist verboten.",
        base_severity=BLOCK,
    ),
    BashPersistenceRule(
        id="sec_persistence",
        scope="Bash",
        description="⚠ SECURITY: Persistence-Mechanismus erkannt (systemctl enable / crontab). Nur mit expliziter User-Genehmigung.",
        base_severity=WARN,
        escalation_threshold=3,
    ),
    EditCriticalFileRule(
        id="sec_edit_critical",
        scope="Edit",
        description="⚠ SECURITY: Diese Datei ist sicherheitskritisch und durch chattr +i geschützt.",
        base_severity=BLOCK,
    ),
    EditCriticalFileRule(
        id="sec_write_critical",
        scope="Write",
        description="⚠ SECURITY: Diese Datei ist sicherheitskritisch und durch chattr +i geschützt.",
        base_severity=BLOCK,
    ),
]

# Index for fast lookup
_RULES_BY_SCOPE: dict[str, list[Rule]] = {}
for _r in RULES:
    _RULES_BY_SCOPE.setdefault(_r.scope, []).append(_r)


# --- Core API ---


def check(tool_name: str, tool_input: dict) -> tuple[str, str, str | None]:
    """Check a tool call against all rules.

    Returns: (decision, message, rule_id)
        decision: "allow" | "warn" | "block" | "block_with_rewrite"
        message: human-readable explanation (empty if allow)
        rule_id: matched rule ID (None if allow)
    """
    for rule in _RULES_BY_SCOPE.get(tool_name, []):
        if rule.match(tool_input):
            severity = rule.severity
            msg = rule.description
            if rule.rewrite_hint and severity == BLOCK_REWRITE:
                msg += f" → {rule.rewrite_hint}"
            return (severity, msg, rule.id)
    return (ALLOW, "", None)


def _normalize_path(file_path: str) -> str:
    """Normalize path for consistent comparison."""
    try:
        return str(Path(file_path).resolve())
    except (OSError, ValueError):
        return file_path


def track_read(file_path: str) -> None:
    """Track that a file was Read (for edit_without_read rule)."""
    if not file_path:
        return
    normalized = _normalize_path(file_path)
    # Rotate at 1000 entries
    if READ_STATE.exists():
        try:
            lines = READ_STATE.read_text().splitlines()
            if len(lines) > 1000:
                READ_STATE.write_text("\n".join(lines[-500:]) + "\n")
        except OSError:
            pass
    try:
        with open(READ_STATE, "a") as f:
            f.write(normalized + "\n")
    except OSError:
        pass


def was_read(file_path: str) -> bool:
    """Check if a file was Read in this session (exact line match, normalized)."""
    if not READ_STATE.exists():
        return False
    normalized = _normalize_path(file_path)
    try:
        return normalized in READ_STATE.read_text().splitlines()
    except OSError:
        return False


# --- Telemetry ---


def log_event(
    rule_id: str,
    event_type: str,
    tool_name: str = "",
    detail: str = "",
) -> None:
    """Log guardrail event to skill-tracker.db events table.

    event_type: 'block' | 'warn' | 'corrected' | 'escalated'
    """
    try:
        db = sqlite3.connect(str(TRACKER_DB), timeout=2)
        db.execute(
            """INSERT INTO events (source, event_type, domain, status, value_text, meta)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "guardrail",
                event_type,
                rule_id,
                "ok",
                tool_name,
                json.dumps({"detail": detail[:200]}, ensure_ascii=False)
                if detail
                else None,
            ),
        )
        db.commit()
        db.close()
    except Exception:
        pass  # Telemetry must never break the hook


# --- Escalation State ---


def _load_overrides() -> dict[str, str]:
    """Load severity overrides from state file."""
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text())
        return data.get("overrides", {})
    except Exception:
        return {}


def _save_overrides(overrides: dict[str, str]) -> None:
    """Save severity overrides."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"overrides": overrides, "updated": datetime.now().isoformat()}
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# --- Correction Detection ---


_LAST_BLOCK_FILE = Path("/tmp/claude-policy-last-block.json")


def record_block(rule_id: str, tool_name: str, context: str = "") -> None:
    """Record the last block for correction detection.

    context: e.g. file_path or command snippet for precise matching.
    """
    try:
        _LAST_BLOCK_FILE.write_text(
            json.dumps(
                {
                    "rule_id": rule_id,
                    "tool_name": tool_name,
                    "context": context[:200],
                    "ts": datetime.now().isoformat(),
                }
            )
        )
    except OSError:
        pass


def check_correction(tool_name: str, tool_input: dict | None = None) -> str | None:
    """Check if current tool call is a correction of a previous block.

    Returns rule_id if this is a correction, None otherwise.
    Uses context matching when available for precision.
    """
    if not _LAST_BLOCK_FILE.exists():
        return None
    try:
        data = json.loads(_LAST_BLOCK_FILE.read_text())
    except Exception:
        return None

    rule_id = data.get("rule_id", "")
    block_context = data.get("context", "")

    # Correction mapping: after blocking bash_cat, using Read is a correction
    corrections = {
        "bash_cat": "Read",
        "bash_grep": "Grep",
        "bash_find": "Glob",
        "bash_sed": "Edit",
        "bash_awk": "Read",
        "bash_perl_edit": "Edit",
        "bash_python_read": "Read",
        "bash_ls_tree": "Glob",
        "edit_without_read": "Read",
        "write_without_read": "Read",
        "web_search_block": "Skill",
        "web_fetch_block": "Skill",
    }

    expected = corrections.get(rule_id)
    if expected and tool_name == expected:
        # Context matching: if we have a blocked file_path, the correction
        # should reference the same file (not just any Read call)
        if block_context and tool_input:
            correction_target = tool_input.get("file_path", "") or tool_input.get(
                "url", ""
            )
            if correction_target and block_context not in correction_target:
                # Different target — not a true correction, but still clear the block
                try:
                    _LAST_BLOCK_FILE.unlink()
                except OSError:
                    pass
                return None
        # Clear the block record
        try:
            _LAST_BLOCK_FILE.unlink()
        except OSError:
            pass
        return rule_id

    # If agent does something else entirely, clear after 1 call
    try:
        _LAST_BLOCK_FILE.unlink()
    except OSError:
        pass
    return None


# --- CLI Commands ---


def cmd_stats():
    """Show violation stats for the last 7 days."""
    try:
        db = sqlite3.connect(str(TRACKER_DB), timeout=2)
        rows = db.execute(
            """SELECT domain as rule_id, event_type, COUNT(*) as cnt
               FROM events
               WHERE source = 'guardrail'
                 AND ts >= datetime('now', '-7 days', 'localtime')
               GROUP BY domain, event_type
               ORDER BY cnt DESC"""
        ).fetchall()
        db.close()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    if not rows:
        print("Keine Guardrail-Events in den letzten 7 Tagen.")
        return

    print(f"{'Rule ID':<25} {'Event':<12} {'Count':>5}")
    print("-" * 45)
    for rule_id, event_type, cnt in rows:
        print(f"{rule_id:<25} {event_type:<12} {cnt:>5}")


def cmd_rules():
    """List all rules with current severity."""
    _load_overrides()
    print(f"{'ID':<25} {'Scope':<12} {'Base':<20} {'Current':<20} {'Threshold':>5}")
    print("-" * 85)
    for rule in RULES:
        current = rule.severity
        marker = " ↑" if current != rule.base_severity else ""
        print(
            f"{rule.id:<25} {rule.scope:<12} {rule.base_severity:<20} "
            f"{current + marker:<20} {rule.escalation_threshold:>5}"
        )


def cmd_escalate():
    """Auto-escalate rules based on violation thresholds."""
    try:
        db = sqlite3.connect(str(TRACKER_DB), timeout=2)
        rows = db.execute(
            """SELECT domain as rule_id, COUNT(*) as cnt
               FROM events
               WHERE source = 'guardrail'
                 AND event_type IN ('block', 'warn')
                 AND ts >= datetime('now', '-7 days', 'localtime')
               GROUP BY domain"""
        ).fetchall()
        db.close()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    violation_counts = dict(rows)
    overrides = _load_overrides()
    changes = []

    for rule in RULES:
        count = violation_counts.get(rule.id, 0)
        if count >= rule.escalation_threshold and rule.severity == WARN:
            # Escalate: warn → block
            overrides[rule.id] = BLOCK
            changes.append((rule.id, WARN, BLOCK, count))
            log_event(
                rule.id,
                "escalated",
                detail=f"warn→block after {count} violations in 7d",
            )

    if changes:
        _save_overrides(overrides)
        print("Auto-Eskalationen:")
        for rule_id, old, new, count in changes:
            print(f"  {rule_id}: {old} → {new} ({count} Verstöße)")
    else:
        print("Keine Eskalationen nötig.")


def cmd_top_violations():
    """Top 3 violations for session-start priming."""
    try:
        db = sqlite3.connect(str(TRACKER_DB), timeout=2)
        rows = db.execute(
            """SELECT domain as rule_id, COUNT(*) as cnt
               FROM events
               WHERE source = 'guardrail'
                 AND event_type IN ('block', 'warn')
                 AND ts >= datetime('now', '-7 days', 'localtime')
               GROUP BY domain
               ORDER BY cnt DESC
               LIMIT 3"""
        ).fetchall()
        db.close()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    if not rows:
        return  # Silent if no violations

    print("⚠ Top-Verstöße (letzte 7 Tage):")
    for rule_id, cnt in rows:
        rule = next((r for r in RULES if r.id == rule_id), None)
        hint = rule.rewrite_hint if rule else ""
        print(f"  {cnt}× {rule_id}: {hint}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: agent_policy.py {stats|rules|escalate|top-violations}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "stats":
        cmd_stats()
    elif cmd == "rules":
        cmd_rules()
    elif cmd == "escalate":
        cmd_escalate()
    elif cmd == "top-violations":
        cmd_top_violations()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
