$ErrorActionPreference = 'Stop'
$resultPath = Join-Path $PSScriptRoot 'admin-result.json'
$logPath = Join-Path $PSScriptRoot 'prepare-elevated.log'
try {
    & (Join-Path $PSScriptRoot 'manage_test_driver.ps1') -Mode Prepare *> $logPath
    @{ Success = $true; FinishedAt = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 0
}
catch {
    $_ | Out-String | Add-Content -LiteralPath $logPath -Encoding UTF8
    @{ Success = $false; Error = $_.Exception.Message; FinishedAt = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
