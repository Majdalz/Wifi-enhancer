"""Turn a list of scanned networks into channel congestion data and advice."""

from __future__ import annotations

from typing import Dict, List, Optional

from .scanner import Network

CHANNELS_24 = list(range(1, 14))
NON_OVERLAP_24 = [1, 6, 11]
# Common non-DFS 5 GHz channels (usable by nearly every router/client).
CHANNELS_5 = [36, 40, 44, 48, 149, 153, 157, 161, 165]


def _weight(net: Network) -> float:
    # Strong neighbours interfere far more than faint ones.
    return (net.signal / 100.0) ** 2


def congestion_24(networks: List[Network]) -> Dict[int, float]:
    """20 MHz 2.4 GHz channels bleed into neighbours up to 4 channels away."""
    scores = {c: 0.0 for c in CHANNELS_24}
    for n in networks:
        if n.band != "2.4 GHz":
            continue
        for c in CHANNELS_24:
            overlap = max(0.0, 1 - abs(c - n.channel) / 5)
            scores[c] += _weight(n) * overlap
    return {c: round(v, 3) for c, v in scores.items()}


def congestion_5(networks: List[Network]) -> Dict[int, float]:
    chans = sorted(set(CHANNELS_5) | {n.channel for n in networks if n.band == "5 GHz"})
    scores = {c: 0.0 for c in chans}
    for n in networks:
        if n.band == "5 GHz":
            scores[n.channel] += _weight(n)
    return {c: round(v, 3) for c, v in scores.items()}


def best_channel(scores: Dict[int, float], candidates: List[int]) -> Optional[int]:
    cands = [c for c in candidates if c in scores]
    return min(cands, key=lambda c: (scores[c], c)) if cands else None


def signal_quality(signal: int) -> str:
    if signal >= 80:
        return "Excellent"
    if signal >= 60:
        return "Good"
    if signal >= 40:
        return "Fair"
    return "Weak"


def _security_level(sec: str) -> str:
    s = sec.upper()
    if s in ("", "OPEN", "NONE", "--"):
        return "open"
    if "WEP" in s:
        return "wep"
    if "WPA3" in s or "SAE" in s:
        return "strong"
    if "WPA2" in s or "802.1X" in s or "RSN" in s:
        return "good"
    if "WPA" in s:
        return "weak"
    return "good"


def analyze(networks: List[Network]) -> dict:
    c24 = congestion_24(networks)
    c5 = congestion_5(networks)
    best24 = best_channel(c24, NON_OVERLAP_24)
    best5 = best_channel(c5, CHANNELS_5)
    current = next((n for n in networks if n.connected), None)

    tips: List[dict] = []

    def tip(level: str, title: str, detail: str):
        tips.append({"level": level, "title": title, "detail": detail})

    if current is None:
        tip("info", "Not connected", "Connect to a network to get personalised advice.")
    else:
        q = signal_quality(current.signal)
        if q == "Weak":
            tip("bad", "Weak signal",
                f"{current.ssid} is at {current.signal}% ({current.dbm} dBm). Move closer to the "
                "router, raise it off the floor, or add a mesh node / extender.")
        elif q == "Fair":
            tip("warn", "Signal could be better",
                f"{current.signal}% is usable but drops under load. Clear obstructions "
                "(walls, metal, aquariums, microwaves) between you and the router.")

        if current.band == "2.4 GHz":
            same_ssid_5 = [n for n in networks if n.band != "2.4 GHz" and
                           (n.ssid == current.ssid or n.ssid.startswith(current.ssid))]
            if same_ssid_5:
                tip("warn", "Switch to 5 GHz",
                    f"\"{same_ssid_5[0].ssid}\" is broadcasting on {same_ssid_5[0].band} "
                    f"at {same_ssid_5[0].signal}%. It's faster and less crowded.")
            mine = c24.get(current.channel, 0) - _weight(current)
            if best24 is not None and best24 != current.channel:
                alt = c24[best24]
                if alt < mine * 0.7:
                    tip("warn", f"Change router to channel {best24}",
                        f"Channel {current.channel} is crowded (load {mine:.2f}); channel "
                        f"{best24} has load {alt:.2f}. Change it in your router's wireless settings.")
            if current.channel not in NON_OVERLAP_24:
                tip("warn", "Use channel 1, 6 or 11",
                    f"Channel {current.channel} overlaps two clean channels. In 2.4 GHz only "
                    "1, 6 and 11 don't interfere with each other.")
        elif current.band == "5 GHz" and best5 is not None and best5 != current.channel:
            mine = c5.get(current.channel, 0) - _weight(current)
            if mine > 0.15 and c5[best5] < mine * 0.5:
                tip("warn", f"Consider 5 GHz channel {best5}",
                    f"{current.channel} is shared with other strong networks; {best5} is quieter.")

        lvl = _security_level(current.security)
        if lvl == "open":
            tip("bad", "Unencrypted network",
                "Anyone nearby can see your traffic. Use a VPN or switch to a WPA2/WPA3 network.")
        elif lvl in ("wep", "weak"):
            tip("bad", "Outdated security",
                f"{current.security} can be cracked in minutes. Set the router to WPA2-AES or WPA3.")
        elif lvl == "good":
            tip("info", "Enable WPA3 if available",
                "WPA3 (or WPA2/WPA3 mixed mode) protects against offline password guessing.")

    crowd = sum(1 for n in networks if n.band == "2.4 GHz" and n.signal >= 40)
    if crowd >= 6:
        tip("info", "Busy 2.4 GHz neighbourhood",
            f"{crowd} strong 2.4 GHz networks around you. Prefer 5 GHz for laptops/phones and "
            "keep 2.4 GHz for smart-home devices.")

    if not any(t["level"] in ("bad", "warn") for t in tips) and current is not None:
        tip("good", "Looking good", "Your connection has no obvious problems.")

    bands = {}
    for n in networks:
        bands[n.band] = bands.get(n.band, 0) + 1

    return {
        "current": current.to_dict() if current else None,
        "quality": signal_quality(current.signal) if current else None,
        "congestion": {"2.4 GHz": c24, "5 GHz": c5},
        "best_channel": {"2.4 GHz": best24, "5 GHz": best5},
        "band_counts": bands,
        "tips": tips,
    }
