#!/home/maetzger/.claude/tools/.venv/bin/python
"""Compress session handoff context for spawn-session and session recycling.

Reads a session-context.md (or raw text from stdin) and produces a compressed
YAML handoff that fits within a token budget. Extracts only decisions, results,
and actionable context — discards conversational filler, intermediate steps,
and verbose tables (collapsed to one-line summaries).

Usage:
    # Compress an existing session-context.md
    compress-handoff.py /path/to/session-context.md

    # Compress with custom token budget
    compress-handoff.py --budget 1500 /path/to/session-context.md

    # Pipe raw text
    echo "long conversation..." | compress-handoff.py --stdin

    # Write compressed output to file
    compress-handoff.py session-context.md -o /path/to/output.md

    # Include routing block (outside token budget)
    compress-handoff.py session-context.md --with-routing

Token estimation: ~4 chars per token (conservative for mixed en/de text).
Default budget: 2000 tokens (~8000 chars of YAML content).
"""

import argparse
import re
import sys
from pathlib import Path

# ~4 chars per token is conservative for mixed English/German text
CHARS_PER_TOKEN = 4
DEFAULT_BUDGET_TOKENS = 2000

# Patterns that indicate filler vs. substance
FILLER_PATTERNS = [
    r"^---\s*$",
    r"^\*\*Agent:\*\*\s*$",
    r"^Stimmt,?\s",
    r"^OK,?\s",
    r"^Gute Frage",
    r"^Kein Problem",
    r"^Lass mich",
    r"^Jetzt habe ich",
    r"^Perfekt\s*[—–-]",
    r"^\[\.{3}\s*gekürzt\]",
    r"^ETA\s",
    r"^Alle Daten zusammen",
    r"^Hier ist",
    r"^Vielversprechend",
    r"^Gute Treffer",
    r"^Die allgemeine Suche",
    r"^Endspurt",
    r"^Alter Timer",
    r"^Am Prompt",
]

# Patterns that indicate substantive content to keep
KEEP_PATTERNS = [
    r"^##\s",
    r"^###\s",
    r"^\*\*Ergebnis",
    r"^\*\*Fazit",
    r"^\*\*Empfehlung",
    r"^>\s",
    r"→\s",
    r"decision|entscheidung|beschluss",
    r"constraint|einschränkung|leitplanke",
    r"^\*\*Ja[,.]",
    r"^\*\*Nein[,.]",
]


def estimate_tokens(text: str) -> int:
    """Estimate token count from character length."""
    return len(text) // CHARS_PER_TOKEN


def is_filler(line: str) -> bool:
    """Check if a line is conversational filler."""
    stripped = line.strip()
    if not stripped:
        return True
    for pattern in FILLER_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            return True
    return False


def is_substantive(line: str) -> bool:
    """Check if a line contains substantive content worth keeping."""
    stripped = line.strip()
    for pattern in KEEP_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            return True
    return False


def extract_yaml_block(text: str) -> str | None:
    """Extract existing YAML handoff block if present."""
    match = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def collapse_table(lines: list[str]) -> str | None:
    """Collapse a Markdown table into a one-line summary.

    Returns the header columns + row count as a compact summary.
    """
    if not lines or not lines[0].strip().startswith("|"):
        return None

    header = None
    data_rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            continue  # separator row
        if header is None:
            header = stripped
        else:
            data_rows.append(stripped)

    if not header:
        return None

    # Extract column names from header
    cols = [c.strip().strip("*") for c in header.split("|") if c.strip()]
    return f"[Tabelle: {' | '.join(cols[:4])} — {len(data_rows)} Zeilen]"


def parse_recycled_context(text: str) -> dict:
    """Parse auto-recycled session-context.md into structured sections."""
    result = {
        "session_id": "",
        "extracted": "",
        "reason": "",
        "task_origin": "",
        "files_modified": [],
        "conversation_lines": [],
    }

    sid_match = re.search(r"Session-ID:\*\*\s*`([^`]+)`", text)
    if sid_match:
        result["session_id"] = sid_match.group(1)

    ext_match = re.search(r"Extrahiert:\*\*\s*(.+)", text)
    if ext_match:
        result["extracted"] = ext_match.group(1).strip()

    reason_match = re.search(r"Grund:\*\*\s*(.+)", text)
    if reason_match:
        result["reason"] = reason_match.group(1).strip()

    current_section = "header"
    for line in text.split("\n"):
        lower = line.strip().lower()

        if "ursprüngliche aufgabe" in lower:
            current_section = "task_origin"
            continue
        elif "bearbeitete dateien" in lower:
            current_section = "files_modified"
            continue
        elif "letzte konversation" in lower:
            current_section = "conversation"
            continue

        if current_section == "task_origin":
            if line.strip():
                result["task_origin"] += line + "\n"
        elif current_section == "files_modified":
            file_match = re.match(r"^-\s*`([^`]+)`", line.strip())
            if file_match:
                result["files_modified"].append(file_match.group(1))
        elif current_section == "conversation":
            result["conversation_lines"].append(line)

    return result


def compress_conversation(lines: list[str], budget_chars: int) -> list[str]:
    """Compress conversation lines to fit within character budget.

    Strategy:
    1. Group lines into agent message blocks
    2. Per block: keep only headers, conclusions, bold key points
    3. Collapse tables into one-line summaries
    4. Skip conversational filler entirely
    5. If still over budget: trim oldest findings first
    """
    current_agent_block = []
    agent_blocks = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("**Agent:**"):
            if current_agent_block:
                agent_blocks.append(current_agent_block)
            current_agent_block = []
            continue

        if is_filler(line):
            continue

        current_agent_block.append(line)

    if current_agent_block:
        agent_blocks.append(current_agent_block)

    # Extract key findings from each block
    findings = []
    for block in agent_blocks:
        block_findings = []
        table_buffer = []
        in_table = False

        for line in block:
            stripped = line.strip()
            if not stripped:
                if in_table and table_buffer:
                    summary = collapse_table(table_buffer)
                    if summary:
                        block_findings.append(summary)
                    table_buffer = []
                    in_table = False
                continue

            # Detect table rows
            if stripped.startswith("|"):
                in_table = True
                table_buffer.append(stripped)
                continue

            # Flush table buffer when leaving table
            if in_table and table_buffer:
                summary = collapse_table(table_buffer)
                if summary:
                    block_findings.append(summary)
                table_buffer = []
                in_table = False

            # Priority: headers and conclusions
            if is_substantive(line):
                block_findings.append(stripped)
            elif stripped.startswith("- **") or stripped.startswith("* **"):
                block_findings.append(stripped)
            elif "→" in stripped or "=>" in stripped:
                block_findings.append(stripped)

        # Flush remaining table
        if table_buffer:
            summary = collapse_table(table_buffer)
            if summary:
                block_findings.append(summary)

        # Fallback: last non-empty line from block
        if not block_findings and block:
            for line in reversed(block):
                if line.strip() and not is_filler(line):
                    block_findings.append(line.strip()[:200])
                    break

        findings.extend(block_findings)

    # Deduplicate
    seen = set()
    unique = []
    for line in findings:
        normalized = line.strip()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    # Trim from the beginning (oldest) if over budget
    result_text = "\n".join(unique)
    if len(result_text) > budget_chars:
        trimmed = []
        char_count = 0
        for line in reversed(unique):
            line_chars = len(line) + 1
            if char_count + line_chars > budget_chars:
                break
            trimmed.insert(0, line)
            char_count += line_chars
    else:
        trimmed = unique

    return trimmed


def compress_task_origin(text: str, budget_chars: int) -> str:
    """Compress task origin — usually a SKILL.md pasted in full.

    Keeps only the first heading and first meaningful line.
    """
    lines = text.strip().split("\n")
    compressed = []
    char_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("|"):
            continue
        if stripped.startswith("##") or stripped.startswith("#"):
            compressed.append(stripped)
            char_count += len(stripped) + 1
        elif stripped and char_count < budget_chars // 3:
            compressed.append(stripped)
            char_count += len(stripped) + 1

        if char_count >= budget_chars:
            break

    return "\n".join(compressed[:10])


def build_compressed_handoff(
    parsed: dict, budget_tokens: int, routing_block: str = ""
) -> str:
    """Build the compressed session-context.md from parsed sections."""
    budget_chars = budget_tokens * CHARS_PER_TOKEN
    yaml_overhead = 400

    content_budget = budget_chars - yaml_overhead
    task_budget = int(content_budget * 0.15)
    findings_budget = int(content_budget * 0.70)
    files_budget = int(content_budget * 0.15)

    task_compressed = compress_task_origin(
        parsed.get("task_origin", ""), task_budget
    )

    conversation_compressed = compress_conversation(
        parsed.get("conversation_lines", []), findings_budget
    )

    files = parsed.get("files_modified", [])
    kept_files = []
    char_count = 0
    for f in files:
        if char_count + len(f) + 10 > files_budget:
            break
        kept_files.append(f)
        char_count += len(f) + 10

    def _build(task_line, findings, files_list):
        parts = ["# Session Handoff (komprimiert)", ""]
        if parsed.get("session_id"):
            parts.append(f'**Vorherige Session:** `{parsed["session_id"]}`')
        if parsed.get("extracted"):
            parts.append(f'**Extrahiert:** {parsed["extracted"]}')
        parts.append("")
        parts.append("```yaml")
        parts.append(f'task: "{task_line}"')
        if findings:
            parts.append("ergebnisse:")
            for finding in findings:
                clean = finding.replace('"', "'").strip()
                if len(clean) > 200:
                    clean = clean[:197] + "..."
                parts.append(f'  - "{clean}"')
        if files_list:
            parts.append("bearbeitete_dateien:")
            for f in files_list:
                parts.append(f'  - "{f}"')
        parts.append("```")
        parts.append("")
        if routing_block:
            parts.append(routing_block)
        return "\n".join(parts)

    task_first_line = (
        task_compressed.split("\n")[0][:100] if task_compressed else "unbekannt"
    )
    result = _build(task_first_line, conversation_compressed, kept_files)

    # Emergency trim loop: drop oldest findings until within budget
    content_for_check = result
    if routing_block and routing_block in result:
        content_for_check = result[: result.index(routing_block)].strip()

    while (
        estimate_tokens(content_for_check) > budget_tokens * 1.1
        and conversation_compressed
    ):
        conversation_compressed.pop(0)
        result = _build(task_first_line, conversation_compressed, kept_files)
        content_for_check = result
        if routing_block and routing_block in result:
            content_for_check = result[: result.index(routing_block)].strip()

    return result


def compress_spawned_handoff(text: str, budget_tokens: int) -> str:
    """Compress a spawn-session YAML handoff that's already structured."""
    yaml_block = extract_yaml_block(text)
    if not yaml_block:
        parsed = parse_recycled_context(text)
        return build_compressed_handoff(parsed, budget_tokens)

    budget_chars = budget_tokens * CHARS_PER_TOKEN

    lines = yaml_block.split("\n")
    compressed_lines = []
    total_chars = 0

    for line in lines:
        if total_chars + len(line) > budget_chars * 0.7:
            if line.strip().startswith("-"):
                continue
            if ":" in line and not line.strip().startswith("-"):
                compressed_lines.append(line)
                total_chars += len(line) + 1
        else:
            compressed_lines.append(line)
            total_chars += len(line) + 1

    parts = []
    in_yaml = False
    yaml_done = False
    for line in text.split("\n"):
        if "```yaml" in line and not yaml_done:
            in_yaml = True
            parts.append(line)
            parts.extend(compressed_lines)
            continue
        if in_yaml and "```" in line and "yaml" not in line:
            in_yaml = False
            yaml_done = True
            parts.append(line)
            continue
        if not in_yaml:
            parts.append(line)

    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description="Compress session handoff context for spawn-session"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to session-context.md to compress",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read from stdin instead of file",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET_TOKENS,
        help=f"Token budget (default: {DEFAULT_BUDGET_TOKENS})",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write compressed output to file (default: stdout)",
    )
    parser.add_argument(
        "--with-routing",
        action="store_true",
        help="Append skill-routing-block.md to output",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print compression statistics to stderr",
    )

    args = parser.parse_args()

    if args.stdin:
        text = sys.stdin.read()
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Fehler: {path} existiert nicht", file=sys.stderr)
            sys.exit(1)
        text = path.read_text()
    else:
        parser.print_help()
        sys.exit(1)

    if not text.strip():
        print("Fehler: Leere Eingabe", file=sys.stderr)
        sys.exit(1)

    input_tokens = estimate_tokens(text)

    routing_block = ""
    if args.with_routing:
        routing_path = Path.home() / ".claude" / "data" / "skill-routing-block.md"
        if routing_path.exists():
            routing_block = routing_path.read_text()

    yaml_block = extract_yaml_block(text)
    if yaml_block and ("task:" in yaml_block or "objective:" in yaml_block):
        result = compress_spawned_handoff(text, args.budget)
    else:
        parsed = parse_recycled_context(text)
        result = build_compressed_handoff(parsed, args.budget, routing_block)

    output_tokens = estimate_tokens(result)

    if args.output:
        Path(args.output).write_text(result)
        print(f"Komprimiert: {args.output}", file=sys.stderr)
    else:
        print(result)

    if args.stats or args.output:
        ratio = (1 - output_tokens / input_tokens) * 100 if input_tokens > 0 else 0
        print(
            f"[compress-handoff] {input_tokens} → {output_tokens} Tokens "
            f"({ratio:.0f}% Reduktion, Budget: {args.budget})",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
