# Virtual Desktop over a USB cable on Quest 3 (Windows 11): fixing the freezes and the micro-stutters

Notes from two days of measuring one setup: Quest 3, Virtual Desktop 1.34.24 (beta, wired USB mode), Windows 11 (build 26200), RTX 5070 Ti, a 32-bit OpenXR game (FlatOut 2 with a VR mod) through VDXR. Every number below was measured on this setup, mostly in 3–5-minute races. Your mileage may vary; the causes should not.

## TL;DR

1. **Short full freezes (~¼ second every 10–60 s) over USB, but not over Wi-Fi**: a bug in Windows' own USB network driver (`UsbNcm.sys`). Partial workaround: `netsh int tcp set global timestamps=disabled` (admin), then restart VD on the headset. Real fix: Microsoft's (reported, see below), or a patched driver if you are comfortable with Windows test-signing mode.
2. **The remaining micro-stutters** (single repeated frames, a few per minute) come from the Quest 3's hardware video decoder taking too long now and then. Most of the slow decodes happen while the headset calibrates its colour cameras or runs background work. **Turning on Travel Mode, turning off Wi-Fi and hand/body tracking** cut decodes slower than 16 ms from 5.6 to 0 per minute and repeated frames from 3.8 to 1.1 per minute.
3. **At Godlike quality use 120 Hz, not 144 Hz.** At 144 Hz the decoder can't keep up (both eyes take ~7.2 ms against a 6.9 ms frame): 5× more repeated frames.
4. **Codec:** H.264+ at 500 Mbit/s looked best at speed to me; AV1 10-bit decodes more evenly. HEVC and HEVC 10-bit had by far the worst decode spikes on Quest 3.

## 1. The freezes: a bug in Windows' USB NCM driver

VD's USB mode (Quest beta 1.34.19+, Horizon OS 2.5+) runs Ethernet over USB: the headset shows up in Windows as a "UsbNcm Host Device" network adapter, and VD streams over TCP on it.

Windows' NCM host driver (`UsbNcm.sys`, open source: [microsoft/NCM-Driver-for-Windows](https://github.com/microsoft/NCM-Driver-for-Windows)) packs TCP segments into USB transfer blocks (NTBs) of at most 16 KB for the Quest. Its size check forgets one 8-byte table entry (the NDP's null terminator), so a block can come out up to 8 bytes too big. The headset drops such a block whole. Windows resends the same segments, they get packed into the same oversized block, and are lost again, about ten times in a row, until TCP's 300 ms minimum retransmission timeout resends them one by one. That is the freeze.

How it was pinned down:
- Packet captures on the USB adapter (`pktmon`) during play: every loss was the same 15200-byte piece of VD's video. With the IPv6 MTU of 1400 that VD's service sets on the adapter, plus TCP timestamps, that piece is 11 × 1328 + 592 bytes. Alone in a block, it lands exactly in the bad window.
- A plain TCP stream to the headset (`toybox nc -l` on the Quest, one send every 2 ms, MTU 1400, no timestamps; [`tools/repro/ntbsweep.py`](tools/repro/ntbsweep.py)) reproduces it deterministically, no VD involved: sends of **15337–15344 bytes** lose ~900 segments per second; 15336 and 15345 lose nothing. With MTU 1500 the bad sizes move to 15421–15428. Both ranges are exactly what the driver's arithmetic allows.
- The code: `common/ntb.cpp`, `NcmTransferBlock::CopyNextDatagram` reserves `(m_CurrentNdpDatagramCount + 1) * sizeof(DPE)`, but `SetNdp` writes one more entry. The fix is `+ 2`.

Affected: Windows 11 `UsbNcm.sys` 10.0.26100.9444 and .9711 (the version Windows Update brought later). Any Linux/Android NCM gadget with the default 16 KB block size is affected, PC → device only. Meta Link and Wi-Fi don't use this driver.

### What you can do

| Option | Effect (measured) |
|---|---|
| `netsh int tcp set global timestamps=disabled` (admin terminal), then restart VD on the headset (needs new connections). Undo: `timestamps=allowed`. | Moves VD's most common piece size out of the bad window. Freezes: 1 per 5-minute race instead of 2–5. Other piece sizes still hit it now and then. |
| Wi-Fi | No freezes from this bug. |
| Lower bitrate | Fewer losses, not zero (72 Hz / ~12 Mbit/s: no freezes in 5 min). |
| USB Ethernet adapter on the headset, PC on Ethernet | Avoids Windows' NCM driver entirely. Not tested. |
| Changing the adapter's MTU | Doesn't stick: VD's service sets it back to 1400 on every connection. It would only move the bad sizes anyway. |
| Patched driver (advanced, below) | Zero losses: 10 minutes of racing at 122 Mbit/s without a single lost segment; TCP over the cable did 2.5 Gbit/s clean. |

### Advanced: patch the driver yourself

The fix in machine code is one byte in each of two places (the NTB16 and NTB32 copies of the function): `lea eax, [r11 + 1]` → `lea eax, [r11 + 2]` (`41 8D 43 01` → `41 8D 43 02`), plus the PE checksum. A modified Microsoft driver loses its Microsoft signature, so it has to be signed with your own test certificate and Windows has to run in **test-signing mode**. Know the costs first:

- Secure Boot must be off for `bcdedit /set testsigning on`;
- some anti-cheat systems refuse to run in test mode;
- Windows shows a "Test Mode" watermark;
- the self-signed certificate you trust is a weak spot: delete its private key once the driver is signed;
- a Windows update can replace the driver package and reset the service to the stock driver (it did here once);
- the byte offsets differ per driver build: check the original's SHA-256 and find the instructions with Microsoft's public symbols.

The procedure used here: make a patched copy of `UsbNcm.sys` from the DriverStore (never touch the original), sign it with a self-signed code-signing certificate, trust that certificate in the machine's Root and TrustedPublisher stores, copy the driver to `C:\Windows\System32\drivers\UsbNcmNtbFix.sys`, point `HKLM\SYSTEM\CurrentControlSet\Services\UsbNcm\ImagePath` at it, enable test signing, reboot, and verify the patched module is actually the one loaded. Keep a rollback script that restores the original `ImagePath` and turns test signing off. The scripts (pinned to builds .9444 and .9711 by SHA-256) are in [`tools/usbncm-fix/`](tools/usbncm-fix/); read its README first.

If you'd rather wait: upvote [the issue on Microsoft's repository](https://github.com/microsoft/NCM-Driver-for-Windows/issues/27) and send the same through the Feedback Hub (Devices and Drivers).

## 2. The micro-stutters: the Quest 3's video decoder

With the freezes gone, a few single-frame stutters per minute remained. To see where they came from, I traced the headset with **Perfetto over adb (no root needed)**: `adb shell perfetto` with a config on stdin. The trace shows every display refresh of the compositor (which app frame it used: the same one twice = a repeated frame) and, from VD's process, when each video frame's data was handed to the decoder and when it came out decoded. The video frame's timestamp is the PC's QPC clock, so each frame can be matched to the PC's packet capture exactly.

What it showed:
- **Every repeated frame was a video frame decoded too late.** The PC's capture and send, the cable and VD's reading of the data were all on time.
- VD sends **one stream per eye**, and the hardware decoder does them **one after the other**, ~3 ms each. At Godlike / 120 Hz / AV1 10-bit the second eye is ready ~7.5 ms after its data on the median, against an 8.33 ms frame. There is little room.
- For AV1, decode time does not depend on the frame's size (100 KB and 600 KB alike): bitrate doesn't matter, pixels, codec and refresh rate do. **For H.264 the bitrate does matter** (second eye 5.9 ms at 500 Mbit/s against 4.1 ms at a lower rate).
- VD already asks the decoder for everything it can: low-latency mode, real-time priority, maximum operating rate. No VD setting gets more out of it.

### Codecs (Godlike, 120 Hz, decode time of one eye in ms: median / 99.9th percentile)

| Codec | Eye 1 | Eye 2 |
|---|---|---|
| AV1 10-bit | 7.3 / 12.1 | 5.0 / 11.2 |
| HEVC | 5.7 / 15 | 5.5 / 23 |
| HEVC 10-bit | 5.3 / 18 | 7.2 / 22 |
| H.264 | 4.4 / 8.7 | 4.1 / 8.3 |

### Where the slow decodes come from, and the fix

The slow decodes come in bursts. In one race (H.264+ 500 Mbit/s, 120 Hz, 69 decodes over 13 ms):
- **a third** fell in the 1.4 seconds every 21.4 s when the tracking service switches on the **colour cameras for calibration** (`iot:ocal` in logcat): 6.5% of the time, 5× more slow decodes than chance;
- most of the rest came with bursts of background work: Meta's telemetry, the kernel reclaiming and compacting memory, the Wi-Fi telemetry service starting (Wi-Fi was on although VD ran over USB).

Then, on the headset: **Travel Mode on, Wi-Fi off, hand and body tracking off** (plus a longer sleep timeout). In Travel Mode the colour-camera calibration didn't run once, telemetry logged far less, and head tracking stayed full 6DoF (logcat: `Mode=TravelModeDescriptorVega,6DoF`). I changed these together, so I can't say which one matters most.

| H.264+ 500 Mbit/s, Godlike, 120 Hz | Repeated frames / min | Decodes > 12 ms / min | > 16 ms / min | One eye, 99.9th pct |
|---|---|---|---|---|
| default headset settings | 3.8 | 24 | 5.6 | 14 ms |
| Travel Mode, Wi-Fi off, hand/body tracking off | **1.1** | **0.4** | **0** | **9.5 ms** |

The ~1 single repeated frame per minute that's left is a frame decoded 2–5 ms later than usual, with no big stall behind it. VD's window for a frame is only a few milliseconds, and VD has no setting for it.

### What didn't help

- Lower settings: Ultra / 90 Hz / H.264 also gave ~1 repeated frame per minute. Below a certain decoder load, the rare slow decodes set the floor, not the load.
- Forcing the headset's CPU/GPU clocks up (`setprop debug.oculus.cpuLevel 4` / `gpuLevel 4`).
- Lower bitrate with AV1 (decode time doesn't depend on it).
- 144 Hz at Godlike: 8.4 repeated frames per minute against 1.5–1.7 at 120 Hz.

## My settings now

| | |
|---|---|
| Connection | VD 1.34.24 beta, USB cable, patched `UsbNcm.sys` |
| VD | Godlike, 120 Hz, H.264+ 500 Mbit/s, video buffering on, sharpening off |
| Quest | Travel Mode on, Wi-Fi off, hand and body tracking off |
| Windows | TCP timestamps at the default (`allowed`) |
| Result | about one single repeated frame per minute, the game drops none |

## Tracing your own headset

Everything here was measured over adb without root. The Perfetto configs and analysis scripts (Python, using Perfetto's trace processor) are in [`tools/perfetto/`](tools/perfetto/), the method in [`docs/tracing.md`](docs/tracing.md).

Useful markers: compositor thread `OVR::TimeWarp` in `com.oculus.vrruntimeservice` (`TimeWarpSlice : F` = app frame F used for this refresh), VD's `xrWaitFrame : F` / `!xrEndFrame : F`, and the decoders' `CCodecBufferChannel::queue(...@ts=T)` / `onWorkDone(...)`. logcat's per-second `VrApi: ... Stale=N` line counts repeated frames without a trace.

## What's in this repository

| Path | What |
|---|---|
| [`tools/repro/`](tools/repro/) | `ntbsweep.py`: does a TCP send of a given size get lost on the way to the headset? `loadtest.py`: a steady TCP stream PC → headset. Both use `toybox nc` on the Quest over adb (`ADB` environment variable, default `adb`). |
| [`tools/usbncm-fix/`](tools/usbncm-fix/) | the patch, signing, install / verify / rollback scripts for the driver (no Microsoft binaries) |
| [`tools/perfetto/`](tools/perfetto/) | Perfetto trace configs for the Quest and the analysis scripts |
| [`tools/capture/`](tools/capture/) | packet capture on the USB adapter (`pktmon`, run elevated) and its analysis for VD's stream |
| [`docs/tracing.md`](docs/tracing.md) | tracing a Quest 3 with Perfetto over adb, without root |

The scripts were written during the investigation for one PC and one game; read each one's header before running it.
