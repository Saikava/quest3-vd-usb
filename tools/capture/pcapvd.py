"""pcapvd.py <vd.pcapng> <timemap.txt> <qpc time> [before after]: VD's TCP connections on the USB network
around a moment (a game freeze, in QPC seconds): per connection and direction, segments and bytes in 10 ms
bins, retransmissions, zero windows and window sizes. Directions: 'pc>' PC to headset, '<hmd' headset to PC."""
import struct
import sys
from collections import defaultdict

path, tmap, tq = sys.argv[1], sys.argv[2], float(sys.argv[3])
before = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3
after = float(sys.argv[5]) if len(sys.argv) > 5 else 0.6
maps = [tuple(map(float, l.split()[1:3])) for l in open(tmap) if l.startswith('map')]
(e0, q0), (e1, q1) = maps[0], maps[-1]
t_epoch = e0 + (tq - q0) * (e1 - e0) / (q1 - q0)

data = open(path, 'rb').read()
pos = 0
tsres = {}
ifcount = 0
pkts = []  # (t, src_port, dst_port, seq, ack, flags, win, plen, from_pc)
pc_prefix = None
while pos + 8 <= len(data):
    btype, blen = struct.unpack_from('<II', data, pos)
    if blen < 12:
        break
    body = data[pos + 8:pos + blen - 4]
    if btype == 1:  # interface description
        res = 1e-6
        o = 8
        while o + 4 <= len(body):
            code, ln = struct.unpack_from('<HH', body, o)
            if code == 0:
                break
            if code == 9:
                v = body[o + 4]
                res = 2.0 ** -(v & 0x7f) if v & 0x80 else 10.0 ** -v
            o += 4 + ((ln + 3) & ~3)
        tsres[ifcount] = res
        ifcount += 1
    elif btype == 6:  # enhanced packet
        ifid, th, tl, cap, orig = struct.unpack_from('<IIIII', body, 0)
        t = ((th << 32) | tl) * tsres.get(ifid, 1e-6)
        p = body[20:20 + cap]
        if len(p) >= 14 + 40 + 20 and p[12:14] == b'\x86\xdd' and p[14 + 6] == 6:
            ip = p[14:]
            plen = struct.unpack_from('>H', ip, 4)[0]
            src, dst = ip[8:24], ip[24:40]
            tcp = ip[40:]
            sp, dp, seq, ack, off, flags, win = struct.unpack_from('>HHIIBBH', tcp, 0)
            hl = (off >> 4) * 4
            pkts.append((t, sp, dp, seq, ack, flags, win, plen - hl, src, dst))
    pos += blen

# the PC's side: VD's ports 38810..38840
conns = defaultdict(list)
for t, sp, dp, seq, ack, flags, win, ln, src, dst in pkts:
    if 38800 <= sp <= 38850:
        conns[(sp, dp, 'pc>')].append((t, seq, ack, flags, win, ln))
    elif 38800 <= dp <= 38850:
        conns[(dp, sp, '<hmd')].append((t, seq, ack, flags, win, ln))
print('%d TCP packets, capture %.1f s, moment at epoch %.3f' % (len(pkts), pkts[-1][0] - pkts[0][0], t_epoch))

for key in sorted(conns):
    ps = conns[key]
    # dedupe (pktmon may log a packet twice)
    seen = set()
    uniq = []
    for p in ps:
        k = (p[1], p[2], p[3], p[5], round(p[0], 3))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    ps = uniq
    tot = sum(p[5] for p in ps)
    span = ps[-1][0] - ps[0][0] if len(ps) > 1 else 1
    print('\nport %d<->%d %s: %d segments, %.1f Mbit/s average' % (key[0], key[1], key[2], len(ps), tot * 8 / span / 1e6))
    # retransmissions over the whole capture and in the window
    hi = None
    rtx = []
    for t, seq, ack, flags, win, ln in ps:
        if ln > 0:
            end = (seq + ln) & 0xffffffff
            if hi is not None and ((end - hi) & 0xffffffff) > 0x7fffffff or (hi is not None and end == hi):
                rtx.append(t)
            else:
                hi = end
    zw = [p[0] for p in ps if p[4] == 0 and not p[3] & 0x04]
    print('  retransmitted segments: %d in all, %s in the window; zero windows: %d in all, %d in the window' % (
        len(rtx), len([t for t in rtx if t_epoch - before <= t <= t_epoch + after]), len(zw),
        len([t for t in zw if t_epoch - before <= t <= t_epoch + after])))
    w = [p for p in ps if t_epoch - before <= p[0] <= t_epoch + after]
    if not w:
        print('  nothing in the window')
        continue
    bins = defaultdict(lambda: [0, 0, 1 << 30, 0])
    for t, seq, ack, flags, win, ln in w:
        b = int((t - t_epoch) * 100)  # 10 ms
        bins[b][0] += 1
        bins[b][1] += ln
        bins[b][2] = min(bins[b][2], win)
        if t in rtx:
            bins[b][3] += 1
    line = []
    for b in range(int(-before * 100), int(after * 100)):
        if b in bins:
            n, by, mw, r = bins[b]
            line.append('%+d:%d/%dk%s' % (b * 10, n, by // 1000, ' R%d' % r if r else ''))
        else:
            line.append('%+d:-' % (b * 10))
    print('  10 ms bins (ms from the moment: segments/kbytes):')
    for i in range(0, len(line), 15):
        print('   ', ' '.join(line[i:i + 15]))
    gaps = [(b[0] - a[0], a[0] - t_epoch) for a, b in zip(w, w[1:]) if b[0] - a[0] > 0.03]
    print('  silences > 30 ms: ' + ', '.join('%.0f ms from %+.0f ms' % (1000 * g, 1000 * s) for g, s in gaps))
