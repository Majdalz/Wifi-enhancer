# Wifi-enhancer
A project for enhancing and improving Wi-Fi connectivity and management.

## Web dashboard

A local web GUI that scans nearby Wi-Fi networks and tells you how to improve your connection.

- **Current connection**: signal gauge, dBm, band, channel and security
- **Recommendations**: weak signal, switching to 5 GHz, the least-congested channel to set on your router, and insecure (Open/WEP/WPA) networks
- **Channel congestion chart**: for 2.4 GHz and 5 GHz, accounting for overlap between 2.4 GHz channels
- **Latency test**: ping, jitter and packet loss to Cloudflare, Google or Quad9
- **Nearby networks table**: sortable and filterable
- Light and dark themes, auto-refresh, works on phones

There are no dependencies beyond Python 3.8+. It uses the OS's own Wi-Fi tools:

| OS      | Scanner used                              |
|---------|-------------------------------------------|
| Linux   | `nmcli` (NetworkManager)                  |
| Windows | `netsh wlan`                              |
| macOS   | `system_profiler SPAirPortDataType`       |

If no scanner or Wi-Fi adapter is found, the dashboard shows simulated demo data with a notice.

### Install & run

```bash
git clone https://github.com/majdalz/wifi-enhancer.git
cd wifi-enhancer

# Option A: run directly
python -m wifi_enhancer

# Option B: install the `wifi-enhancer` command
pip install .
wifi-enhancer
```

Your browser opens at <http://localhost:8765/>.

Options:

```
--port 8765      port to listen on
--host 127.0.0.1 bind address (use 0.0.0.0 to open it from your phone on the same LAN)
--demo           always use simulated networks
--no-browser     don't open a browser tab automatically
```

On macOS 14+ the network names may show as `<redacted>` unless your terminal has Location Services permission.

### Tests

```bash
python -m unittest
```
