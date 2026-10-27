"""frameprobe.py <seconds> <mbps> <hz> <label> <outdir>: a VD-like video stream from the PC to the headset over
Wi-Fi. Every 1/hz s the PC sends one frame of mbps/hz bits over a single TCP connection (header: "VRF1", length,
sequence, PC send time); tsecho on the headset logs when each frame's first and last byte arrived. A small UDP probe
every 2 ms keeps measuring the uplink alongside (replies from tsecho), like the headset's pose and ACK traffic.
Delivery = last byte at headset - PC send; offset and drift between the clocks are removed with a line through
5-second minima, so 'late' means later than the link's normal delivery time. The first 10 s are left out."""
import os
import socket
import struct
import subprocess
import sys
import time

ADB = os.environ.get('ADB', 'adb')   # the adb executable (Android SDK platform-tools)
HS = []  # adb itself picks the headset by ANDROID_SERIAL when several devices are attached
seconds, mbps, hz, label, outdir = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5]
os.makedirs(outdir, exist_ok=True)
WARM = 10.0


def adb(*a):
    return subprocess.run([ADB, *HS, *a], capture_output=True, text=True)


host = os.environ.get('FP_HOST')  # a laptop running framesink instead of the headset: no adb, log read from TCP 5564
if host:
    ip, srv = host, None
else:
    ip = next((w.split('/')[0] for w in adb('shell', 'ip -4 addr show wlan0').stdout.split() if '/' in w and w[0].isdigit()), None)
    if not ip:
        raise SystemExit('no wlan0 IPv4 address')
    adb('shell', 'pkill -f tsecho')
    srv = subprocess.Popen([ADB, *HS, 'shell', '/data/local/tmp/tsecho -o /data/local/tmp/tsecho.bin -fo /data/local/tmp/frames.bin'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if 'ready' not in srv.stdout.readline():
        raise SystemExit('tsecho did not start')

tcp = socket.create_connection((ip, 5563))
tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
u.setblocking(False)
size = int(mbps * 1e6 / 8 / hz)
payload = bytes(size)
period = 1 / hz
sent, blocked = {}, {}
psent, pgot = {}, {}
t0 = time.perf_counter()
stop = t0 + seconds
with open(os.path.join(outdir, 't0.txt'), 'w') as f:
    f.write('%.6f\n' % time.time())  # PC wall clock at t = 0, to line frames up with logs from the AP
nf = t0
npb = t0
seq = pseq = 0
while time.perf_counter() < stop:
    while True:
        try:
            d = u.recv(256)
        except (BlockingIOError, OSError):
            break
        s = struct.unpack_from('<Q', d)[0]
        if s in psent and s not in pgot:
            pgot[s] = time.perf_counter_ns()
    now = time.perf_counter()
    if now >= npb:
        psent[pseq] = time.perf_counter_ns()
        u.sendto(struct.pack('<Qq', pseq, psent[pseq]) + bytes(16), (ip, 5562))
        pseq += 1
        npb += 0.002
    if now >= nf:
        ns = time.perf_counter_ns()
        sent[seq] = ns
        a = time.perf_counter()
        tcp.sendall(b'VRF1' + struct.pack('<IQQ', size, seq, ns) + payload)
        blocked[seq] = (time.perf_counter() - a) * 1000
        seq += 1
        nf += period
        if time.perf_counter() > nf + 0.1:
            nf = time.perf_counter()  # far behind: do not burst to catch up
end = time.perf_counter() + 1.0
while time.perf_counter() < end:
    try:
        d = u.recv(256)
        s = struct.unpack_from('<Q', d)[0]
        if s in psent and s not in pgot:
            pgot[s] = time.perf_counter_ns()
    except (BlockingIOError, OSError):
        time.sleep(0.001)
tcp.close()
time.sleep(0.5)
fp = os.path.join(outdir, 'frames.bin')
if srv:
    adb('shell', 'pkill -f tsecho')
    srv.kill()
    subprocess.run([ADB, *HS, 'pull', '/data/local/tmp/frames.bin', fp], capture_output=True)
else:
    with socket.create_connection((ip, 5564)) as c, open(fp, 'wb') as f:
        while b := c.recv(1 << 16):
            f.write(b)
data = open(fp, 'rb').read() if os.path.exists(fp) else b''
recv = {}
for i in range(0, len(data) - 23, 24):
    s, first, last = struct.unpack_from('<Qqq', data, i)
    recv[s] = (first, last)

ts = lambda s: (sent[s] - sent[0]) / 1e9
rows = [(s, ts(s), recv[s][1] - sent[s], (recv[s][1] - recv[s][0]) / 1e6) for s in range(seq) if s in recv]
mins = {}
for s, t, d, _ in rows:
    w = int(t // 5)
    if w not in mins or d < mins[w][1]:
        mins[w] = (t, d)
xs, ys = zip(*mins.values())
mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sum((x - mx) ** 2 for x in xs) or 1)
ex = [(s, t, (d - (my + k * (t - mx))) / 1e6, dur) for s, t, d, dur in rows]
steady = [e for e in ex if e[1] >= WARM]
mins_measured = (max(e[1] for e in steady) - WARM) / 60 if steady else 0
vals = sorted(e[2] for e in steady)
p = lambda q: vals[min(len(vals) - 1, int(q / 100 * len(vals)))]
late = {th: sum(1 for v in vals if v > th) / mins_measured for th in (4, 8, 16, 33)}
missing = sum(1 for s in range(seq) if s not in recv and ts(s) >= WARM)
blk = sorted(v for s, v in blocked.items() if ts(s) >= WARM)
# uplink probe loss in the same window
pl = sum(1 for s in psent if (psent[s] - sent[0]) / 1e9 >= WARM and s not in pgot)
pn = sum(1 for s in psent if (psent[s] - sent[0]) / 1e9 >= WARM)
line = ('%s [%.1f min steady, %.0f Mbit/s, %.0f Hz, frame %d KB]: frames %d, missing %d; frame delivery excess ms p50 %.2f '
        'p99 %.2f p99.9 %.2f max %.1f; late frames/min >4 ms %.1f, >8 ms %.1f, >16 ms %.1f, >33 ms %.1f; '
        'sender blocked p99.9 %.1f ms max %.1f; udp probes lost (either way) %.3f%%') % (
    label, mins_measured, mbps, hz, size // 1024, len(steady), missing, p(50), p(99), p(99.9), vals[-1],
    late[4], late[8], late[16], late[33], blk[min(len(blk) - 1, int(0.999 * len(blk)))], blk[-1], 100 * pl / max(pn, 1))
with open(os.path.join(outdir, 'frames.csv'), 'w') as f:
    f.write('seq,t_s,excess_ms,recv_ms,blocked_ms\n')
    for s, t, e, dur in ex:
        f.write('%d,%.4f,%.3f,%.3f,%.3f\n' % (s, t, e, dur, blocked[s]))
with open(os.path.join(outdir, 'frameprobe.txt'), 'w') as f:
    f.write(line + '\n')
print(line)
for s, t, e, dur in ex:
    if t >= WARM and e > 16:
        print('  late frame %d at %.2f s: +%.1f ms (headset receive took %.1f ms, sender blocked %.1f ms)' % (s, t, e, dur, blocked[s]))
