$ErrorActionPreference = 'Stop'
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\UsbNcmNtbFix\manage_test_driver.ps1" -Mode Rollback'
Start-Process -FilePath 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
    -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -Wait
