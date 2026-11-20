# Wifi-enhancer

Read-only Wi-Fi diagnostics. **Nothing is changed** on your computer or network.

| | macOS / Linux | Windows |
|---|---|---|
| Run | `bash diagnose.sh` | `powershell -ExecutionPolicy Bypass -File .\diagnose.ps1` |

Each run takes 1–2 minutes and saves `wifi-report-<time>.txt` with:

1. Wi-Fi link: band, channel, width, signal/noise, link rate
2. Nearby networks and how many share each channel
3. Idle latency to the router and to the internet (separates Wi-Fi from ISP problems)
4. Speed test (Cloudflare, multi-stream) plus latency under load (bufferbloat)
5. Which apps on this computer are using the network
6. Every device that answers on your subnet (IP, MAC, name, random-MAC/AP flags)

Notes
- macOS 14.4+: SSIDs may show `<redacted>` without Location permission for Terminal — harmless.
- Windows 11 24H2+: turn on *Settings → Privacy → Location → Let desktop apps access your location*, or the network scan comes back empty.
- Run it once close to the access point and once where Wi-Fi is slow, then compare.
