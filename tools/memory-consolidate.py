#!/usr/bin/env python3
"""Consolidate scattered MCB workdir memories into the central memory location.

Scans all ./projects/*/memory/*.md files from MCB workdir sessions,
deduplicates against existing central memories, and imports unique ones.
"""

import hashlib
import re
import sys
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
CENTRAL_MEMORY = PROJECTS_DIR / "-home-maetzger" / "memory"
BLOCKLIST_FILE = CENTRAL_MEMORY / ".consolidate-blocklist"
# MCB workdir pattern: -home-maetzger-mcb-workdirs-mc{3,4}-HEXHASH
MCB_PATTERN = re.compile(r"-home-maetzger-mcb-workdirs-mc[34]-[0-9a-f]+")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    return meta, parts[2].strip()


def content_hash(text: str) -> str:
    """Hash normalized content for dedup."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def find_mcb_memories() -> list[tuple[Path, dict, str]]:
    """Find all memory files from MCB workdir sessions."""
    results = []
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        if not MCB_PATTERN.match(project_dir.name):
            continue
        memory_dir = project_dir / "memory"
        if not memory_dir.is_dir():
            continue
        for md_file in memory_dir.glob("*.md"):
            if md_file.name == "MEMORY.md":
                continue
            text = md_file.read_text(errors="replace")
            if not text.strip():
                continue
            meta, body = parse_frontmatter(text)
            results.append((md_file, meta, body))
    return results


def load_blocklist() -> set[str]:
    """Load filenames that should never be re-imported (previously deleted)."""
    if not BLOCKLIST_FILE.exists():
        return set()
    return {
        line.strip() for line in BLOCKLIST_FILE.read_text().splitlines() if line.strip()
    }


def save_blocklist(blocked: set[str]) -> None:
    """Save blocklist of filenames that should not be imported."""
    BLOCKLIST_FILE.write_text("\n".join(sorted(blocked)) + "\n")


def find_central_memories() -> dict[str, set[str]]:
    """Build dedup index from central memory location."""
    index = {"hashes": set(), "names": set()}
    if not CENTRAL_MEMORY.is_dir():
        return index
    for md_file in CENTRAL_MEMORY.glob("*.md"):
        if md_file.name in ("MEMORY.md", ".consolidate-blocklist"):
            continue
        text = md_file.read_text(errors="replace")
        meta, body = parse_frontmatter(text)
        if meta.get("name"):
            index["names"].add(meta["name"].lower())
        index["hashes"].add(content_hash(text))
    return index


def import_memory(src: Path, meta: dict, body: str, dry_run: bool = False) -> str:
    """Copy a memory file to central location. Returns destination path."""
    dest = CENTRAL_MEMORY / src.name
    # Handle name collisions
    if dest.exists():
        counter = 1
        stem = src.stem
        while dest.exists():
            dest = CENTRAL_MEMORY / f"{stem}_{counter}.md"
            counter += 1
    if not dry_run:
        CENTRAL_MEMORY.mkdir(parents=True, exist_ok=True)
        full_text = src.read_text(errors="replace")
        dest.write_text(full_text)
    return str(dest)


def update_central_index(imported: list[tuple[str, dict]]) -> None:
    """Append imported memories to the central MEMORY.md if not zettel-managed."""
    memory_md = CENTRAL_MEMORY / "MEMORY.md"
    if not memory_md.exists():
        return
    existing = memory_md.read_text(errors="replace")
    # If zettel-managed, don't touch the auto-generated index
    if "Auto-generiert" in existing or "zettel" in existing.lower():
        return
    additions = []
    for dest_path, meta in imported:
        name = Path(dest_path).name
        desc = meta.get("description", meta.get("name", "imported memory"))
        additions.append(f"- [{name}]({name}) — {desc}")
    if additions:
        with open(memory_md, "a") as f:
            f.write("\n" + "\n".join(additions) + "\n")


def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    if dry_run:
        print("=== DRY RUN — keine Änderungen ===\n")

    mcb_memories = find_mcb_memories()
    print(f"Gefunden: {len(mcb_memories)} Memory-Dateien in MCB-Workdirs")

    central_index = find_central_memories()
    print(
        f"Zentral vorhanden: {len(central_index['names'])} benannte, "
        f"{len(central_index['hashes'])} gehashte Memories\n"
    )

    imported = []
    skipped_dup = []
    skipped_empty = []
    skipped_blocked = []
    blocklist = load_blocklist()

    for src, meta, body in mcb_memories:
        h = content_hash(src.read_text(errors="replace"))
        name = meta.get("name", "").lower()

        # Blocklist: skip files that were intentionally deleted from central
        if src.name in blocklist:
            skipped_blocked.append((src, "blocklist"))
            continue

        # Skip if base filename already exists in central (prevents _1.md variants
        # when central was edited/merged and hash diverged from workdir copy)
        central_candidate = CENTRAL_MEMORY / src.name
        if central_candidate.exists():
            skipped_dup.append((src, "datei existiert zentral"))
            continue

        # Dedup: skip if content hash matches or name matches
        if h in central_index["hashes"]:
            skipped_dup.append((src, "hash-duplikat"))
            continue
        if name and name in central_index["names"]:
            skipped_dup.append((src, f"name-duplikat: {name}"))
            continue

        # Skip very short / empty body
        if len(body.strip()) < 20:
            skipped_empty.append(src)
            continue

        dest = import_memory(src, meta, body, dry_run=dry_run)
        imported.append((dest, meta))
        central_index["hashes"].add(h)
        if name:
            central_index["names"].add(name)

        label = meta.get("name") or src.stem
        typ = meta.get("type", "?")
        print(f"  ✓ {label} ({typ}) → {Path(dest).name}")
        if verbose:
            print(f"    Quelle: {src}")
            print(f"    Desc: {meta.get('description', '—')}")

    if not dry_run and imported:
        update_central_index(imported)

    print("\n=== Ergebnis ===")
    print(f"Importiert:        {len(imported)}")
    print(f"Duplikate:         {len(skipped_dup)}")
    print(f"Blockiert:         {len(skipped_blocked)}")
    print(f"Zu kurz/leer:      {len(skipped_empty)}")
    print(f"Gesamt verarbeitet: {len(mcb_memories)}")

    if verbose and skipped_dup:
        print("\nÜbersprungene Duplikate:")
        for src, reason in skipped_dup:
            print(f"  ✗ {src.stem} ({reason})")

    if verbose and skipped_blocked:
        print("\nBlockierte (intentionally deleted):")
        for src, reason in skipped_blocked:
            print(f"  ✗ {src.stem}")

    return 0 if imported or not mcb_memories else 1


if __name__ == "__main__":
    sys.exit(main())
