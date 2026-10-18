$ErrorActionPreference = 'Stop'
$sourceDirectory = $PSScriptRoot
$rootDirectory = 'C:\ProgramData\UsbNcmNtbFix'
$resultPath = Join-Path $sourceDirectory 'reload-result.json'
$state = $null
$disabledIds = @()
$transcript = $false
try {
    Start-Transcript -LiteralPath (Join-Path $rootDirectory 'reload-9711.log') -Append
    $transcript = $true
    # Load the existing native module-list verifier and rollback helpers.
    . (Join-Path (Split-Path -Parent $sourceDirectory) 'manage_test_driver.ps1') -Mode Status
    $state = Get-Content -LiteralPath (Join-Path $root 'state.json') -Raw | ConvertFrom-Json
    if (([UsbNcmTestNative]::CiFlags() -band 2) -eq 0) { throw 'TESTSIGNING is not active.' }
    if ((Get-FileHash -LiteralPath $originalImage -Algorithm SHA256).Hash -ne $originalHash) { throw 'Updated inbox driver changed.' }
    $currentServicePath = (Get-ItemProperty -LiteralPath $serviceKey -Name ImagePath).ImagePath
    if ($currentServicePath -ne '\SystemRoot\System32\DriverStore\FileRepository\usbncm.inf_amd64_70d658347632acad\UsbNcm.sys') {
        throw 'Service path changed since inspection.'
    }
    if ((Get-FileHash -LiteralPath (Join-Path $sourceDirectory 'UsbNcm.test.sys') -Algorithm SHA256).Hash -ne $signedHash) { throw 'New signed copy changed.' }
    if ((Get-AuthenticodeSignature -LiteralPath (Join-Path $sourceDirectory 'UsbNcm.test.sys')).Status -ne 'Valid') { throw 'New test signature is not trusted.' }
    if (@([UsbNcmTestNative]::LoadedNcmImages()) -match '\\UsbNcmNtbFix\.sys$') { throw 'Test image is already loaded; do not overwrite it.' }
    foreach ($device in (Get-PnpDevice -Class Net -PresentOnly)) {
        $deviceService = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName 'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue
        if ($deviceService.Data -eq 'UsbNcm' -and $device.InstanceId -notlike 'USB\VID_2833&PID_5018&MI_03\*') {
            throw ('Another connected device uses UsbNcm: ' + $device.InstanceId)
        }
    }

    $archive = Join-Path $root 'archive-9444'
    $null = New-Item -ItemType Directory -Path $archive
    foreach ($name in @('state.json','manifest.json','signing.json','UsbNcm.original.sys','UsbNcm.test.sys','manage_test_driver.ps1','verify.log','README.txt')) {
        if (Test-Path -LiteralPath (Join-Path $root $name)) {
            Copy-Item -LiteralPath (Join-Path $root $name) -Destination (Join-Path $archive $name)
        }
    }
    foreach ($name in @('manifest.json','signing.json','UsbNcm.original.sys','UsbNcm.test.sys','README.txt')) {
        Copy-Item -LiteralPath (Join-Path $sourceDirectory $name) -Destination (Join-Path $root $name) -Force
    }
    Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $sourceDirectory) 'manage_test_driver.ps1') -Destination (Join-Path $root 'manage_test_driver.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $sourceDirectory 'UsbNcm.test.sys') -Destination $testImage -Force
    $state.OriginalImage = $originalImage
    $state.OriginalImagePath = $currentServicePath
    $state.OriginalSha256 = $originalHash
    $state.SignedSha256 = $signedHash
    $state.Failure = ''
    $state.Stage = 'Updated9711Signed-Staged'
    $state | Add-Member -MemberType NoteProperty -Name DriverVersion -Value '10.0.26100.9711' -Force
    Save-State $state

    foreach ($device in (Get-NcmDevices)) {
        if ($device.Status -ne 'OK') { throw 'Quest network device is not in an OK state before reload.' }
        Disable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false
        $disabledIds += $device.InstanceId
    }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $loaded = @([UsbNcmTestNative]::LoadedNcmImages())
        if (-not ($loaded -match '\\UsbNcm\.sys$')) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($loaded -match '\\UsbNcm\.sys$') {
        & sc.exe stop UsbNcm
        Start-Sleep -Seconds 1
        $loaded = @([UsbNcmTestNative]::LoadedNcmImages())
    }
    Set-ItemProperty -LiteralPath $serviceKey -Name ImagePath -Value $testServicePath
    foreach ($id in $disabledIds) { Enable-PnpDevice -InstanceId $id -Confirm:$false }
    $disabledIds = @()

    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $loaded = @([UsbNcmTestNative]::LoadedNcmImages())
        if ($loaded -match '\\UsbNcmNtbFix\.sys$') { break }
        Start-Sleep -Milliseconds 500
    }
    $state.LoadedImages = $loaded
    $state.DeviceStatus = @(Get-NcmDevices | Select-Object InstanceId,Status,Problem)
    if ($loaded -match '\\UsbNcmNtbFix\.sys$') {
        if (@($state.DeviceStatus | Where-Object Status -ne 'OK').Count) { throw 'The patched driver loaded, but the Quest device reports a PnP problem.' }
        $state.Stage = 'PatchedImageLoaded-VerifiedByKernelModuleList'
        Save-State $state
        Remove-VerificationTask
        @{ Success=$true; Loaded=$true; DriverVersion='10.0.26100.9711'; LoadedImages=$loaded } |
            ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    }
    elseif ($loaded -match '\\UsbNcm\.sys$') {
        $state.Stage = 'Updated9711Prepared-ExistingInboxImageStillLoaded-RebootRequired'
        Save-State $state
        @{ Success=$true; Loaded=$false; RestartRequired=$true; LoadedImages=$loaded } |
            ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    }
    else { throw 'Neither original nor patched UsbNcm image is loaded after re-enabling Quest.' }
}
catch {
    $failure = $_.Exception.Message
    Write-Output ('FAILED: ' + $failure)
    foreach ($id in $disabledIds) {
        try { Enable-PnpDevice -InstanceId $id -Confirm:$false } catch { Write-Output $_ }
    }
    if ($state) {
        $state.Failure = $failure
        try { Restore-Original $state $true } catch { Write-Output ('Rollback error: ' + $_.Exception.Message) }
        $state.Stage = 'ReloadFailed-RollbackAttempted'
        Save-State $state
    }
    @{Success=$false; Error=$failure} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
finally {
    if ($transcript) { Stop-Transcript }
}
