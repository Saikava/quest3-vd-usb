# A fixed copy of UsbNcm.sys (advanced, at your own risk)

These are the scripts that fixed Windows' USB NCM host driver on one PC (the bug: the main README, section 1). They change **two bytes** in a copy of the installed `UsbNcm.sys`, sign the copy with a self-made test certificate and point the `UsbNcm` service at it. The original in the DriverStore is never modified.

**Read before using:**
- Windows has to run in **test-signing mode** (`bcdedit /set testsigning on`), which needs **Secure Boot off**, shows a "Test Mode" watermark and makes some anti-cheat systems refuse to run.
- The scripts are **pinned to two exact builds** by SHA-256: `10.0.26100.9444` (`patch_usbncm.py`) and `10.0.26100.9711` (`9711/prepare_9711.py`). For any other build they refuse to run; the byte offsets have to be found again (Microsoft's public symbols: `UsbNcm.pdb`, function `NcmTransferBlock<…>::CopyNextDatagram`, the `lea eax, [r11 + 1]` before the size multiplication).
- A Windows update can replace the driver package and reset the service to the stock driver. Check after big updates.
- Once the copy is signed, **delete the test certificate's private key** (`Remove-Item Cert:\CurrentUser\My\<thumbprint> -DeleteKey`): the certificate is trusted machine-wide, and anything running as you could sign with it.
- No Microsoft binaries are in this repository: the scripts patch your own copy.

## Steps (as used)

1. `patch_usbncm.py` (or `9711/prepare_9711.py`): reads the installed driver from the DriverStore, checks its SHA-256 and PE checksum, writes `UsbNcm.original.sys`, `UsbNcm.patched.sys` (`41 8D 43 01` → `41 8D 43 02` in the NTB16 and NTB32 copies of `CopyNextDatagram`, PE checksum recomputed) and `manifest.json`.
2. `sign_test_copy.ps1`: creates a code-signing certificate "UsbNcm NTB Fix - Local Test Only" (non-exportable key, current user's store), signs a copy as `UsbNcm.test.sys` with `signtool` (Windows SDK; adjust its path) and checks that signing changed nothing but the signature and checksum.
3. `manage_test_driver.ps1 -Mode Prepare` (elevated; `run_prepare_admin.ps1` runs it and logs the result): trusts the certificate in the machine's Root and TrustedPublisher stores, copies the driver to `C:\Windows\System32\drivers\UsbNcmNtbFix.sys`, points `HKLM\SYSTEM\CurrentControlSet\Services\UsbNcm\ImagePath` at it, turns test signing on, suspends BitLocker for one restart if it's on, and registers a one-time task that checks after the reboot that the patched module is the one loaded (and rolls back if it isn't). Its working folder is `C:\ProgramData\UsbNcmNtbFix\`.
4. Reboot. `manage_test_driver.ps1 -Mode Status` shows the state; `state.json` should say `PatchedImageLoaded-VerifiedByKernelModuleList`.
5. Rollback any time: `Restore-original.ps1` (elevated): the original `ImagePath`, test signing as it was, the certificate's trust removed, the Quest's network adapter restarted. Reboot to leave test mode.

`9711/update_and_load.ps1` moved an existing install to the .9711 build and reloaded the driver without a reboot (by disabling and re-enabling the Quest's network adapter). The device check in the scripts expects a Quest 3 (`USB\VID_2833&PID_5018&MI_03`).

The fix in the source (for Microsoft): in `common/ntb.cpp`, `CopyNextDatagram`, reserve `(m_CurrentNdpDatagramCount + 2) * sizeof(DPE)` to count the NDP's null entry, as `SetNdp` writes it.
