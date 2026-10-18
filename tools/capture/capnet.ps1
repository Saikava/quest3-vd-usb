# capnet.ps1 <dir>: run elevated. Like cap.ps1 but only the packet headers on the USB network adapter (pktmon), no
# VDXR trace: until <dir>\stop.txt appears, then writes vd.pcapng (and deletes the raw vd.etl).
param([string]$dir)
New-Item -ItemType Directory -Force $dir | Out-Null
Remove-Item "$dir\stop.txt", "$dir\done.txt", "$dir\started.txt" -ErrorAction SilentlyContinue
pktmon stop 2>&1 | Out-Null
pktmon filter remove 2>&1 | Out-Null
$id = $null
foreach ($l in (pktmon comp list 2>&1)) { if ($l -match '^\s*(\d+)\s+.*UsbNcm') { $id = $Matches[1]; break } }
if (-not $id) { $id = 'nics' }
"component $id" | Out-File -Encoding utf8 "$dir\log.txt"
pktmon start --capture --pkt-size 128 --comp $id --file-name "$dir\vd.etl" --file-size 3000 2>&1 | Out-File -Append -Encoding utf8 "$dir\log.txt"
"started" | Out-File -Encoding utf8 "$dir\started.txt"
while (-not (Test-Path "$dir\stop.txt")) { Start-Sleep -Milliseconds 300 }
pktmon stop 2>&1 | Out-File -Append -Encoding utf8 "$dir\log.txt"
pktmon etl2pcap "$dir\vd.etl" --out "$dir\vd.pcapng" 2>&1 | Out-File -Append -Encoding utf8 "$dir\log.txt"
Remove-Item "$dir\vd.etl" -ErrorAction SilentlyContinue
"done" | Out-File -Encoding utf8 "$dir\done.txt"
