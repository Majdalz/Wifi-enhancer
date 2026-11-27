"""Cross-platform Wi-Fi scanning.

Uses the tools that ship with each OS:
  * Linux   -> nmcli (NetworkManager)
  * Windows -> netsh wlan
  * macOS   -> system_profiler SPAirPortDataType
Falls back to simulated demo data when no scanner is available.
"""

from __future__ import annotations

import json
import platform
import random
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import List, Optional


@dataclass
class Network:
    ssid: str
    bssid: str
    signal: int  # 0-100 %
    channel: int
    frequency: int  # MHz
    security: str
    connected: bool = False

    @property
    def band(self) -> str:
        if self.frequency >= 5925:
            return "6 GHz"
        if self.frequency >= 4900:
            return "5 GHz"
        return "2.4 GHz"

    @property
    def dbm(self) -> int:
        return percent_to_dbm(self.signal)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["band"] = self.band
        d["dbm"] = self.dbm
        return d


def percent_to_dbm(pct: int) -> int:
    return int(round(pct / 2 - 100))


def dbm_to_percent(dbm: float) -> int:
    return max(0, min(100, int(round(2 * (dbm + 100)))))


def channel_to_freq(channel: int) -> int:
    if 1 <= channel <= 13:
        return 2407 + 5 * channel
    if channel == 14:
        return 2484
    return 5000 + 5 * channel


def freq_to_channel(freq: int) -> int:
    if freq == 2484:
        return 14
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if 5955 <= freq <= 7115:
        return (freq - 5950) // 5
    return (freq - 5000) // 5


def _run(cmd: List[str], timeout: int = 15) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"{cmd[0]} exited with {out.returncode}")
    return out.stdout


# ---------------------------------------------------------------- Linux

def _split_nmcli(line: str) -> List[str]:
    """Split an nmcli terse line on unescaped colons."""
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def parse_nmcli(output: str) -> List[Network]:
    nets = []
    for line in output.splitlines():
        if not line.strip():
            continue
        f = _split_nmcli(line)
        if len(f) < 7:
            continue
        in_use, ssid, bssid, chan, freq, signal, security = f[:7]
        try:
            channel = int(chan)
            frequency = int(re.sub(r"\D", "", freq) or channel_to_freq(channel))
            sig = int(signal)
        except ValueError:
            continue
        nets.append(Network(
            ssid=ssid or "(hidden)",
            bssid=bssid.upper(),
            signal=sig,
            channel=channel,
            frequency=frequency,
            security=security.strip() or "Open",
            connected=in_use.strip() == "*",
        ))
    return nets


def scan_linux() -> List[Network]:
    out = _run(["nmcli", "-t", "-f", "IN-USE,SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY",
                "device", "wifi", "list", "--rescan", "auto"])
    return parse_nmcli(out)


# -------------------------------------------------------------- Windows

def parse_netsh(networks_out: str, interfaces_out: str = "") -> List[Network]:
    connected_bssid = None
    m = re.search(r"^\s*BSSID\s*:\s*([0-9a-fA-F:]{17})", interfaces_out, re.M)
    if m and re.search(r"^\s*State\s*:\s*connected", interfaces_out, re.M | re.I):
        connected_bssid = m.group(1).upper()

    nets: List[Network] = []
    ssid, security = "", "Open"
    cur: Optional[dict] = None

    def flush():
        if cur and "signal" in cur and "channel" in cur:
            nets.append(Network(
                ssid=ssid or "(hidden)",
                bssid=cur["bssid"],
                signal=cur["signal"],
                channel=cur["channel"],
                frequency=channel_to_freq(cur["channel"]) if not cur.get("band6") else 5950 + 5 * cur["channel"],
                security=security,
                connected=cur["bssid"] == connected_bssid,
            ))

    for raw in networks_out.splitlines():
        line = raw.strip()
        if m := re.match(r"^SSID \d+\s*:\s*(.*)$", line):
            flush()
            cur = None
            ssid, security = m.group(1).strip(), "Open"
        elif m := re.match(r"^Authentication\s*:\s*(.*)$", line):
            auth = m.group(1).strip()
            security = "Open" if auth.lower() == "open" else auth
        elif m := re.match(r"^BSSID \d+\s*:\s*(.*)$", line):
            flush()
            cur = {"bssid": m.group(1).strip().upper()}
        elif cur is not None and (m := re.match(r"^Signal\s*:\s*(\d+)%", line)):
            cur["signal"] = int(m.group(1))
        elif cur is not None and (m := re.match(r"^Channel\s*:\s*(\d+)", line)):
            cur["channel"] = int(m.group(1))
        elif cur is not None and (m := re.match(r"^Band\s*:\s*6", line)):
            cur["band6"] = True
    flush()
    return nets


def scan_windows() -> List[Network]:
    nets_out = _run(["netsh", "wlan", "show", "networks", "mode=bssid"])
    try:
        iface_out = _run(["netsh", "wlan", "show", "interfaces"])
    except Exception:
        iface_out = ""
    return parse_netsh(nets_out, iface_out)


# ---------------------------------------------------------------- macOS

def _mac_entry(entry: dict, connected: bool) -> Optional[Network]:
    chan_txt = str(entry.get("spairport_network_channel", ""))
    m = re.match(r"(\d+)(?:\s*\((\d)GHz)?", chan_txt)
    if not m:
        return None
    channel = int(m.group(1))
    band = m.group(2)
    if band == "6":
        freq = 5950 + 5 * channel
    else:
        freq = channel_to_freq(channel)
    sn = str(entry.get("spairport_signal_noise", ""))
    dm = re.match(r"(-?\d+)\s*dBm", sn)
    signal = dbm_to_percent(int(dm.group(1))) if dm else 0
    sec = str(entry.get("spairport_security_mode", "Open"))
    sec = sec.replace("spairport_security_mode_", "").replace("_", " ").upper()
    return Network(
        ssid=entry.get("_name", "(hidden)"),
        bssid=str(entry.get("spairport_network_bssid", "")).upper() or "—",
        signal=signal,
        channel=channel,
        frequency=freq,
        security="Open" if sec in ("NONE", "") else sec,
        connected=connected,
    )


def parse_system_profiler(output: str) -> List[Network]:
    data = json.loads(output)
    nets: List[Network] = []
    for item in data.get("SPAirPortDataType", []):
        for iface in item.get("spairport_airport_interfaces", []):
            cur = iface.get("spairport_current_network_information")
            if isinstance(cur, dict) and (n := _mac_entry(cur, True)):
                nets.append(n)
            for e in iface.get("spairport_airport_other_local_wireless_networks", []):
                if n := _mac_entry(e, False):
                    nets.append(n)
    return nets


def scan_macos() -> List[Network]:
    return parse_system_profiler(_run(["system_profiler", "SPAirPortDataType", "-json"], timeout=30))


# ----------------------------------------------------------------- Demo

DEMO_SSIDS = [
    ("HomeNet", "WPA2 WPA3"), ("HomeNet-5G", "WPA2 WPA3"), ("Neighbor_2.4", "WPA2"),
    ("TP-Link_8A21", "WPA2"), ("CoffeeShop Guest", "Open"), ("NETGEAR42", "WPA2"),
    ("Apartment 3B", "WPA2"), ("FiberBox-77", "WPA3"), ("PrinterSetup", "WPA"),
    ("OldRouter", "WEP"), ("Office-Mesh", "WPA2 802.1X"), ("SmartTV_Direct", "WPA2"),
]


def demo_networks(seed: Optional[int] = None) -> List[Network]:
    # Layout (channels, BSSIDs, base signal) is fixed; only signal drifts per scan.
    rnd = random.Random(42)
    noise = random.Random(seed)
    chans24 = [1, 1, 6, 6, 6, 11, 3, 11, 6, 9]
    chans5 = [36, 44, 149, 157, 40]
    nets = []
    for i, (ssid, sec) in enumerate(DEMO_SSIDS):
        is5 = "5G" in ssid or ssid in ("FiberBox-77", "Office-Mesh")
        ch = rnd.choice(chans5) if is5 else rnd.choice(chans24)
        if ssid == "HomeNet":
            ch = 6
        if ssid == "HomeNet-5G":
            ch = 36
        base = 78 if ssid.startswith("HomeNet") else rnd.randint(20, 70)
        nets.append(Network(
            ssid=ssid,
            bssid=":".join(f"{rnd.randint(0, 255):02X}" for _ in range(6)),
            signal=max(5, min(100, base + noise.randint(-4, 4))),
            channel=ch,
            frequency=channel_to_freq(ch),
            security=sec,
            connected=(ssid == "HomeNet"),
        ))
    return nets


# ------------------------------------------------------------ Dispatcher

def scan(force_demo: bool = False) -> dict:
    """Return {"networks": [...], "source": str, "demo": bool, "error": str|None}."""
    if force_demo:
        return {"networks": demo_networks(), "source": "demo", "demo": True, "error": None}

    system = platform.system()
    scanner, tool = None, None
    if system == "Linux" and shutil.which("nmcli"):
        scanner, tool = scan_linux, "nmcli"
    elif system == "Windows":
        scanner, tool = scan_windows, "netsh"
    elif system == "Darwin":
        scanner, tool = scan_macos, "system_profiler"

    error = None
    if scanner:
        try:
            nets = scanner()
            if nets:
                return {"networks": nets, "source": tool, "demo": False, "error": None}
            error = "No Wi-Fi networks found (is Wi-Fi turned on?)"
        except Exception as exc:  # noqa: BLE001
            error = f"{tool} failed: {exc}"
    else:
        error = f"No supported Wi-Fi scanner found on {system}"

    return {"networks": demo_networks(), "source": "demo", "demo": True, "error": error}
