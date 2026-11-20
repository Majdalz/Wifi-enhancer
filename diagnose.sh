#!/usr/bin/env bash
# Wi-Fi diagnostics for macOS and Linux. READ-ONLY: changes no settings.
# Usage:  bash diagnose.sh            (report is also saved to wifi-report-<time>.txt)
# Takes about 1-2 minutes. Uses curl + ping; no installs needed.

set -u
export LC_ALL=C
OS=$(uname -s)
STAMP=$(date +%Y%m%d-%H%M%S)
REPORT="wifi-report-$STAMP.txt"
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t wifidiag)
trap 'rm -rf "$TMP"' EXIT
AP_MAC="b8:fb:b3:7b:51:fa"   # Omada EAP613 from the label

exec > >(tee "$REPORT") 2>&1

hr() { printf '\n==================== %s ====================\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------- interface / gateway ----------
if [ "$OS" = "Darwin" ]; then
  WIFI_IF=$(networksetup -listallhardwareports 2>/dev/null | awk '/Wi-Fi|AirPort/{getline; print $2; exit}')
  DEF_IF=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
  GW=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')
  MYIP=$(ipconfig getifaddr "${DEF_IF:-en0}" 2>/dev/null)
else
  WIFI_IF=$( (iw dev 2>/dev/null | awk '/Interface/{print $2; exit}') || true)
  [ -z "$WIFI_IF" ] && WIFI_IF=$(ls /sys/class/net 2>/dev/null | while read -r i; do [ -d "/sys/class/net/$i/wireless" ] && echo "$i" && break; done)
  DEF_IF=$(ip route 2>/dev/null | awk '/^default/{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
  GW=$(ip route 2>/dev/null | awk '/^default/{print $3; exit}')
  MYIP=$(ip -4 -o addr show dev "$DEF_IF" 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')
fi

hr "SUMMARY OF THIS COMPUTER"
echo "OS:                $OS $(uname -r)"
echo "Wi-Fi interface:   ${WIFI_IF:-not found}"
echo "Default route via: ${DEF_IF:-?}  (if this is not the Wi-Fi interface, you're on Ethernet/VPN)"
echo "Gateway (router):  ${GW:-?}"
echo "This computer IP:  ${MYIP:-?}"

# ---------- Wi-Fi link: band, channel, width, signal, link rate ----------
hr "WI-FI LINK (band / channel / width / signal / link speed)"
if [ "$OS" = "Darwin" ]; then
  system_profiler SPAirPortDataType 2>/dev/null > "$TMP/sp.txt"
  awk '/Current Network Information:/{f=1} /Other Local Wi-Fi Networks:/{f=0} f' "$TMP/sp.txt" | head -25
  echo "(macOS 14.4+ may show the SSID as <redacted> unless Terminal has Location permission - harmless.)"
else
  if have iw && [ -n "$WIFI_IF" ]; then iw dev "$WIFI_IF" link; fi
  have nmcli && nmcli -f IN-USE,SSID,BSSID,CHAN,FREQ,RATE,SIGNAL,BARS,SECURITY dev wifi list 2>/dev/null | awk 'NR==1 || /^\*/'
fi
cat <<'EOF'
How to read it:
  Signal  > -60 dBm good | -60..-70 OK | < -70 dBm weak (causes slowdowns)
  SNR (signal minus noise) > 25 dB is good
  5 GHz at 80 MHz width with 2x2 Wi-Fi 6 should show ~600-1200 Mbps link rate.
  2.4 GHz or < 300 Mbps link rate means you are not getting full speed from the EAP613.
EOF

# ---------- Nearby networks & channel congestion ----------
hr "NEARBY NETWORKS & CHANNEL CONGESTION"
if [ "$OS" = "Darwin" ]; then
  awk '/Other Local Wi-Fi Networks:/{f=1} f' "$TMP/sp.txt" | head -200
  echo
  echo "Networks per channel (busiest first):"
  awk '/Other Local Wi-Fi Networks:/{f=1} f && /Channel:/{print $2}' "$TMP/sp.txt" | sort | uniq -c | sort -rn
else
  if have nmcli; then
    nmcli -f SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY dev wifi list --rescan yes 2>/dev/null > "$TMP/scan.txt"
    cat "$TMP/scan.txt"
    echo; echo "Networks per channel (busiest first):"
    nmcli -t -f CHAN dev wifi list 2>/dev/null | sort | uniq -c | sort -rn
  elif have iw && [ -n "$WIFI_IF" ]; then
    echo "(nmcli not found; 'sudo iw dev $WIFI_IF scan' gives a full scan)"
  fi
fi
cat <<'EOF'
How to read it:
  2.4 GHz: only channels 1, 6, 11 don't overlap. Many neighbours on yours = congestion.
  5 GHz: 36-48 and 149-165 are the common non-DFS blocks. Fewer neighbours = better.
EOF

# ---------- Latency ----------
ping_stats() { # $1 host  $2 count  $3 label
  local out
  out=$(ping -c "$2" -i 0.2 "$1" 2>/dev/null)
  local loss rtt
  loss=$(printf '%s\n' "$out" | grep -o '[0-9.]*% packet loss')
  rtt=$(printf '%s\n' "$out" | awk -F' = ' '/min\/avg\/max/{split($2,a,"/"); printf "min %s / avg %s / max %s / jitter %s ms", a[1],a[2],a[3],a[4]+0}')
  printf '%-28s %s  | loss: %s\n' "$3" "${rtt:-no reply}" "${loss:-?}"
}
hr "LATENCY (idle)"
[ -n "${GW:-}" ] && ping_stats "$GW" 30 "Router/gateway ($GW)"
ping_stats 1.1.1.1 30 "Internet (1.1.1.1)"
ping_stats 8.8.8.8 30 "Internet (8.8.8.8)"
cat <<'EOF'
How to read it:
  Gateway avg should be < 5 ms with jitter < 5 ms. Higher = Wi-Fi problem (signal/interference).
  Internet minus gateway = your ISP's part. Any packet loss is worth fixing.
EOF

# ---------- Speed test (Cloudflare) + loaded latency (bufferbloat) ----------
hr "SPEED TEST (Cloudflare, 4 download / 2 upload streams) + LATENCY UNDER LOAD"
if have curl; then
  PIDS=""
  for i in 1 2 3 4; do
    curl -s -o /dev/null --max-time 15 -w '%{speed_download}\n' \
      "https://speed.cloudflare.com/__down?bytes=100000000" > "$TMP/dl$i" 2>/dev/null &
    PIDS="$PIDS $!"
  done
  sleep 2
  ping_stats 1.1.1.1 40 "Ping DURING download" > "$TMP/loaded_dl"
  wait $PIDS
  DL=$(cat "$TMP"/dl* 2>/dev/null | awk '{s+=$1} END{printf "%.1f", s*8/1000000}')
  PIDS=""
  for i in 1 2; do
    head -c 40000000 /dev/zero | curl -s -o /dev/null --max-time 15 -w '%{speed_upload}\n' \
      --data-binary @- "https://speed.cloudflare.com/__up" > "$TMP/ul$i" 2>/dev/null &
    PIDS="$PIDS $!"
  done
  sleep 2
  ping_stats 1.1.1.1 40 "Ping DURING upload" > "$TMP/loaded_ul"
  wait $PIDS
  UL=$(cat "$TMP"/ul* 2>/dev/null | awk '{s+=$1} END{printf "%.1f", s*8/1000000}')
  [ "$DL" = "0.0" ] && DL="FAILED (could not reach speed.cloudflare.com)"
  [ "$UL" = "0.0" ] && UL="FAILED (could not reach speed.cloudflare.com)"
  echo "Download: $DL Mbps"
  echo "Upload:   $UL Mbps"
  cat "$TMP/loaded_dl" "$TMP/loaded_ul"
  cat <<'EOF'
How to read it:
  Compare with your ISP plan. If avg ping under load is >100 ms above idle, you have
  "bufferbloat" (router queueing) - fixable with SQM/QoS on the router.
EOF
else
  echo "curl not found - skipping."
fi

# ---------- What is using bandwidth on this computer ----------
hr "BANDWIDTH USE ON THIS COMPUTER (5-second sample)"
if [ "$OS" = "Darwin" ]; then
  echo "Per-process traffic over 5 s (bytes in / out):"
  nettop -P -L 2 -s 5 -d -x -J bytes_in,bytes_out 2>/dev/null | awk -F, '
    /^time/{h++; next} h==2 && NF>=3 { t=$3+$4; if(t>0) printf "%12d in %12d out  %s\n", $3, $4, $2 }' \
    | sort -rn | head -15
  echo; echo "Open internet connections per app:"
  lsof -nP -iTCP -sTCP:ESTABLISHED 2>/dev/null | awk 'NR>1{print $1}' | sort | uniq -c | sort -rn | head -15
else
  if have nethogs && [ "$(id -u)" = 0 ]; then
    nethogs -t -c 5 2>/dev/null | tail -20
  else
    R1=$(awk -v i="$DEF_IF:" '$1==i{print $2, $10}' /proc/net/dev); sleep 5
    R2=$(awk -v i="$DEF_IF:" '$1==i{print $2, $10}' /proc/net/dev)
    echo "$R1 $R2" | awk '{printf "Interface traffic: %.2f Mbps down, %.2f Mbps up\n", ($3-$1)*8/5e6, ($4-$2)*8/5e6}'
    echo; echo "Open connections per app (run with sudo + nethogs for per-app Mbps):"
    ss -tunpH state established 2>/dev/null | grep -o 'users:(("[^"]*"' | cut -d'"' -f2 | sort | uniq -c | sort -rn | head -15
  fi
fi
echo "Look for: cloud sync (iCloud/Dropbox/OneDrive/Google Drive), backups, game launchers, torrent clients, updates."

# ---------- Devices on the network ----------
hr "DEVICES ON YOUR NETWORK"
if [ -n "${MYIP:-}" ]; then
  NET=${MYIP%.*}
  echo "Scanning $NET.1-254 (ping sweep, ~10 s)..."
  PIDS=""
  for h in $(seq 1 254); do
    if [ "$OS" = "Darwin" ]; then ping -c1 -t1 "$NET.$h" >/dev/null 2>&1 &
    else ping -c1 -W1 "$NET.$h" >/dev/null 2>&1 & fi
    PIDS="$PIDS $!"
  done
  wait $PIDS 2>/dev/null
  if [ "$OS" = "Darwin" ] || ! have ip; then
    arp -an | awk -v n="$NET." '{ip=$2; gsub(/[()]/,"",ip); if(index(ip,n)==1 && $4!="(incomplete)") print ip, $4}'
  else
    ip neigh show | awk -v n="$NET." 'index($1,n)==1 && /lladdr/ {for(i=1;i<=NF;i++) if($i=="lladdr") print $1, $(i+1)}'
  fi | sort -t. -k4 -n -u > "$TMP/devs"
  printf '%-16s %-18s %-30s %s\n' "IP" "MAC" "NAME" "NOTE"
  while read -r ip mac; do
    # normalise mac to 2-digit lower-case octets
    mac=$(echo "$mac" | awk -F: '{for(i=1;i<=NF;i++){o=tolower($i); if(length(o)==1)o="0"o; printf "%s%s", o, (i<NF?":":"")}}')
    name=""
    have dig && name=$(dig +short +time=1 +tries=1 -x "$ip" @"${GW:-$ip}" 2>/dev/null | head -1)
    [ -z "$name" ] && have dig && name=$(dig +short +time=1 +tries=1 -x "$ip" -p 5353 @224.0.0.251 2>/dev/null | head -1)
    note=""
    [ "$ip" = "${GW:-}" ] && note="router/gateway"
    [ "$ip" = "${MYIP:-}" ] && note="THIS computer"
    [ "$mac" = "$AP_MAC" ] && note="Omada EAP613 access point"
    case "$mac" in b8:fb:b3:*) [ -z "$note" ] && note="TP-Link device";; esac
    c2=$(echo "$mac" | cut -c2)
    case "$c2" in 2|6|a|e) note="${note:+$note; }private/random MAC (usually a phone/tablet/laptop)";; esac
    printf '%-16s %-18s %-30s %s\n' "$ip" "$mac" "${name:--}" "$note"
  done < "$TMP/devs"
  echo; echo "Total devices answering: $(wc -l < "$TMP/devs" | tr -d ' ')"
  echo "(Devices that block ping or are asleep may be missing - the router/Omada client list is authoritative.)"
else
  echo "Could not determine this computer's IP - skipping."
fi

hr "DONE"
echo "Report saved to: $(pwd)/$REPORT"
echo "Nothing was changed on this computer or your network."
