#!/home/maetzger/.claude/tools/.venv/bin/python
"""System-Check Helper — plattformunabhängig (Pi 5 / x86 Server).

Sammelt alle relevanten Systemdaten und gibt sie als JSON auf stdout aus.
Fortschrittsmeldungen gehen auf stderr.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime


def log(msg: str) -> None:
    """Fortschrittsmeldung auf stderr."""
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


def run(cmd: str, timeout: int = 10) -> str:
    """Shell-Befehl ausführen, Fehler abfangen."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, Exception) as e:
        return f"ERROR: {e}"


def collect_cpu() -> dict:
    """CPU-Temperatur, Takt, Governor, Last."""
    log("CPU-Daten sammeln...")

    # Temperatur (Pi: vcgencmd, x86: /sys/class/thermal oder sensors)
    temp = 0.0
    temp_raw = run("vcgencmd measure_temp 2>/dev/null")
    if m := re.search(r"temp=([\d.]+)", temp_raw):
        temp = float(m.group(1))
    else:
        # x86: lese aus /sys/class/thermal
        temp_raw = run("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
        if temp_raw.isdigit():
            temp = int(temp_raw) / 1000.0

    # Takt (Pi: vcgencmd, x86: lscpu)
    clock_raw = run("vcgencmd measure_clock arm 2>/dev/null")
    clock_mhz = 0
    if m := re.search(r"=(\d+)", clock_raw):
        clock_mhz = int(m.group(1)) // 1_000_000
    else:
        freq_raw = run(
            "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null"
        )
        if freq_raw.isdigit():
            clock_mhz = int(freq_raw) // 1000

    # Governor
    governor = run("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")

    # Load Average
    load_raw = run("cat /proc/loadavg")
    load_parts = load_raw.split()[:3] if not load_raw.startswith("ERROR") else []
    load_avg = {
        "1min": float(load_parts[0]) if len(load_parts) > 0 else 0,
        "5min": float(load_parts[1]) if len(load_parts) > 1 else 0,
        "15min": float(load_parts[2]) if len(load_parts) > 2 else 0,
    }

    # CPU-Kerne
    cores = os.cpu_count() or 4

    return {
        "temp_c": temp,
        "clock_mhz": clock_mhz,
        "governor": governor,
        "load_avg": load_avg,
        "cores": cores,
    }


def collect_ram() -> dict:
    """RAM und Swap Nutzung."""
    log("RAM-Daten sammeln...")

    meminfo = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    meminfo[key] = int(parts[1])  # kB
    except Exception:
        pass

    total_mb = meminfo.get("MemTotal", 0) / 1024
    available_mb = meminfo.get("MemAvailable", 0) / 1024
    used_mb = total_mb - available_mb
    used_pct = (used_mb / total_mb * 100) if total_mb > 0 else 0

    swap_total_mb = meminfo.get("SwapTotal", 0) / 1024
    swap_free_mb = meminfo.get("SwapFree", 0) / 1024
    swap_used_mb = swap_total_mb - swap_free_mb
    swap_pct = (swap_used_mb / swap_total_mb * 100) if swap_total_mb > 0 else 0

    return {
        "total_mb": round(total_mb),
        "used_mb": round(used_mb),
        "available_mb": round(available_mb),
        "used_pct": round(used_pct, 1),
        "swap_total_mb": round(swap_total_mb),
        "swap_used_mb": round(swap_used_mb),
        "swap_pct": round(swap_pct, 1),
    }


def collect_disk() -> dict:
    """NVMe-Belegung und größte Verzeichnisse."""
    log("Disk-Daten sammeln...")

    usage = shutil.disk_usage("/")
    total_gb = usage.total / (1024**3)
    used_gb = usage.used / (1024**3)
    free_gb = usage.free / (1024**3)
    used_pct = (usage.used / usage.total * 100) if usage.total > 0 else 0

    # Größte Verzeichnisse in /home/maetzger (top 10)
    du_raw = run(
        "du -d1 -BM /home/maetzger 2>/dev/null | sort -rn | head -11", timeout=30
    )
    top_dirs = []
    for line in du_raw.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            size_str = parts[0].strip().rstrip("M")
            path = parts[1].strip()
            if path == "/home/maetzger":
                continue
            try:
                top_dirs.append({"path": path, "size_mb": int(size_str)})
            except ValueError:
                pass

    return {
        "total_gb": round(total_gb, 1),
        "used_gb": round(used_gb, 1),
        "free_gb": round(free_gb, 1),
        "used_pct": round(used_pct, 1),
        "top_dirs": top_dirs[:10],
    }


def collect_overclocking() -> dict:
    """Overclocking/Throttling-Status (Pi) oder CPU-Frequenz-Info (x86)."""
    log("CPU-Frequenz-Status prüfen...")

    throttled_raw = run("vcgencmd get_throttled 2>/dev/null")
    throttled_hex = "0x0"
    if m := re.search(r"throttled=(0x[\da-fA-F]+)", throttled_raw):
        throttled_hex = m.group(1)

    throttled_val = int(throttled_hex, 16)

    flags = []
    flag_map = {
        0: "Aktuell unterspannt",
        1: "ARM-Frequenz begrenzt",
        2: "Aktuell gedrosselt",
        3: "Soft-Temperatur-Limit aktiv",
        16: "Unterspannung aufgetreten",
        17: "ARM-Frequenz wurde begrenzt",
        18: "Drosselung aufgetreten",
        19: "Soft-Temperatur-Limit aufgetreten",
    }
    for bit, desc in flag_map.items():
        if throttled_val & (1 << bit):
            flags.append(desc)

    oc_config = {}
    # Pi: config.txt
    try:
        with open("/boot/firmware/config.txt") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                for key in ("arm_freq", "over_voltage", "gpu_freq", "arm_boost"):
                    if line.startswith(key):
                        oc_config[key] = line.split("=", 1)[1].strip()
    except Exception:
        # x86: kein config.txt, Frequenz-Scaling Info
        max_freq = run(
            "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null"
        )
        if max_freq.isdigit():
            oc_config["max_freq_mhz"] = str(int(max_freq) // 1000)

    return {
        "throttled_hex": throttled_hex,
        "throttled_value": throttled_val,
        "throttled_flags": flags,
        "is_throttled": throttled_val != 0,
        "config": oc_config,
    }


def collect_services() -> list:
    """Status der relevanten systemd-Services."""
    log("Service-Status prüfen...")

    service_names = [
        "mission-control-v3",
        "mission-control-v2",
        "mission-control-v2-https",
        "filebrowser",
        "claude-proxy",
        "earlyoom",
        "ssh",
    ]

    services = []
    for name in service_names:
        state = run(f"systemctl is-active {name}.service 2>/dev/null")
        enabled = run(f"systemctl is-enabled {name}.service 2>/dev/null")
        # Laufzeit ermitteln
        uptime_raw = run(
            f"systemctl show {name}.service --property=ActiveEnterTimestamp "
            f"--value 2>/dev/null"
        )
        services.append(
            {
                "name": name,
                "active": state == "active",
                "state": state,
                "enabled": enabled,
                "started": uptime_raw if not uptime_raw.startswith("ERROR") else "",
            }
        )

    return services


def collect_network() -> dict:
    """IP, Hostname, UFW-Status."""
    log("Netzwerk-Daten sammeln...")

    hostname = run("hostname")
    # Primäre IP
    ip_raw = run("hostname -I")
    ips = ip_raw.split() if not ip_raw.startswith("ERROR") else []

    # UFW Status
    ufw_raw = run("sudo ufw status numbered 2>/dev/null")

    # Offene Ports extrahieren
    ports = []
    for line in ufw_raw.splitlines():
        # Zeilen mit Port-Nummern finden
        if m := re.search(r"(\d+)/(tcp|udp)\s+ALLOW", line):
            port = m.group(1)
            proto = m.group(2)
            comment = ""
            if "#" in line:
                comment = line.split("#", 1)[1].strip()
            elif "  " in line:
                # Kommentar am Ende
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) > 3:
                    comment = parts[-1]
            ports.append({"port": int(port), "proto": proto, "comment": comment})

    return {
        "hostname": hostname,
        "ips": ips,
        "ufw_status": "active" if "Status: active" in ufw_raw else "inactive",
        "open_ports": ports,
    }


def collect_python() -> dict:
    """Python- und uv-Version, installierte Tools."""
    log("Python-Umgebung prüfen...")

    python_version = run("python3 --version")
    uv_version = run("/home/maetzger/.local/bin/uv --version 2>/dev/null")

    # Globale uv-Tools
    uv_tools = run("/home/maetzger/.local/bin/uv tool list 2>/dev/null")
    tools = []
    if not uv_tools.startswith("ERROR"):
        for line in uv_tools.splitlines():
            line = line.strip()
            if line and not line.startswith("-") and not line.startswith(" "):
                tools.append(line)

    return {
        "python_version": python_version,
        "uv_version": uv_version,
        "tools": tools,
    }


def collect_uptime() -> dict:
    """Systemlaufzeit und Boot-Zeitpunkt."""
    log("Uptime ermitteln...")

    uptime_raw = run("uptime -p")
    boot_time = run("uptime -s")

    # /proc/uptime für Sekunden
    try:
        with open("/proc/uptime") as f:
            uptime_secs = float(f.read().split()[0])
    except Exception:
        uptime_secs = 0

    return {
        "pretty": uptime_raw,
        "boot_time": boot_time,
        "seconds": round(uptime_secs),
    }


def collect_updates() -> dict:
    """Verfügbare apt-Updates."""
    log("Verfügbare Updates prüfen...")

    updates_raw = run("apt list --upgradable 2>/dev/null", timeout=30)
    lines = [
        line
        for line in updates_raw.splitlines()
        if line and not line.startswith("Listing") and not line.startswith("WARNING")
    ]

    return {
        "count": len(lines),
        "packages": lines[:20],  # Nur erste 20 anzeigen
    }


def main() -> None:
    log("System-Check startet...")
    start = datetime.now()

    data = {
        "timestamp": start.isoformat(),
        "hostname": run("hostname"),
        "cpu": collect_cpu(),
        "ram": collect_ram(),
        "disk": collect_disk(),
        "overclocking": collect_overclocking(),
        "services": collect_services(),
        "network": collect_network(),
        "python": collect_python(),
        "uptime": collect_uptime(),
        "updates": collect_updates(),
    }

    elapsed = (datetime.now() - start).total_seconds()
    data["collection_time_s"] = round(elapsed, 2)
    log(f"Fertig in {elapsed:.1f}s")

    # JSON auf stdout
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
