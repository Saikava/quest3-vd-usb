# Tracing a Quest 3 with Perfetto over adb (no root)

How to see every frame in the headset: when VD handed a video frame to the decoder, when it came out decoded, and which app frame the compositor showed on each display refresh. Configs and scripts: [`tools/perfetto/`](../tools/perfetto/).

## Recording

```bash
# the config goes on stdin; --background detaches; stop with: adb shell killall -INT perfetto
sed "s/DURATION/720000/" tools/perfetto/race.pbtx |
  adb shell perfetto --txt -c - -o /data/misc/perfetto-traces/run.pftrace --background
adb logcat -d -v epoch > logcat.txt           # logcat separately: the android.log data source comes out empty
adb shell killall -INT perfetto               # then wait until `adb shell pidof perfetto` finds nothing
adb pull /data/misc/perfetto-traces/run.pftrace run.pftrace
adb shell rm /data/misc/perfetto-traces/run.pftrace
```

(From Git Bash on Windows: `MSYS_NO_PATHCONV=1`, and a Windows path for `adb pull` via `cygpath -w`.)

| Config | What it records | Size |
|---|---|---|
| `race.pbtx` | scheduling, CPU frequencies, atrace `gfx` and `video` of all apps, all track events (compositor, VD) | ~5.5 MB/s, 256 MB buffer |
| `light.pbtx` | atrace `video` only (the decoder marks) | ~0.4 MB/s, 16 MB buffer |
| `events-probe.pbtx` | a 5 s probe of which kernel events are allowed | |

Pitfalls:
- Use `fill_policy: RING_BUFFER` with `write_into_file`. With `DISCARD` the trace stops as soon as the buffer is full (~2 min).
- Set `incremental_state_config { clear_period_ms: 1000 }`. Otherwise, once the compositor's writer loses a packet (its shared memory full), the trace processor drops all of its later events (`packet_skipped_seq_needs_incremental_state_invalid` in the stats).
- The full trace loads the headset itself: `traced` writes ~5 MB/s to flash and holds ~270 MB of buffers, and the kernel starts reclaiming memory. To count slow decodes, use `light.pbtx`.
- Clocks: the trace uses the headset's boot clock, `logcat -v epoch` its wall clock; `clock_snapshot` links them (`pfclock.py`). The headset's wall clock can be seconds off the PC's: measure with `adb shell date +%s.%N`.
- The logcat buffer is back to 256 KB after every boot (about 2 minutes): `adb logcat -G 64M`.

Kernel events on a retail Quest 3 (user build): allowed — sched (with `sched_blocked_reason`), irq/softirq, ipi, power/cpu_idle, cpu_frequency, clock_*, suspend_resume, thermal; not allowed — msm_vidc (the video decoder), power/gpu_frequency, devfreq, interconnect, rpmh, workqueue, kgsl, msm_bus, scm. The decoder itself can't be seen inside without root.

## Markers

**Compositor** (`com.oculus.vrruntimeservice`, thread `OVR::TimeWarp`, category `xr_runtime_markers`):
- each display refresh is composed in two screen slices: `SliceCpuStart` (args `debug.frameIndex`, `debug.screenSlice`);
- `TimeWarpSlice : F` — the app frame F it used. The same F as on the refresh before = a **repeated frame**;
- `FetchFrameInternal : F` > `IngestFrame` — the compositor took the app's frame (~3.5 ms before the slice is shown);
- `WaitForClient : F` — waiting for the app's GPU work; counters `Stale`, `FPS`, `GpuUtilization`, `media.decode_latency_us#…`.

**Virtual Desktop** (thread "Game Thread"): `xrWaitFrame : F` (with `PhaseSync` inside), `xrBeginFrame : F`, `!xrEndFrame : F`. After `xrWaitFrame` VD's thread waits for the decoded frame, checking every 1 ms.

**Decoders** (VD's threads `NDK MediaCodec_`, `CodecLooper`; atrace `video`):
- `CCodecBufferChannel::queue(c2.qti.av1.decoder.low_latency#<id>@ts=<T>)` — the frame's data handed to the decoder;
- `CCodecBufferChannel::onWorkDone(...)` — decoded;
- **T is the PC's QPC clock in microseconds** (VD's capture time; sending starts ~3 ms later), so each video frame in the headset matches the PC's packet capture exactly (`pfnet.py`).
- The decoder HAL is the `media.hwcodec` process (threads `poll_av1DLowLat`, `EvtQ_c2.qti.av1`, `EvtQ_codecPipe`); the decoder's interrupt thread is `irq/358-msm-vid`.

**logcat:** once a second `VrApi: FPS=…,Stale=N,Stale2/5/10/max=…` — the compositor's repeated frames in that second (`vrapi.py`), no trace needed.

## Scripts

Python 3 with `pip install perfetto` (the trace processor binary downloads itself on first use).

| Script | What |
|---|---|
| `q.py <trace> <sql>…` | run SQL on a trace |
| `survey.py <trace>` | what is in a trace: the biggest slice producers, ftrace, counters |
| `pfstale.py <trace> <prefix>` | frame by frame: the compositor's repeated frames and what VD's frame thread was doing → `<prefix>_frames.csv`, `_stale.csv`, `_stale.txt`, `_detail.txt` |
| `pfvideo.py <trace> <prefix>` | the video frames: data handed over / decoded, for both decoders → `<prefix>_video.csv` |
| `pfclock.py <trace> <prefix>` | for a light trace: only the clock offset into `<prefix>_stale.csv` |
| `pfdec.py`, `pfwhy.py` | runs compared: decode time per eye, decodes over 12/16 ms per minute; per repeated frame, the video frame VD was waiting for |
| `pfnet.py <prefix> <vd.pcapng> <frametimes.csv>` | each frame's way PC → headset by stage (capture, send, ACK, VD's read, decode) |
| `slowdec.py`, `slowdiff.py`, `slowlog.py`, `pfwho.py`, `pfcam.py` | what happens in the headset during slow decodes: CPU by process, frequencies, the decoder HAL's threads, logcat lines, the colour-camera calibration |
| `vrapi.py <logcat> <frametimes.csv> <clock offset>` | repeated frames from the VrApi lines within a race |

`pfdec.py`, `pfwhy.py`, `slowdiff.py`, `slowlog.py`, `pfwho.py` and `vrapi.py` take the race's time window from a frame-times CSV that the game's VR mod writes (`ft_<label>_1.csv`: one row per frame, `display,start,reported,frames,period`, QPC seconds). For another game, replace that part with your own time window. `vrapi.py` and `pfnet.py` turn the PC's QPC seconds into the time of day with a constant `QPC_TO_WALL` (time of day − QPC, in seconds) measured on our PC after one boot: set your own.
