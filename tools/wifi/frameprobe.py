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
    # FP_IP: another address of the headset, e.g. its USB link-local 'fe80::…%<PC ifIndex>' for a run over the cable
    ip = os.environ.get('FP_IP') or next((w.split('/')[0] for w in adb('shell', 'ip -4 addr show wlan0').stdout.split()
                                          if '/' in w and w[0].isdigit()), None)
    if not ip:
        raise SystemExit('no wlan0 IPv4 address')
    adb('shell', 'pkill -f tsecho')
    srv = subprocess.Popen([ADB, *HS, 'shell', '/data/local/tmp/tsecho -o /data/local/tmp/tsecho.bin -fo /data/local/tmp/frames.bin'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if 'ready' not in srv.stdout.readline():
        raise SystemExit('tsecho did not start')

tcp = socket.create_connection((ip, 5563))
tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
fam, _, _, _, udst = socket.getaddrinfo(ip, 5562, type=socket.SOCK_DGRAM)[0]
u = socket.socket(fam, socket.SOCK_DGRAM)
u.setblocking(False)
socks = [u]
vport = int(os.environ.get('FP_VIPORT', 0))  # odd probes go from this source port; a QoS policy can mark it (DSCP 46)
if vport:
    u2 = socket.socket(fam, socket.SOCK_DGRAM)
    u2.bind(('::' if fam == socket.AF_INET6 else '0.0.0.0', vport))
    u2.setblocking(False)
    socks.append(u2)
size = int(mbps * 1e6 / 8 / hz)
payload = bytes(size)
period = 1 / hz
sent, blocked = {}, {}
psent, pgot, phs = {}, {}, {}
chirps = []


def chirp(tag):
    """FP_CHIRP: three UDP packets of odd sizes, 20 ms apart, on a quiet link, to find this run in a sniffer capture."""
    for n in (1111, 1222, 1333):
        chirps.append((tag, n, time.perf_counter_ns()))
        u.sendto(struct.pack('<Q', 1 << 62) + bytes(n - 8), udst)
        time.sleep(0.02)
    time.sleep(0.3)


if os.environ.get('FP_CHIRP'):
    chirp('start')
t0 = time.perf_counter()
stop = t0 + seconds
with open(os.path.join(outdir, 't0.txt'), 'w') as f:
    f.write('%.6f\n' % time.time())  # PC wall clock at t = 0, to line frames up with logs from the AP
nf = t0
npb = t0
seq = pseq = 0
def got(d):
    s = struct.unpack_from('<Q', d)[0]
    if s in psent and s not in pgot:
        pgot[s] = time.perf_counter_ns()
        if len(d) >= 56:
            phs[s] = struct.unpack_from('<qqq', d, 32)  # receiver's kernel receive time (0 if none), user receive, send


while time.perf_counter() < stop:
    for sk in socks:
        while True:
            try:
                d = sk.recv(256)
            except (BlockingIOError, OSError):
                break
            got(d)
    now = time.perf_counter()
    if now >= npb:
        psent[pseq] = time.perf_counter_ns()
        socks[pseq % len(socks)].sendto(struct.pack('<Qq', pseq, psent[pseq]) + bytes(16), udst)
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
if os.environ.get('FP_CHIRP'):
    time.sleep(0.3)
    chirp('end')
    with open(os.path.join(outdir, 'chirp.txt'), 'w') as f:
        f.write('sent0 0 %d\n' % sent[0])  # PC perf_counter ns of frame 0 (t_s = 0 in frames.csv)
        for c in chirps:
            f.write('%s %d %d\n' % c)
end = time.perf_counter() + 1.0
while time.perf_counter() < end:
    idle = True
    for sk in socks:
        try:
            got(sk.recv(256))
            idle = False
        except (BlockingIOError, OSError):
            pass
    if idle:
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
# each UDP probe one way: PC -> headset (to its kernel receive time, or user time if it has none) and headset -> PC,
# with offset and drift removed like for the frames
def excess(pairs):
    mins = {}
    for t, d in pairs:
        w = int(t // 5)
        if w not in mins or d < mins[w][1]:
            mins[w] = (t, d)
    if len(mins) < 2:
        return {}
    xs, ys = zip(*mins.values())
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sum((x - mx) ** 2 for x in xs) or 1)
    return {t: (d - (my + k * (t - mx))) / 1e6 for t, d in pairs}


pt = {s: (psent[s] - sent[0]) / 1e9 for s in psent}
down = excess([(pt[s], (phs[s][0] or phs[s][1]) - psent[s]) for s in phs])
up = excess([(pt[s], pgot[s] - phs[s][2]) for s in phs])
with open(os.path.join(outdir, 'probes.csv'), 'w') as f:
    f.write('seq,t_s,down_ms,up_ms,via\n')  # via 1: sent from FP_VIPORT
    for s in sorted(psent):
        t = pt[s]
        f.write('%d,%.4f,%s,%s,%d\n' % (s, t, '%.3f' % down[t] if t in down else '', '%.3f' % up[t] if t in up else '',
                                      s % len(socks)))
dv = sorted(v for t, v in down.items() if t >= WARM) or [0]
uv = sorted(v for t, v in up.items() if t >= WARM) or [0]
line += '; probes one way, excess ms: down p99.9 %.1f max %.1f, up p99.9 %.1f max %.1f' % (
    dv[min(len(dv) - 1, int(0.999 * len(dv)))], dv[-1], uv[min(len(uv) - 1, int(0.999 * len(uv)))], uv[-1])
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
