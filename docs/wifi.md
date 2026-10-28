# Virtual Desktop over Wi-Fi on Quest 3: the router's firmware matters

Measured on one setup in October 2026. Quest 3 with Virtual Desktop 1.34.24, lying on a desk 1–2 m from the access point (RSSI −35…−50 dBm). The PC was wired to the access point at 1 Gbit/s. Channel 36 at 80 MHz, later channel 100 (see [What caused the remaining late frames](#what-caused-the-remaining-late-frames)). A scan from the Archer found two neighbours in the 36–48 block: one on 48 using the same 80 MHz block at −69 dBm, and one on 36 at 20/40 MHz, −77 dBm. All numbers below are from this setup.

## TL;DR

1. **Stock TP-Link firmware on an Archer C6 v2 (1.3.8 EU) drops or holds the headset's uplink packets.** These are tracking data and TCP ACKs going back to the PC:
   - 0.23–0.58% of them were lost in every run;
   - they also stopped for about 50 ms, 1–2 times a minute on average (0–6.7), sometimes for 150–370 ms.

   **The same router flashed with OpenWrt 25.12.6**, with nothing else changed, lost 0–0.001% and stalled 0–0.4 times a minute.
2. **On OpenWrt the Archer delivers a 150 Mbit/s VD-like stream smoothly.** It had 1–9 frames a minute more than 8 ms late. In a real race, AV1 10-bit at 150 Mbit/s gave 2.1 repeated frames a minute, against 1.0–1.75 over a USB cable.
3. **With nothing polling it, the Archer on OpenWrt carries 180–200 Mbit/s about as evenly as 150.** 180 Mbit/s had 0.3–10 frames a minute more than 8 ms late (median ~3.7), and none more than 33 ms late in 38 minutes. 200 Mbit/s was similar. 220–240 Mbit/s got worse, and the CPU reached ~80% at 240. It's one MIPS core at 775 MHz, and OpenWrt bridges the traffic in software.
4. **Two things made it look worse, and both are easy to avoid:**
   - **My own measurement.** Running `iw station dump` and `iw survey dump` on the router once a second took 180 Mbit/s from ~4 to 17–23 late frames a minute. Reading `/proc` once a second didn't. So don't query the router's Wi-Fi driver while playing. LuCI pages that list connected clients probably do the same; that's untested.
   - **A neighbour's 80 MHz network on channels 36–48.** At night, when it was busy, channel 36 had twice the late frames of channel 100 and ten times the retries. In the daytime it made no difference. Channels 100–112 had no neighbours here.

   Earlier versions of this page blamed the CPU and then the chip's heat for the ~12 late frames a minute and the rare 0.1 s stalls measured at 150–180 Mbit/s (the stalls came at 160–180). Both were wrong: those runs had the polling and the night-time neighbour in them. The chip runs hotter on a busy channel because retries keep it transmitting longer.
5. **A Wi-Fi 6 router on its stock firmware, Xiaomi Mesh System AX3000 (RA82), carries 300 Mbit/s, but not evenly**: 10–110 late frames a minute. None of its settings changed that by an order of magnitude, and 160 MHz was worse. OpenWrt can't be installed on it: secure boot is on, and U-Boot runs only Xiaomi-signed images.
6. **Measure with VD running on the headset.** Without it, the Quest 3 keeps Wi-Fi power saving on and lets a location service scan channels. Both make Wi-Fi look worse than it is in a game (see [Measuring](#measuring)).

**What I use for Wi-Fi play:** Archer C6 v2 on OpenWrt 25.12.6, channel 100, and so far VD at 150 Mbit/s with AV1 10-bit. VD puts ~5% more on the air than its bitrate setting, so VD at 170–180 Mbit/s matches the 180–190 that tested clean. That isn't checked in a game yet. Even 300 Mbit/s over Wi-Fi was not achieved on either access point.

## Archer C6 v2: stock firmware against OpenWrt

### Uplink loss and stalls

`owprobe.py`: a 150 Mbit/s TCP stream to the headset, plus a 32-byte UDP probe every 2 ms that `tsecho` on the headset echoes back with its kernel receive time. That splits every delay and loss into PC → headset and headset → PC. These were 3-minute runs with the first 10 s left out, and VD was not running.

| | Stock 1.3.8 (8 runs) | OpenWrt 25.12.6, ath10k-ct |
|---|---|---|
| Probes lost headset → PC | 0.23–0.58% (every run) | 0–0.001% |
| Probes lost PC → headset | 0–0.03% | ~0 |
| Stalls ≥ 30 ms per minute | 0–6.7 (≈ 1.7 on average), ~45–50 ms each, sometimes 150–370 ms | 0–0.4 |

On the stock firmware, measurements ruled out everything other than the access point:
- **The cable, the PC's network card and the router's wired side were fine.** A wired ping to the router and to the ISP's terminal every 5 ms stayed under 1 ms with no loss, including during the stalls.
- **The headset was not scanning during the stalls.** Its radio was on 97–100% of the time, it received every beacon, and it answered within 2 ms.
- **Interference was not the cause.** 40 MHz, which avoids the neighbour, was not better (6.7 stalls a minute).
- **TxBF/MU-MIMO** made no difference, off or on (two A/B pairs).

### VD-like frame stream

`frameprobe.py` sends one TCP "frame" of bitrate/120 every 8.33 ms, like VD at 120 Hz. The receiver on the headset logs when each frame is complete. A frame counts as "late" when it arrives later than the link's normal delivery time.

| Archer on OpenWrt | Frames > 8 ms late per minute | > 16 ms | > 33 ms | Max | AP CPU |
|---|---|---|---|---|---|
| 150 Mbit/s, 10 min (72 000 frames, none missing) | 0.9 | 0 | 0 | 11 ms | |
| 150 Mbit/s, VD running, 3 × 1 min | 1 / 9 / 1 | | | 8 / 21 / 8 ms | |
| 200 Mbit/s, VD not running | 17 | 6.3 | 3.0 | | 75% median, 100% peaks |
| 250 Mbit/s, VD not running | 291 | | | | 91% |
| 300 Mbit/s, VD not running | 2899 | 324 | 2.7 | | saturated |

All the runs in this section were on channel 36, with the router's Wi-Fi driver polled once a second. That overstates the late frames; see [What caused the remaining late frames](#what-caused-the-remaining-late-frames) for runs without it.

Between 150 and 200 Mbit/s, with VD running, I did two series. The first was three interleaved rounds of 1-minute runs at 150–200, in steps of 10. The second was 5-minute runs back to back, like a game. Together:

| Archer on OpenWrt, VD running | Minutes | Frames > 8 ms late per minute | Stalls (frames > 33 ms late) | AP CPU, median |
|---|---|---|---|---|
| 150 Mbit/s | 11 | 12.0 | 0 | 59–71% |
| 160 Mbit/s | 8 | 12.3 | 2 (48, 125 ms) | 59–71% |
| 170 Mbit/s | 8 | 12.1 | 2 (101, 105 ms) | 63–73% |
| 180 Mbit/s | 8 | 12.8 | 1 (81 ms) | 72–75% |
| 190 Mbit/s | 3 | 27.7 | 2 (38, 67 ms) | 72–77% |
| 200 Mbit/s | 3 | 14.7 | 0 | 74–76% |

- **Run-to-run spread (0–35 a minute) is larger than the difference between 150 and 180.** There's no sharp threshold in this range.
- **Each stall is one event of about 0.1 s.** Around 30 frames in a row are late by 30–105 ms. In that second the AP's transmit rate drops, from 650–867 to 325–360 Mbit/s, and retries rise, while the signal stays the same.
- **The chip was hotter during stalls**, at 101–111 °C against 91–98 °C in the clean runs. That's an effect, not the cause: retries keep it transmitting longer. OpenWrt's thermal throttling (`ath10k_thermal`) never engaged.

The 5 GHz chip runs hot: 69 °C idle, 83–105 °C at 150 Mbit/s, and up to 114 °C at 180 Mbit/s and 106–115 °C at 200–500 Mbit/s, all with the polling on. Without it, it read 76–91 °C before and after each 180–240 Mbit/s run.

### What caused the remaining late frames

**Neighbours.** The 180 Mbit/s runs were 5 minutes each, in blocks 100 → 36 → 100, at night, with polling on in all of them:

| Channel | Frames > 8 ms late per minute | > 33 ms | Retries per second (median) |
|---|---|---|---|
| 100 (no neighbours) | 11–16 | 0 in 20 minutes | 44–438 |
| 36 (the 80 MHz neighbour on 48) | 31 | 0–0.2 | 905–1005 |

In the morning, without polling, I alternated 36 and 100 again. Channel 36 was no worse: 0.3–4 a minute, against 2–10 on 100, with ~1% retries on both. So the neighbour hurts only when it's busy. I stayed on 100, which doesn't depend on that.

**Polling the router.** Then 180 Mbit/s on channel 100, 3-minute runs, interleaved:

| What ran on the router during the stream | Frames > 8 ms late per minute | Max | AP CPU, average |
|---|---|---|---|
| nothing | 4.0 / 3.3 | 15 / 17 ms | 67 / 69% |
| `iw dev phy0-ap0 station dump` and `iw dev phy0-ap0 survey dump`, once a second | **17.3 / 23.3** | 29 / 19 ms | 71 / 73% |
| `/proc/stat` and the chip temperature, read once a second with shell builtins | 1.3 / 4.0 | 12 / 16 ms | 64 / 68% |

In the earlier runs, 54–70% of the late frames on channel 100 fell within 60 ms after a polling tick, against 5% by chance. Five of the eight 0.1 s stalls started at the same point of the polling cycle.

**A sniffer saw nothing else wrong.** I used a MacBook in monitor mode: Wireless Diagnostics → Window → Sniffer, channel 100, 80 MHz. With VD running, the headset never entered power save and never scanned, and nothing else transmitted on channels 100–112. The AP retried 2.5% of its frames. It sent small aggregates, ~9 MPDUs of two packets each, at MCS 5–7 on two streams.

**Bitrate on channel 100 without polling**, two interleaved rounds of 4-minute runs:

| Bitrate | Frames > 8 ms late per minute | > 33 ms | Max | AP CPU, average |
|---|---|---|---|---|
| 180 Mbit/s | 2.0 / 7.3, and 4.0 / 3.3 above | 0 | 19 / 33 ms | 65–70% |
| 200 Mbit/s | 2.5 / 13.0 | 0 | 25 / 23 ms | 70 / 71% |
| 220 Mbit/s | 17.8 / 6.5 | one 0.12 s stall | 123 / 20 ms | 72 / 76% |
| 240 Mbit/s | 13.8 / 12.3 | 0 | 21 / 16 ms | 82 / 79% |

Where the last 2–10 late frames a minute (8–20 ms) on a clean channel come from, I don't know.

### In a game

FlatOut 2 (VR mod, VDXR), Godlike quality, 120 Hz. "Repeated frames" are the headset compositor's count (VrApi `Stale`).

| Connection | Repeated frames per minute | What caused them |
|---|---|---|
| USB cable, H.264+ 500 Mbit/s (patched driver, [README](../README.md)) | 1.0–1.75 | the headset's video decoder |
| Archer C6 v2 on OpenWrt, AV1 10-bit 150 Mbit/s (one 3.4-minute race) | 2.1 | 5 of 7 were the decoder, 2 were Wi-Fi frames 6–7 ms late. Wi-Fi also lost packets 3 times, which made video frames 17–25 ms late. The stock firmware's ~50 ms uplink stalls were gone: the longest pause in the race was 19 ms |
| Xiaomi RA82 stock, "Wi-Fi 5 Compatible Mode", H.264+ 300 Mbit/s | 4.1 | mostly the network: video frames 5–23 ms late, ACK pauses from the headset > 15 ms 4.7 times a minute |

## Flashing an Archer C6 v2 with OpenWrt

This is what was done here. It was done once, on one router; read the [OpenWrt device page](https://openwrt.org/toh/tp-link/archer_c6_v2) before you start.

1. **Check the label: hardware version v2, EU/RU/JP.** The US v2 is a different board with its own image (`tplink_archer-c6-v2-us`). Other hardware versions are different hardware altogether.
2. **Download the factory image** from [downloads.openwrt.org/releases/25.12.6/targets/ath79/generic/](https://downloads.openwrt.org/releases/25.12.6/targets/ath79/generic/): `openwrt-25.12.6-ath79-generic-tplink_archer-c6-v2-squashfs-factory.bin`. Check its SHA-256 against `sha256sums` in the same folder. It was `7429e9a019ceb754a0c9775180f64e7397eefbbe24f602e8a767fe011fd60bbb`.
3. **Optional:** save the stock configuration (System Tools → Backup & Restore) and download the stock firmware from TP-Link's site, in case you want to go back.
4. **In the stock web interface:** System Tools → Firmware Upgrade → choose the factory image → Upgrade → Yes. About two minutes later the router answers as OpenWrt at **192.168.1.1**, with SSH open and no root password. Set one with `passwd` over SSH, or in LuCI at http://192.168.1.1.
5. **Make it a plain access point inside your existing network**, if your main router already does DHCP. Connect the PC to it with a cable, since its own DHCP is off after this. Replace the addresses, country, SSID and password with your own:

   ```sh
   # one bridge over all ports, a static address in the main network, no DHCP or IPv6 RA from this box
   uci delete network.wan; uci delete network.wan6
   uci set network.@switch_vlan[0].ports='1 2 3 4 5 0t'
   uci delete network.@switch_vlan[1]
   uci delete network.lan.ipaddr
   uci add_list network.lan.ipaddr='192.168.100.5/24'   # a free address outside the main router's DHCP pool
   uci set network.lan.gateway='192.168.100.1'          # the main router
   uci add_list network.lan.dns='192.168.100.1'
   uci delete network.lan.ip6assign
   uci set dhcp.lan.ignore=1; uci set dhcp.lan.ra=disabled; uci set dhcp.lan.dhcpv6=disabled
   /etc/init.d/odhcpd disable
   # 5 GHz: 80 MHz, WPA2-AES; 2.4 GHz off. Pick a block of four channels nobody else uses (see below).
   # 100 is a DFS channel: after boot the AP stays silent for a minute, and if it detects radar it moves to another
   # channel, which drops the link for about a minute
   uci set wireless.radio0.channel=100
   uci set wireless.radio0.htmode=VHT80
   uci set wireless.radio0.country=DE                   # your country
   uci set wireless.radio0.disabled=0
   uci set wireless.default_radio0.ssid='VR'
   uci set wireless.default_radio0.encryption='psk2+ccmp'
   uci set wireless.default_radio0.key='your Wi-Fi password'
   uci set wireless.radio1.disabled=1
   uci commit
   reboot
   ```

   To find a free block, scan from the router while it's on a non-DFS channel. On a DFS channel the scan returned `Resource busy` here. Look at each network's primary channel and, for 80 MHz ones, `center freq segment 1`: 42 means the block 36–48, 58 means 52–64, 106 means 100–112.

   ```sh
   iw dev phy0-ap0 scan | grep -E "^BSS|freq:|signal:|SSID:|primary channel|channel width|center freq segment 1"
   ```

   Afterwards the router is at the new address. Nothing else was changed. No packages were added: the image's default driver, `ath10k-ct`, was used. Transmit power was left at the default.
6. **Going back to stock**, not tried here: TP-Link's TFTP recovery. The PC is at 192.168.0.66 and serves the stock firmware named `ArcherC6v2_tp_recovery.bin`, and you hold Reset while powering the router on. See the OpenWrt device page for the details.

## Xiaomi Mesh System AX3000 (RA82) on stock firmware

The RA82 has a Qualcomm IPQ5018 SoC (two Cortex-A53 cores at 1 GHz, network offload) and Wi-Fi 6 2×2 with up to 1201 Mbit/s at 80 MHz. Its CPU doesn't limit it the way the Archer's does: 9–13% at 300 Mbit/s. The tests used firmware 1.4.31, with root access over SSH and every change made at runtime.

Frame test with VD running, 1-minute runs, frames more than 8 ms late per minute:

| Bitrate | RA82, Wi-Fi 6 (HE80), extras off | RA82, stock "Wi-Fi 5 Compatible Mode" (VHT80) | Archer on OpenWrt (polled, channel 36) |
|---|---|---|---|
| 150 Mbit/s | 2 – 36 (6 runs) | | 0 – 9 (6 runs) |
| 200 Mbit/s | 27 / 43 | 22 / 30 | 4 – 27 (3 runs) |
| 250 Mbit/s | | 68 | 291 (VD not running) |
| 300 Mbit/s | 10 / 28 / 110 | 44 / 48 | CPU saturated |
| 300 Mbit/s at 160 MHz (HE160) | 846 / 145 / 33 | | |

Things that changed nothing beyond the 2–3× run-to-run spread, with six 5-minute and four 1-minute runs at 300 Mbit/s:
- stopping Xiaomi's daemons (mesh, QoS, telemetry, cron and similar);
- beamforming off;
- 1024-QAM off;
- U-APSD off;
- 2.4 GHz radio off;
- Wi-Fi 6 with OFDMA, TWT and spatial reuse off.

Measurements also ruled out several other causes:
- **The router's CPU was not the cause.** Late frames didn't line up with CPU load or with processes starting.
- **There was no thermal throttling:** level 0 throughout.
- **The channel looked clean:** the RA82's own scan showed one neighbouring network on channels 36–48, at −88 dBm, and noise at −95 dBm. A later scan from the Archer found a network on channel 48 at −69 dBm. All the RA82 tests were on channel 36, so the neighbour may have affected them too. That's untested.

**The headset is not the only reason.** A MacBook Pro (M3 Pro) put in the headset's place, receiving the same stream through the RA82, got 1 and 9 late frames a minute at 150 Mbit/s and ~20 at 300 Mbit/s. That's the same pattern as the headset. macOS has no low-latency Wi-Fi mode, so this points at the access point without proving it.

**There's no way out on this hardware.** Xiaomi has nothing newer than 1.4.31, and no one has a working way to install OpenWrt on the RA82 ([hzyitc/openwrt-redmi-ax3000#88](https://github.com/hzyitc/openwrt-redmi-ax3000/issues/88)). On this unit secure boot is fused on, and both U-Boot copies refuse unsigned images.

Untested next step for 300 Mbit/s: a MediaTek MT7981 router that OpenWrt officially supports, such as the Xiaomi AX3000T (not the RD03v2) or the ASUS RT-AX52.

## Measuring

The tools are in [`tools/wifi/`](../tools/wifi/); [its README](../tools/wifi/README.md) has the build and run commands. None of them needs root on the headset. The PC sends and the headset receives, which is the direction VD's video goes:
- **`tsecho`** runs on the headset. It's a UDP echo with kernel receive timestamps, a TCP sink, and a frame receiver.
- **`owprobe.py`** runs the uplink/downlink probe under load.
- **`frameprobe.py`** runs the VD-like frame stream.
- **`framesink`** is the frame receiver for a laptop, used as a second client.

**Run VD in the foreground on the headset during every Wi-Fi test.** VD takes Android's low-latency Wi-Fi lock (`WIFI_MODE_FULL_LOW_LATENCY`). Without it, the Quest 3:
- keeps Wi-Fi power saving on (`dumpsys wifi`: `mPowerSaveDisableRequests 0` without VD, 2 with it);
- lets `com.facebook.wearable.system.location.service` scan channels every 2–7 minutes. A scan takes ~9 s and makes frames up to 170 ms late.

The lock can't be taken from adb without root. Instead, start VD with the USB cable connected. Its stream then goes over the cable, so Wi-Fi stays free for the test, and the lock holds while VD is in front:

```sh
adb shell input keyevent KEYCODE_WAKEUP
adb shell am broadcast -a com.oculus.vrpowermanager.prox_close   # "headset is on"
adb shell setprop debug.oculus.guardian_pause 1                  # no boundary prompt on the desk
adb shell am start -n VirtualDesktop.Android/md59102214312e19799944a61bf7bc2f23e.VrActivity
# ... test ...
adb shell am broadcast -a com.oculus.vrpowermanager.automation_disable
adb shell setprop debug.oculus.guardian_pause 0
```

The lock drops when the headset sleeps, so start VD again before each run. Most of my early frame tests were run without VD. They made the stock RA82 look 15× worse than the Archer at 150 Mbit/s; with VD running the difference was 2–8×. The Archer stock-vs-OpenWrt probe runs were all without VD, so they compare like with like.

Other notes:
- **Don't query the AP's Wi-Fi driver during a test.** On the Archer, `iw station dump` and `iw survey dump` once a second made 180 Mbit/s 4–7× worse. Take readings before and after the stream instead. Reading `/proc/stat` and `/sys/class/hwmon/*/temp1_input` with shell builtins (`read l < /proc/stat`) once a second was harmless. The RA82 was sampled that way, so its numbers aren't affected.
- **To see the air itself, a Mac makes a usable sniffer:** Wireless Diagnostics → Window → Sniffer, with the channel and the width. The capture lands in `/var/tmp`. The M3 Pro's capture cut the AP's A-MSDUs at ~1.8 KB, but it caught every BlockAck from the headset.
- **One-minute runs are enough to spot an order-of-magnitude difference.** Identical settings vary 2–3× between runs, so smaller differences need several runs.
- **On a Mac as the second client, run `sudo ifconfig awdl0 down` during the test**, and `up` afterwards. AWDL, the radio used by AirDrop, takes the radio off the channel.
