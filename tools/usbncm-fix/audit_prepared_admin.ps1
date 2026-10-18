$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\UsbNcmNtbFix'
$auditLog = Join-Path $PSScriptRoot 'audit-elevated.log'
try {
    foreach ($name in @('manage_test_driver.ps1','README.txt','Restore-original.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $root $name)
    }
    $task = Get-ScheduledTask -TaskName 'UsbNcmNtbFix-VerifyAfterRestart'
    if ($task.Principal.UserId -notin @('SYSTEM','S-1-5-18')) { throw 'Unexpected startup task principal.' }
    if ($task.State -eq 'Disabled') { throw 'Startup verification task is disabled.' }
    $boot = @(& bcdedit.exe /enum)
    if ($LASTEXITCODE -ne 0 -or ($boot -join "`n") -notmatch '(?im)^\s*testsigning\s+Yes\s*$') {
        throw 'TESTSIGNING is not enabled in the boot entry.'
    }
    $boot | Set-Content -LiteralPath (Join-Path $root 'boot-prepared.txt') -Encoding UTF8
    & (Join-Path $root 'manage_test_driver.ps1') -Mode Status *> $auditLog
    $statusResult = [pscustomobject]@{
        AuditPassed = $true
        At = (Get-Date).ToString('o')
        TaskState = [string]$task.State
        TaskPrincipal = $task.Principal.UserId
        StartupDelay = $task.Triggers.Delay
        TaskAction = $task.Actions.Arguments
        ServicePath = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\UsbNcm').ImagePath
        DriverSignature = [string](Get-AuthenticodeSignature 'C:\Windows\System32\drivers\UsbNcmNtbFix.sys').Status
        TestSigningConfiguredForNextBoot = $true
        OriginalFileHash = (Get-FileHash 'C:\Windows\System32\DriverStore\FileRepository\usbncm.inf_amd64_55ca763394be2e25\UsbNcm.sys' -Algorithm SHA256).Hash
    }
    $statusResult | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $root 'prepared-audit.json') -Encoding UTF8
}
catch {
    $_ | Out-String | Add-Content -LiteralPath $auditLog -Encoding UTF8
    @{AuditPassed=$false; Error=$_.Exception.Message} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $root 'prepared-audit.json') -Encoding UTF8
    exit 1
}
