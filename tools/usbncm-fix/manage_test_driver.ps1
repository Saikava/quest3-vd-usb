param([ValidateSet('Prepare', 'Verify', 'Rollback', 'Status')][string]$Mode = 'Status')

$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\UsbNcmNtbFix'
$serviceKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\UsbNcm'
$testImage = 'C:\Windows\System32\drivers\UsbNcmNtbFix.sys'
$testServicePath = '\SystemRoot\System32\drivers\UsbNcmNtbFix.sys'
$originalImage = 'C:\Windows\System32\DriverStore\FileRepository\usbncm.inf_amd64_70d658347632acad\UsbNcm.sys'
$originalHash = 'F34630163C88948E6FB272BD60F84D588EC2907CF228FAA52FF698F3DF0F0B79'
$signedHash = 'A2E2258F44735D959299922796EFBB409A7E279B6691BF1943BF07B59904A4EE'
$thumbprint = 'DDC974F9308DDDE953C19866C96A5C5A6FC68743'
$taskName = 'UsbNcmNtbFix-VerifyAfterRestart'
$powershell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell or through the prepared UAC launcher.'
}

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public static class UsbNcmTestNative {
    [StructLayout(LayoutKind.Sequential)] struct CiInfo { public uint Length; public uint Options; }
    [StructLayout(LayoutKind.Sequential)] struct Luid { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential)] struct Privilege { public uint Count; public Luid Id; public uint Attributes; }
    [DllImport("ntdll.dll")] static extern int NtQuerySystemInformation(int kind, ref CiInfo info, uint size, out uint returned);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool LookupPrivilegeValue(string system, string name, out Luid id);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool AdjustTokenPrivileges(IntPtr token, bool disableAll, ref Privilege state, uint length, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("psapi.dll", SetLastError=true)] static extern bool EnumDeviceDrivers([Out] IntPtr[] addresses, uint bytes, out uint needed);
    [DllImport("psapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetDeviceDriverFileName(IntPtr address, StringBuilder name, uint size);
    public static uint CiFlags() {
        CiInfo info = new CiInfo { Length = 8 }; uint returned;
        int status = NtQuerySystemInformation(103, ref info, 8, out returned);
        if (status != 0) throw new Exception("NtQuerySystemInformation: " + status);
        return info.Options;
    }
    public static string[] LoadedNcmImages() {
        IntPtr token;
        if (!OpenProcessToken(new IntPtr(-1), 0x28, out token)) throw new Win32Exception();
        try {
            Luid id;
            if (!LookupPrivilegeValue(null, "SeDebugPrivilege", out id)) throw new Win32Exception();
            Privilege state = new Privilege { Count = 1, Id = id, Attributes = 2 };
            if (!AdjustTokenPrivileges(token, false, ref state, 0, IntPtr.Zero, IntPtr.Zero)) throw new Win32Exception();
            int error = Marshal.GetLastWin32Error();
            if (error != 0) throw new Win32Exception(error);
        } finally { CloseHandle(token); }
        IntPtr[] addresses = new IntPtr[4096]; uint needed;
        if (!EnumDeviceDrivers(addresses, (uint)(addresses.Length * IntPtr.Size), out needed)) throw new Win32Exception();
        if (needed > addresses.Length * IntPtr.Size) throw new Exception("Module list overflow");
        List<string> found = new List<string>();
        for (int i=0; i<needed/IntPtr.Size; i++) {
            if (addresses[i] == IntPtr.Zero) throw new Exception("Kernel module addresses were redacted");
            StringBuilder path = new StringBuilder(2048);
            if (GetDeviceDriverFileName(addresses[i], path, (uint)path.Capacity) == 0) continue;
            string name = path.ToString();
            if (name.EndsWith("\\UsbNcm.sys", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith("\\UsbNcmNtbFix.sys", StringComparison.OrdinalIgnoreCase)) found.Add(name);
        }
        return found.ToArray();
    }
}
'@

function Save-State($state) {
    $state.UpdatedAt = (Get-Date).ToString('o')
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $root 'state.json') -Encoding UTF8
}

function Get-NcmDevices {
    @(Get-PnpDevice -Class Net -PresentOnly | Where-Object {
        $_.InstanceId -like 'USB\VID_2833&PID_5018&MI_03\*'
    })
}

function Remove-VerificationTask {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
}

function Restore-Original($state, [bool]$restartDevice) {
    # Restore the service path before touching the device, so even a failed
    # restart leaves the next PnP load pointing at the original Microsoft file.
    if (-not (Test-Path -LiteralPath $state.OriginalImage)) {
        # Windows Update may replace the whole inbox driver package and reset
        # this service to its new DriverStore path during a reboot.
        $currentPath = (Get-ItemProperty -LiteralPath $serviceKey -Name ImagePath).ImagePath
        if ($currentPath -notlike '\SystemRoot\System32\DriverStore\FileRepository\usbncm.inf_amd64_*\UsbNcm.sys') {
            throw 'Original image is missing, and the service does not point at a new inbox package.'
        }
        $currentImage = $currentPath -replace '^\\SystemRoot', 'C:\Windows'
        $currentSignature = Get-AuthenticodeSignature -LiteralPath $currentImage
        if ($currentSignature.Status -ne 'Valid' -or $currentSignature.SignerCertificate.Subject -notmatch 'CN=Microsoft Windows,') {
            throw 'The replacement inbox image does not have a valid Microsoft Windows signature.'
        }
        $state.OriginalImage = $currentImage
        $state.OriginalImagePath = $currentPath
        $state.OriginalSha256 = (Get-FileHash -LiteralPath $currentImage -Algorithm SHA256).Hash
    }
    Set-ItemProperty -LiteralPath $serviceKey -Name ImagePath -Value $state.OriginalImagePath
    $bootValue = if ($state.OriginalTestSigningConfigured) { 'on' } else { 'off' }
    & bcdedit.exe /set testsigning $bootValue
    if ($LASTEXITCODE -ne 0) { throw 'Could not restore the original TESTSIGNING setting.' }
    Remove-VerificationTask
    if ($restartDevice) {
        foreach ($device in (Get-NcmDevices)) {
            Disable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false
            Start-Sleep -Milliseconds 750
            Enable-PnpDevice -InstanceId $device.InstanceId -Confirm:$false
        }
    }
    foreach ($store in @('Cert:\LocalMachine\Root', 'Cert:\LocalMachine\TrustedPublisher')) {
        $certificatePath = Join-Path $store $thumbprint
        if (Test-Path -LiteralPath $certificatePath) { Remove-Item -LiteralPath $certificatePath }
    }
    $state.Stage = 'OriginalServicePathRestored'
    Save-State $state
}

$transcriptStarted = $false
try {
    if ($Mode -eq 'Prepare') {
        if (Test-Path -LiteralPath (Join-Path $root 'state.json')) { throw 'A previous test state exists; inspect it first.' }
        if ((Get-FileHash -LiteralPath $originalImage -Algorithm SHA256).Hash -ne $originalHash) { throw 'Installed driver changed.' }
        $sourceSigned = Join-Path $PSScriptRoot 'UsbNcm.test.sys'
        if ((Get-FileHash -LiteralPath $sourceSigned -Algorithm SHA256).Hash -ne $signedHash) { throw 'Signed copy changed.' }
        $oldServicePath = (Get-ItemProperty -LiteralPath $serviceKey -Name ImagePath).ImagePath
        if ($oldServicePath -ne '\SystemRoot\System32\DriverStore\FileRepository\usbncm.inf_amd64_70d658347632acad\UsbNcm.sys') {
            throw 'The current service path is unexpected.'
        }
        if (Test-Path -LiteralPath $testImage) { throw 'The destination test image already exists.' }

        $null = New-Item -Path $root -ItemType Directory -Force
        # Only Administrators and SYSTEM may change files executed by the startup task.
        & icacls.exe $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX'
        if ($LASTEXITCODE -ne 0) { throw 'Could not protect the installation directory.' }
        Start-Transcript -LiteralPath (Join-Path $root 'prepare.log') -Append
        $transcriptStarted = $true
        foreach ($name in @('manage_test_driver.ps1', 'manifest.json', 'signing.json', 'UsbNcmTest.cer', 'UsbNcm.original.sys', 'UsbNcm.test.sys', 'README.txt')) {
            Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $root $name)
        }
        & reg.exe export 'HKLM\SYSTEM\CurrentControlSet\Services\UsbNcm' (Join-Path $root 'UsbNcm-before.reg') /y
        if ($LASTEXITCODE -ne 0) { throw 'Service backup failed.' }
        $bootOutput = @(& bcdedit.exe /enum)
        if ($LASTEXITCODE -ne 0) { throw 'Could not read the current boot entry.' }
        $bootOutput | Set-Content -LiteralPath (Join-Path $root 'boot-before.txt') -Encoding UTF8
        $configuredBefore = [bool](($bootOutput -join "`n") -match '(?im)^\s*testsigning\s+(Yes|True|On|1)\s*$')
        $state = [pscustomobject][ordered]@{
            Stage = 'Preparing'
            UpdatedAt = ''
            OriginalImage = $originalImage
            OriginalImagePath = $oldServicePath
            OriginalSha256 = $originalHash
            OriginalTestSigningConfigured = $configuredBefore
            OriginalCiFlags = ('0x{0:X}' -f [UsbNcmTestNative]::CiFlags())
            SignedSha256 = $signedHash
            CertificateThumbprint = $thumbprint
            TestImage = $testImage
            LoadedImages = @()
            DeviceStatus = @()
            BitLockerSuspendedForOneRestart = $false
            Failure = ''
        }
        Save-State $state

        foreach ($store in @('Cert:\LocalMachine\Root', 'Cert:\LocalMachine\TrustedPublisher')) {
            $null = Import-Certificate -FilePath (Join-Path $root 'UsbNcmTest.cer') -CertStoreLocation $store
        }
        Copy-Item -LiteralPath $sourceSigned -Destination $testImage
        $signature = Get-AuthenticodeSignature -LiteralPath $testImage
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Thumbprint -ne $thumbprint) {
            throw ('Test signature validation failed: ' + $signature.Status)
        }
        if ((Get-FileHash -LiteralPath $testImage -Algorithm SHA256).Hash -ne $signedHash) { throw 'Installed copy differs.' }
        $verifyTool = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe'
        & $verifyTool verify /pa /v $testImage
        if ($LASTEXITCODE -ne 0) { throw 'SignTool verification failed.' }

        $bitLockerVolume = Get-BitLockerVolume -MountPoint 'C:' -ErrorAction Stop
        if ($bitLockerVolume.ProtectionStatus -eq 'On') {
            $null = Suspend-BitLocker -MountPoint 'C:' -RebootCount 1
            $state.BitLockerSuspendedForOneRestart = $true
            Save-State $state
        }

        $action = New-ScheduledTaskAction -Execute $powershell -Argument '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\UsbNcmNtbFix\manage_test_driver.ps1" -Mode Verify'
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $trigger.Delay = 'PT30S'
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $null = Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Description 'Verify the local UsbNcm NTB boundary fix once after restart; restore the original path on load failure.'

        & bcdedit.exe /set testsigning on
        if ($LASTEXITCODE -ne 0) { throw 'Could not enable TESTSIGNING.' }
        # The currently loaded image is unchanged. PnP will use this signed copy
        # after Windows restarts with TESTSIGNING active.
        Set-ItemProperty -LiteralPath $serviceKey -Name ImagePath -Value $testServicePath
        $state.Stage = 'SignedAndPrepared-RebootRequired'
        $state.LoadedImages = @([UsbNcmTestNative]::LoadedNcmImages())
        Save-State $state
        Write-Output 'PREPARED: signed image staged; TESTSIGNING enabled for next boot; restart required.'
    }
    elseif ($Mode -eq 'Verify') {
        Start-Transcript -LiteralPath (Join-Path $root 'verify.log') -Append
        $transcriptStarted = $true
        $state = Get-Content -LiteralPath (Join-Path $root 'state.json') -Raw | ConvertFrom-Json
        if (([UsbNcmTestNative]::CiFlags() -band 2) -eq 0) { throw 'TESTSIGNING is not active in the running kernel.' }
        if ((Get-FileHash -LiteralPath $testImage -Algorithm SHA256).Hash -ne $signedHash) { throw 'The staged driver changed.' }
        $loaded = @()
        for ($attempt = 0; $attempt -lt 15; $attempt++) {
            $loaded = @([UsbNcmTestNative]::LoadedNcmImages())
            if ($loaded -match '\\UsbNcmNtbFix\.sys$') { break }
            Start-Sleep -Seconds 2
        }
        $state.LoadedImages = $loaded
        $devices = @(Get-NcmDevices)
        $state.DeviceStatus = @($devices | Select-Object InstanceId, Status, Problem)
        if ($loaded -match '\\UsbNcmNtbFix\.sys$') {
            $state.Stage = 'PatchedImageLoaded-VerifiedByKernelModuleList'
            Save-State $state
            Remove-VerificationTask
            Write-Output 'VERIFIED: UsbNcmNtbFix.sys is present in the actual loaded kernel module list.'
        }
        elseif ($devices.Count -eq 0) {
            $state.Stage = 'Prepared-WaitingForQuestNetworkInterface'
            Save-State $state
            Remove-VerificationTask
            Write-Output 'The Quest network interface is absent; the test path remains ready for the next connection.'
        }
        else { throw 'Quest is present, but the patched image did not load.' }
    }
    elseif ($Mode -eq 'Rollback') {
        Start-Transcript -LiteralPath (Join-Path $root 'rollback.log') -Append
        $transcriptStarted = $true
        $state = Get-Content -LiteralPath (Join-Path $root 'state.json') -Raw | ConvertFrom-Json
        Restore-Original $state $true
        $state.LoadedImages = @([UsbNcmTestNative]::LoadedNcmImages())
        Save-State $state
        Write-Output 'Original service path and boot setting restored. Restart Windows to finish leaving test mode.'
    }
    else {
        Get-Content -LiteralPath (Join-Path $root 'state.json')
        [pscustomobject]@{
            CiFlags = ('0x{0:X}' -f [UsbNcmTestNative]::CiFlags())
            ServiceImagePath = (Get-ItemProperty -LiteralPath $serviceKey -Name ImagePath).ImagePath
            ActualLoadedImages = @([UsbNcmTestNative]::LoadedNcmImages())
        } | ConvertTo-Json
    }
}
catch {
    $failure = $_.Exception.Message
    Write-Output ('FAILED: ' + $failure)
    if ($state) {
        $state.Failure = $failure
        try {
            Restore-Original $state ($Mode -eq 'Verify')
            $state.Stage = 'Failed-OriginalServicePathRestored'
            Save-State $state
        }
        catch {
            Write-Output ('ROLLBACK ALSO FAILED: ' + $_.Exception.Message)
            $state.Stage = 'Failed-RollbackFailed'
            $state.Failure = $failure + '; rollback: ' + $_.Exception.Message
            Save-State $state
        }
    }
    throw
}
finally {
    if ($transcriptStarted) { Stop-Transcript }
}
