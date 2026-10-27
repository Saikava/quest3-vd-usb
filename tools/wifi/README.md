# Wi-Fi link tests: PC → Quest 3

These are the tools behind [`docs/wifi.md`](../../docs/wifi.md). The PC is wired to the access point and sends; the headset receives over Wi-Fi, which is the direction VD's video goes. Nothing on the headset needs root.

| File | What |
|---|---|
| `tsecho/` (Go) | Receiver on the headset. It has a UDP echo on 5562 that adds kernel receive, user receive and send times, and logs every probe it got, so a lost probe can be blamed on the way down or the way up. A TCP sink on 5561 takes the load stream. A frame receiver on 5563 logs when each frame's first and last byte arrived. |
| `owprobe.py <seconds> <load_mbps> <label> <outdir>` | A TCP load at the given rate plus a 32-byte UDP probe every 2 ms. Prints loss and excess delay separately in each direction, and stalls ≥ 30 ms. |
| `steady.py <runs dir>` | Summarises every `owprobe` run in a folder again, without the first 10 s, when TCP is still ramping up. |
| `frameprobe.py <seconds> <mbps> <hz> <label> <outdir>` | A VD-like stream: one TCP frame of mbps/hz every 1/hz s. Prints frames more than 4 / 8 / 16 / 33 ms late per minute, with the first 10 s left out, and writes `frames.csv`. |
| `framesink/` (Go) | The same frame receiver for a laptop (macOS, Windows, Linux), used as a second Wi-Fi client in the headset's place. It returns its log over TCP 5564. |

## Build and install

You need Go and Python 3.8+. The scripts find `adb` on `PATH`, or the path in the `ADB` environment variable. If more than one adb device is attached, set `ANDROID_SERIAL` to the headset's serial from `adb devices`.

```sh
cd tsecho
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o tsecho-arm64 .
adb push tsecho-arm64 /data/local/tmp/tsecho
adb shell chmod 755 /data/local/tmp/tsecho
```

`owprobe.py` and `frameprobe.py` start `tsecho` over adb, find the headset's Wi-Fi address (`wlan0`), and pull its log when the run ends.

## Run

Before each run, wake the headset and start VD in the foreground with the USB cable connected (commands in [`docs/wifi.md`](../../docs/wifi.md#measuring)). Without VD the headset's Wi-Fi power saving is on, and the results look worse than in a game.

```sh
python frameprobe.py 70 150 120 archer-150 runs/archer-150   # 1 minute measured, 150 Mbit/s, 120 Hz
python owprobe.py 180 150 archer-probe runs/archer-probe
python steady.py runs
```

A laptop as the receiver instead of the headset: run `framesink` on it, built with `go build` in `framesink/`, then:

```sh
FP_HOST=<laptop IP> python frameprobe.py 70 300 120 mac-300 runs/mac-300
```

On a Mac, run `sudo ifconfig awdl0 down` for the duration of the test, then `sudo ifconfig awdl0 up`.

The scripts were written for this one investigation; read each one's header before running it.
