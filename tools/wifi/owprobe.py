"""owprobe.py <seconds> <load_mbps> <label> <outdir>: one-way split of the PC -> headset Wi-Fi link.
The headset runs tsecho (UDP echo with kernel receive timestamps, TCP sink). A 32-byte UDP probe goes every 2 ms
while a TCP stream paced every 1 ms carries the load. Per probe: down = headset kernel rx - PC send,
up = PC rx - headset send, proc = headset send - headset kernel rx. Clock offset and drift are removed with a line
through the 5-second minima, so 'excess' is the delay above the run's floor in that direction.
Lost probes are split by the headset's own log: never received (lost down) or received, no reply (lost up)."""
import os
import socket
import struct
import subprocess
import sys
import time

ADB = os.environ.get('ADB', 'adb')   # the adb executable (Android SDK platform-tools)
HS = []  # adb itself picks the headset by ANDROID_SERIAL when several devices are attached
seconds, mbps, label, outdir = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3], sys.argv[4]
os.makedirs(outdir, exist_ok=True)


def adb(*args, **kw):
    return subprocess.run([ADB, *HS, *args], capture_output=True, text=True, **kw)


ip = None
for w in adb('shell', 'ip -4 addr show wlan0').stdout.split():
    if '/' in w and w[0].isdigit():
        ip = w.split('/')[0]
if not ip:
    raise SystemExit('no wlan0 IPv4 address')
adb('shell', 'pkill -f tsecho')
srv = subprocess.Popen([ADB, *HS, 'shell', '/data/local/tmp/tsecho -o /data/local/tmp/tsecho.bin'],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
if 'ready' not in srv.stdout.readline():
    raise SystemExit('tsecho did not start')

u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
u.setblocking(False)
sent, got = {}, {}


def drain():
    while True:
        try:
            data = u.recv(256)
        except (BlockingIOError, OSError):
            return
        t = time.perf_counter_ns()
        if len(data) >= 16 + 24:
            seq, _ = struct.unpack_from('<Qq', data)
            tk, tu, ts = struct.unpack_from('<qqq', data, len(data) - 24)
            if seq in sent and seq not in got:
                got[seq] = (t, tk, tu, ts)


load = None
if mbps > 0:
    load = socket.create_connection((ip, 5561))
    load.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
chunk = bytes(int(mbps * 1e6 / 8 * 0.001)) if mbps > 0 else b''
pad = bytes(16)
t0 = time.perf_counter()
wall0 = time.time()
stop = t0 + seconds
next_load = next_probe = t0
seq = 0
while True:
    drain()
    now = time.perf_counter()
    if now >= stop:
        break
    if now >= next_probe:
        ns = time.perf_counter_ns()
        sent[seq] = ns
        u.sendto(struct.pack('<Qq', seq, ns) + pad, (ip, 5562))
        seq += 1
        next_probe += 0.002
    if load and now >= next_load:
        load.sendall(chunk)
        next_load += 0.001
        if time.perf_counter() > next_load + 0.05:
            next_load = time.perf_counter()
end = time.perf_counter() + 0.8
while time.perf_counter() < end:
    drain()
if load:
    load.close()
adb('shell', 'pkill -f tsecho')
srv.kill()
logpath = os.path.join(outdir, 'tsecho.bin')
subprocess.run([ADB, *HS, 'pull', '/data/local/tmp/tsecho.bin', logpath], capture_output=True)
hsrx = {}
data = open(logpath, 'rb').read() if os.path.exists(logpath) else b''
for i in range(0, len(data) - 15, 16):
    s, tk = struct.unpack_from('<Qq', data, i)
    hsrx.setdefault(s, tk)

# raw one-way series (ms) with time since start (s)
series = []
for s in range(seq):
    if s in got:
        t, tk, tu, ts = got[s]
        series.append((s, (sent[s] - sent[0]) / 1e9, (tk - sent[s]) / 1e6, (t - ts) / 1e6, (ts - tk) / 1e6, (t - sent[s]) / 1e6))


def floor_line(idx):
    pts = {}
    for row in series:
        w = int(row[1] // 5)
        if w not in pts or row[idx] < pts[w][1]:
            pts[w] = (row[1], row[idx])
    xs, ys = zip(*pts.values())
    n, mx, my = len(xs), sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs) or 1
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return lambda x: my + k * (x - mx)


fd, fu = floor_line(2), floor_line(3)
ex = {r[0]: (r[2] - fd(r[1]), r[3] - fu(r[1]), r[4], r[5]) for r in series}
lost_down = [s for s in range(seq) if s not in got and s not in hsrx]
lost_up = [s for s in range(seq) if s not in got and s in hsrx]

# stalls: runs of probes that are lost or have RTT > 20 ms
runs, cur = [], None
for s in range(seq):
    bad = s not in got or ex[s][3] > 20
    if bad:
        cur = [s, s] if cur is None else [cur[0], s]
    elif cur:
        runs.append(cur)
        cur = None
if cur:
    runs.append(cur)
stalls = [r for r in runs if (sent[r[1]] - sent[r[0]]) / 1e6 + 20 >= 30]


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p / 100 * len(vals)))] if vals else float('nan')


span = seconds
dn = [v[0] for v in ex.values()]
up = [v[1] for v in ex.values()]
pr = [v[2] for v in ex.values()]
per_min = 60 / span
lines = ['%s [%.0f s, load %.0f Mbit/s]: probes %d, replies %d; lost down %d (%.2f%%), lost up %d (%.2f%%); '
         'excess ms down p99 %.1f p99.9 %.1f max %.0f | up p99 %.1f p99.9 %.1f max %.0f | headset proc p99.9 %.2f max %.1f; '
         'probes with down excess >20 ms %.1f/min, up >20 ms %.1f/min; stalls >= 30 ms %.1f/min' % (
             label, span, mbps, seq, len(got), len(lost_down), 100 * len(lost_down) / seq, len(lost_up), 100 * len(lost_up) / seq,
             pct(dn, 99), pct(dn, 99.9), max(dn), pct(up, 99), pct(up, 99.9), max(up), pct(pr, 99.9), max(pr),
             sum(1 for v in dn if v > 20) * per_min, sum(1 for v in up if v > 20) * per_min, len(stalls) * per_min)]
for a, b in stalls:
    rows = [ex[s] for s in range(a, b + 1) if s in ex]
    ld = sum(1 for s in range(a, b + 1) if s in lost_down)
    lu = sum(1 for s in range(a, b + 1) if s in lost_up)
    w = wall0 + (sent[a] - sent[0]) / 1e9
    lines.append('  stall at %6.2f s (PC %s): %d probes, lost down %d up %d; max excess down %.0f ms, up %.0f ms, proc %.1f ms' % (
        (sent[a] - sent[0]) / 1e9, time.strftime('%H:%M:%S', time.localtime(w)), b - a + 1, ld, lu,
        max((r[0] for r in rows), default=float('nan')), max((r[1] for r in rows), default=float('nan')),
        max((r[2] for r in rows), default=float('nan'))))
with open(os.path.join(outdir, 'owprobe.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
with open(os.path.join(outdir, 'raw.csv'), 'w') as f:  # raw clocks: PC perf_counter ns, headset CLOCK_REALTIME ns
    f.write('seq,pc_send,pc_rx,hs_krx,hs_send\n')
    for s in range(seq):
        g = got.get(s)
        f.write('%d,%d,%s,%s,%s\n' % (s, sent[s], g[0] if g else '', g[1] if g else hsrx.get(s, ''), g[3] if g else ''))
with open(os.path.join(outdir, 't0.txt'), 'w') as f:  # perf_counter_ns of probe 0, to line up other PC-side logs
    f.write('%d\n' % sent[0])
with open(os.path.join(outdir, 'lost.csv'), 'w') as f:
    f.write('seq,t_s,dir\n')
    for s in lost_down:
        f.write('%d,%.4f,down\n' % (s, (sent[s] - sent[0]) / 1e9))
    for s in lost_up:
        f.write('%d,%.4f,up\n' % (s, (sent[s] - sent[0]) / 1e9))
with open(os.path.join(outdir, 'owseries.csv'), 'w', encoding='utf-8') as f:
    f.write('seq,t_s,down_excess_ms,up_excess_ms,proc_ms,rtt_ms\n')
    for s in range(seq):
        if s in ex:
            f.write('%d,%.4f,%.3f,%.3f,%.3f,%.3f\n' % (s, (sent[s] - sent[0]) / 1e9, *ex[s]))
print('\n'.join(lines))
