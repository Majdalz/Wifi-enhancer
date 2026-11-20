# Wi-Fi diagnostics for Windows 10/11. READ-ONLY: changes no settings.
# Usage (in PowerShell):  powershell -ExecutionPolicy Bypass -File .\diagnose.ps1
# Takes about 1-2 minutes. Report is also saved to wifi-report-<time>.txt
# Windows 11 24H2+: if Wi-Fi details are blank, turn on Settings > Privacy > Location
# ("Let desktop apps access your location") - netsh needs it to show networks.

$ErrorActionPreference = 'SilentlyContinue'
$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = Join-Path (Get-Location) "wifi-report-$stamp.txt"
Start-Transcript -Path $report | Out-Null
$ApMac = 'b8-fb-b3-7b-51-fa'   # Omada EAP613 from the label

function HR($t) { "`n==================== $t ====================" }

function Ping-Stats($target, $count, $label) {
    $p = New-Object System.Net.NetworkInformation.Ping
    $times = @(); $lost = 0
    for ($i = 0; $i -lt $count; $i++) {
        $r = $p.Send($target, 1000)
        if ($r.Status -eq 'Success') { $times += [double]$r.RoundtripTime } else { $lost++ }
        Start-Sleep -Milliseconds 200
    }
    $lossPct = [math]::Round(100 * $lost / $count, 1)
    if ($times.Count -eq 0) { return ('{0,-28} no reply | loss: {1}%' -f $label, $lossPct) }
    $avg = ($times | Measure-Object -Average).Average
    $jit = 0; for ($i = 1; $i -lt $times.Count; $i++) { $jit += [math]::Abs($times[$i] - $times[$i-1]) }
    if ($times.Count -gt 1) { $jit = $jit / ($times.Count - 1) }
    '{0,-28} min {1} / avg {2:N1} / max {3} / jitter {4:N1} ms | loss: {5}%' -f $label,
        ($times | Measure-Object -Minimum).Minimum, $avg, ($times | Measure-Object -Maximum).Maximum, $jit, $lossPct
}

# ---------- basics ----------
$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1
$gw    = $route.NextHop
$ifIdx = $route.InterfaceIndex
$myIp  = (Get-NetIPAddress -InterfaceIndex $ifIdx -AddressFamily IPv4 | Select-Object -First 1).IPAddress
$adapter = Get-NetAdapter -InterfaceIndex $ifIdx

HR 'SUMMARY OF THIS COMPUTER'
"Default adapter:  $($adapter.Name) - $($adapter.InterfaceDescription)"
"Adapter speed:    $($adapter.LinkSpeed)"
"Gateway (router): $gw"
"This computer IP: $myIp"

# ---------- Wi-Fi link ----------
HR 'WI-FI LINK (band / channel / signal / link speed)'
netsh wlan show interfaces
@'
How to read it:
  "Band" 5 GHz is what you want; "Radio type" 802.11ax = Wi-Fi 6.
  "Signal" (percent) > 70% good, < 50% weak. "Receive/Transmit rate" for 5 GHz 2x2 Wi-Fi 6
  at 80 MHz should be ~600-1200 Mbps. 2.4 GHz or < 300 Mbps = not getting full speed.
'@

# ---------- Nearby networks ----------
HR 'NEARBY NETWORKS & CHANNEL CONGESTION'
$scan = netsh wlan show networks mode=bssid
$scan
''
'Networks (BSSIDs) per channel (busiest first):'
$scan | Select-String '^\s*Channel\s*:\s*(\d+)' | ForEach-Object { $_.Matches[0].Groups[1].Value } |
    Group-Object | Sort-Object Count -Descending | ForEach-Object { '{0,5}  channel {1}' -f $_.Count, $_.Name }
@'
How to read it:
  2.4 GHz: only channels 1, 6, 11 don't overlap. Many neighbours on yours = congestion.
  5 GHz: 36-48 and 149-165 are the common non-DFS blocks. Fewer neighbours = better.
'@

# ---------- Latency ----------
HR 'LATENCY (idle)'
if ($gw) { Ping-Stats $gw 30 "Router/gateway ($gw)" }
Ping-Stats '1.1.1.1' 30 'Internet (1.1.1.1)'
Ping-Stats '8.8.8.8' 30 'Internet (8.8.8.8)'
@'
How to read it:
  Gateway avg should be < 5 ms with jitter < 5 ms. Higher = Wi-Fi problem (signal/interference).
  Internet minus gateway = your ISP's part. Any packet loss is worth fixing.
'@

# ---------- Speed test ----------
HR 'SPEED TEST (Cloudflare, 4 download / 2 upload streams) + LATENCY UNDER LOAD'
$curl = (Get-Command curl.exe).Source
if ($curl) {
    $tmp = Join-Path $env:TEMP "wifidiag-$stamp"; New-Item -ItemType Directory $tmp | Out-Null
    $procs = 1..4 | ForEach-Object {
        Start-Process $curl -NoNewWindow -PassThru -RedirectStandardOutput "$tmp\dl$_.txt" -ArgumentList @(
            '-s','-o','NUL','--max-time','15','-w','%{speed_download}',
            'https://speed.cloudflare.com/__down?bytes=100000000')
    }
    Start-Sleep 2
    $loadedDl = Ping-Stats '1.1.1.1' 40 'Ping DURING download'
    $procs | Wait-Process
    $dl = (1..4 | ForEach-Object { [double](Get-Content "$tmp\dl$_.txt") } | Measure-Object -Sum).Sum * 8 / 1e6

    $blob = "$tmp\upload.bin"; [IO.File]::WriteAllBytes($blob, (New-Object byte[] 40000000))
    $procs = 1..2 | ForEach-Object {
        Start-Process $curl -NoNewWindow -PassThru -RedirectStandardOutput "$tmp\ul$_.txt" -ArgumentList @(
            '-s','-o','NUL','--max-time','15','-w','%{speed_upload}','--data-binary',"`"@$blob`"",
            'https://speed.cloudflare.com/__up')
    }
    Start-Sleep 2
    $loadedUl = Ping-Stats '1.1.1.1' 40 'Ping DURING upload'
    $procs | Wait-Process
    $ul = (1..2 | ForEach-Object { [double](Get-Content "$tmp\ul$_.txt") } | Measure-Object -Sum).Sum * 8 / 1e6
    Remove-Item -Recurse -Force $tmp

    if ($dl -gt 0) { 'Download: {0:N1} Mbps' -f $dl } else { 'Download: FAILED (could not reach speed.cloudflare.com)' }
    if ($ul -gt 0) { 'Upload:   {0:N1} Mbps' -f $ul } else { 'Upload:   FAILED (could not reach speed.cloudflare.com)' }
    $loadedDl; $loadedUl
    @'
How to read it:
  Compare with your ISP plan. If avg ping under load is >100 ms above idle, you have
  "bufferbloat" (router queueing) - fixable with SQM/QoS on the router.
'@
} else { 'curl.exe not found - skipping (use speed.cloudflare.com in a browser).' }

# ---------- Bandwidth on this computer ----------
HR 'BANDWIDTH USE ON THIS COMPUTER (5-second sample)'
$s1 = Get-NetAdapterStatistics -Name $adapter.Name; Start-Sleep 5
$s2 = Get-NetAdapterStatistics -Name $adapter.Name
'Adapter traffic: {0:N2} Mbps down, {1:N2} Mbps up' -f (($s2.ReceivedBytes - $s1.ReceivedBytes) * 8 / 5e6),
    (($s2.SentBytes - $s1.SentBytes) * 8 / 5e6)
''
'Open internet connections per app:'
Get-NetTCPConnection -State Established | Where-Object { $_.RemoteAddress -notmatch '^(127\.|::1)' } |
    Group-Object OwningProcess | Sort-Object Count -Descending | Select-Object -First 15 | ForEach-Object {
        '{0,5}  {1}' -f $_.Count, (Get-Process -Id $_.Name).ProcessName }
''
'Known bandwidth-heavy apps currently running:'
Get-Process | Where-Object { $_.ProcessName -match 'OneDrive|Dropbox|GoogleDrive|iCloud|Steam|EpicGames|Battle\.net|qbittorrent|utorrent|BitTorrent|Backblaze|Teams|Zoom|Spotify|wuauserv|MoUsoCoreWorker|DoSvc' } |
    Select-Object -ExpandProperty ProcessName -Unique
'For live per-app Mbps: open Resource Monitor (resmon) > Network tab.'
'Also check Settings > Windows Update > Advanced > Delivery Optimization (uploads updates to other PCs).'

# ---------- Devices ----------
HR 'DEVICES ON YOUR NETWORK'
if ($myIp) {
    $net = $myIp -replace '\.\d+$', ''
    "Scanning $net.1-254 (ping sweep)..."
    $tasks = 1..254 | ForEach-Object { (New-Object System.Net.NetworkInformation.Ping).SendPingAsync("$net.$_", 1000) }
    try { [Threading.Tasks.Task]::WaitAll($tasks) } catch {}
    $alive = @{}; foreach ($t in $tasks) { if ($t.Result.Status -eq 'Success') { $alive[$t.Result.Address.ToString()] = $true } }
    $rows = Get-NetNeighbor -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -like "$net.*" -and $_.State -notin 'Unreachable','Incomplete' -and
        $_.LinkLayerAddress -and $_.LinkLayerAddress -ne '00-00-00-00-00-00' -and $_.LinkLayerAddress -ne 'FF-FF-FF-FF-FF-FF' -and
        $_.IPAddress -notmatch '\.255$' } |
        Sort-Object { [int]($_.IPAddress -split '\.')[3] } -Unique
    '{0,-16} {1,-18} {2,-30} {3}' -f 'IP','MAC','NAME','NOTE'
    $n = 0
    foreach ($r in $rows) {
        $mac = $r.LinkLayerAddress.ToLower(); $n++
        $name = (Resolve-DnsName $r.IPAddress -QuickTimeout -DnsOnly | Select-Object -First 1).NameHost
        $note = @()
        if ($r.IPAddress -eq $gw) { $note += 'router/gateway' }
        if ($mac -eq $ApMac) { $note += 'Omada EAP613 access point' }
        elseif ($mac.StartsWith('b8-fb-b3')) { $note += 'TP-Link device' }
        if ('26ae'.Contains([string]$mac[1])) { $note += 'private/random MAC (usually a phone/tablet/laptop)' }
        '{0,-16} {1,-18} {2,-30} {3}' -f $r.IPAddress, $mac, ($(if ($name) { $name } else { '-' })), ($note -join '; ')
    }
    "{0,-16} {1,-18} {2,-30} {3}" -f $myIp, $adapter.MacAddress.ToLower(), $env:COMPUTERNAME, 'THIS computer'
    ''
    "Total devices found: $($n + 1)"
    "(Devices that are asleep may be missing - the router/Omada client list is authoritative.)"
} else { "Could not determine this computer's IP - skipping." }

HR 'DONE'
"Report saved to: $report"
'Nothing was changed on this computer or your network.'
Stop-Transcript | Out-Null
