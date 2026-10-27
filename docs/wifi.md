# Virtual Desktop over Wi-Fi on Quest 3: the router's firmware matters

Measured on one setup in October 2026. Quest 3 with Virtual Desktop 1.34.24, lying on a desk 1–2 m from the access point (RSSI −35…−50 dBm). The PC was wired to the access point at 1 Gbit/s. Channel 36 at 80 MHz, with one weak neighbour on 5 GHz (channel 48, −77 dBm). All numbers below are from this setup.

## TL;DR

1. **Stock TP-Link firmware on an Archer C6 v2 (1.3.8 EU) drops or holds the headset's uplink packets.** These are tracking data and TCP ACKs going back to the PC:
   - 0.23–0.58% of them were lost in every run;
   - they also stopped for about 50 ms, 1–2 times a minute on average (0–6.7), sometimes for 150–370 ms.

   **The same router flashed with OpenWrt 25.12.6**, with nothing else changed, lost 0–0.001% and stalled 0–0.4 times a minute.
2. **On OpenWrt the Archer delivers a 150 Mbit/s VD-like stream smoothly.** It had 1–9 frames a minute more than 8 ms late. In a real race, AV1 10-bit at 150 Mbit/s gave 2.1 repeated frames a minute, against 1.0–1.75 over a USB cable.
3. **Above ~150 Mbit/s the Archer's CPU runs out**: one MIPS core at 775 MHz, and OpenWrt bridges the traffic in software. At 200 Mbit/s 17 frames a minute were late; at 300 Mbit/s, thousands.
4. **A Wi-Fi 6 router on its stock firmware, Xiaomi Mesh System AX3000 (RA82), carries 300 Mbit/s, but not evenly**: 10–110 late frames a minute. None of its settings changed that by an order of magnitude, and 160 MHz was worse. OpenWrt can't be installed on it: secure boot is on, and U-Boot runs only Xiaomi-signed images.
5. **Measure with VD running on the headset.** Without it, the Quest 3 keeps Wi-Fi power saving on and lets a location service scan channels. Both make Wi-Fi look worse than it is in a game (see [Measuring](#measuring)).

**What I use for Wi-Fi play:** Archer C6 v2 on OpenWrt 25.12.6, VD at 150 Mbit/s, AV1 10-bit. Even 300 Mbit/s over Wi-Fi was not achieved on either access point.

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
| 200 Mbit/s | 17 | 6.3 | 3.0 | | 75% median, 100% peaks |
| 250 Mbit/s | 291 | | | | 91% |
| 300 Mbit/s | 2899 | 324 | 2.7 | | saturated |

The 5 GHz chip runs hot: 69 °C idle, 83–101 °C at 150 Mbit/s, and 106–115 °C at 200–500 Mbit/s.

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
   # 5 GHz: channel 36, 80 MHz, WPA2-AES; 2.4 GHz off
   uci set wireless.radio0.channel=36
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

   Afterwards the router is at the new address. Nothing else was changed. No packages were added: the image's default driver, `ath10k-ct`, was used. Transmit power was left at the default.
6. **Going back to stock**, not tried here: TP-Link's TFTP recovery. The PC is at 192.168.0.66 and serves the stock firmware named `ArcherC6v2_tp_recovery.bin`, and you hold Reset while powering the router on. See the OpenWrt device page for the details.

## Xiaomi Mesh System AX3000 (RA82) on stock firmware

The RA82 has a Qualcomm IPQ5018 SoC (two Cortex-A53 cores at 1 GHz, network offload) and Wi-Fi 6 2×2 with up to 1201 Mbit/s at 80 MHz. Its CPU doesn't limit it the way the Archer's does: 9–13% at 300 Mbit/s. The tests used firmware 1.4.31, with root access over SSH and every change made at runtime.

Frame test with VD running, 1-minute runs, frames more than 8 ms late per minute:

| Bitrate | RA82, Wi-Fi 6 (HE80), extras off | RA82, stock "Wi-Fi 5 Compatible Mode" (VHT80) | Archer on OpenWrt |
|---|---|---|---|
| 150 Mbit/s | 2 – 36 (6 runs) | | 1 – 9 (3 runs) |
| 200 Mbit/s | 27 / 43 | 22 / 30 | 17 (VD not running) |
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
- **The channel was clean:** one neighbouring network on channels 36–48, at −88 dBm; noise −95 dBm.

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
- **One-minute runs are enough to spot an order-of-magnitude difference.** Identical settings vary 2–3× between runs, so smaller differences need several runs.
- **On a Mac as the second client, run `sudo ifconfig awdl0 down` during the test**, and `up` afterwards. AWDL, the radio used by AirDrop, takes the radio off the channel.
