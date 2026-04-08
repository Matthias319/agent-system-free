#!/usr/bin/env python3
"""Deploy files to Strato subdomains via SFTP.

Usage:
    deploy.py upload <target> <local_path> [--remote-dir <dir>]
    deploy.py list <target> [--remote-dir <dir>]
    deploy.py targets

Targets: quickshare, project, event
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.home() / ".claude" / ".env")


@dataclass
class Target:
    name: str
    user: str
    password: str
    host: str
    port: str
    base_url: str


def get_target(name: str) -> Target:
    prefix = f"STRATO_{name.upper()}"
    user = os.getenv(f"{prefix}_USER")
    password = os.getenv(f"{prefix}_PASS")
    host = os.getenv("STRATO_SFTP_HOST")
    port = os.getenv("STRATO_SFTP_PORT", "22")
    base_url = os.getenv(f"{prefix}_URL", "")

    if not user or not password or not host:
        print(json.dumps({"error": f"Missing credentials for target '{name}'"}))
        sys.exit(1)

    return Target(
        name=name, user=user, password=password, host=host, port=port, base_url=base_url
    )


VALID_TARGETS = ["quickshare", "project", "event"]


def auto_detect_target(local_path: str) -> str:
    """Guess target from file path or name."""
    p = local_path.lower()
    if "event" in p or "einladung" in p or "anmeldung" in p:
        return "event"
    if "project" in p or "kanzlei" in p or "relaunch" in p:
        return "project"
    return "quickshare"


def sftp_upload(target: Target, local_path: str, remote_dir: str = "") -> dict:
    """Upload file or directory via SFTP."""
    local = Path(local_path)
    if not local.exists():
        return {"error": f"Local path not found: {local_path}"}

    commands = []
    if remote_dir:
        commands.append(f"mkdir {remote_dir}")
        commands.append(f"cd {remote_dir}")

    if local.is_dir():
        for f in sorted(local.rglob("*")):
            if f.is_file():
                rel = f.relative_to(local)
                if rel.parent != Path("."):
                    commands.append(f"mkdir {rel.parent}")
                commands.append(f"put {f} {rel}")
    else:
        commands.append(f"put {local}")

    batch = "\n".join(commands)

    result = subprocess.run(
        [
            "sshpass",
            "-p",
            target.password,
            "sftp",
            "-P",
            target.port,
            "-oBatchMode=no",
            "-oStrictHostKeyChecking=no",
            f"{target.user}@{target.host}",
        ],
        input=batch,
        capture_output=True,
        text=True,
        timeout=60,
    )

    filename = local.name
    if remote_dir:
        url = f"{target.base_url.rstrip('/')}/{remote_dir.strip('/')}/{filename}"
    else:
        url = f"{target.base_url.rstrip('/')}/{filename}"

    if local.is_dir():
        url = (
            f"{target.base_url.rstrip('/')}/{remote_dir.strip('/')}/"
            if remote_dir
            else f"{target.base_url.rstrip('/')}/"
        )

    success = result.returncode == 0 or "Uploading" in result.stderr

    return {
        "success": success,
        "target": target.name,
        "local_path": str(local),
        "url": url,
        "remote_dir": remote_dir or "/",
        "files_uploaded": len([c for c in commands if c.startswith("put ")]),
        "stderr": result.stderr[-500:] if not success else "",
    }


def sftp_list(target: Target, remote_dir: str = "") -> dict:
    """List files on remote."""
    commands = []
    if remote_dir:
        commands.append(f"cd {remote_dir}")
    commands.append("ls -la")

    batch = "\n".join(commands)

    result = subprocess.run(
        [
            "sshpass",
            "-p",
            target.password,
            "sftp",
            "-P",
            target.port,
            "-oBatchMode=no",
            "-oStrictHostKeyChecking=no",
            f"{target.user}@{target.host}",
        ],
        input=batch,
        capture_output=True,
        text=True,
        timeout=30,
    )

    lines = [
        l.strip()
        for l in result.stdout.splitlines()
        if l.strip() and not l.startswith("sftp>")
    ]
    return {
        "target": target.name,
        "remote_dir": remote_dir or "/",
        "files": lines,
        "base_url": target.base_url,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: deploy.py <upload|list|targets> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "targets":
        targets = []
        for name in VALID_TARGETS:
            url = os.getenv(f"STRATO_{name.upper()}_URL", "")
            targets.append({"name": name, "url": url})
        print(json.dumps({"targets": targets}, indent=2))
        return

    if cmd == "upload":
        if len(sys.argv) < 4:
            print(
                json.dumps(
                    {
                        "error": "Usage: deploy.py upload <target|auto> <local_path> [--remote-dir <dir>]"
                    }
                )
            )
            sys.exit(1)

        target_name = sys.argv[2]
        local_path = sys.argv[3]
        remote_dir = ""

        if "--remote-dir" in sys.argv:
            idx = sys.argv.index("--remote-dir")
            if idx + 1 < len(sys.argv):
                remote_dir = sys.argv[idx + 1]

        if target_name == "auto":
            target_name = auto_detect_target(local_path)

        if target_name not in VALID_TARGETS:
            print(
                json.dumps(
                    {"error": f"Invalid target '{target_name}'. Valid: {VALID_TARGETS}"}
                )
            )
            sys.exit(1)

        target = get_target(target_name)
        result = sftp_upload(target, local_path, remote_dir)
        print(json.dumps(result, indent=2))

    elif cmd == "list":
        if len(sys.argv) < 3:
            print(
                json.dumps(
                    {"error": "Usage: deploy.py list <target> [--remote-dir <dir>]"}
                )
            )
            sys.exit(1)

        target_name = sys.argv[2]
        remote_dir = ""

        if "--remote-dir" in sys.argv:
            idx = sys.argv.index("--remote-dir")
            if idx + 1 < len(sys.argv):
                remote_dir = sys.argv[idx + 1]

        if target_name not in VALID_TARGETS:
            print(
                json.dumps(
                    {"error": f"Invalid target '{target_name}'. Valid: {VALID_TARGETS}"}
                )
            )
            sys.exit(1)

        target = get_target(target_name)
        result = sftp_list(target, remote_dir)
        print(json.dumps(result, indent=2))

    else:
        print(
            json.dumps(
                {"error": f"Unknown command '{cmd}'. Use: upload, list, targets"}
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
