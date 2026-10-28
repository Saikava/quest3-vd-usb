"""sniffsum.py <rec.bin>: overview of a parsed capture: per transmitter frames, bytes, retries, rates, signal; time span."""
import collections
import struct
import sys

REC = struct.Struct('<qqHHHHBBHBbIBHHQ')
src = sys.argv[1]
macs = open(src + '.macs').read().split()
data = open(src, 'rb').read()
n = len(data) // REC.size
by = collections.defaultdict(lambda: [0, 0, 0, collections.Counter(), 0, collections.Counter()])
t_first = t_last = None
tsft_zero = 0
for i in range(n):
    pts, tsft, fc, a1, a2, ln, mcs, nss, bw, sgi, sig, ref, fl = REC.unpack_from(data, i * REC.size)[:13]
    if t_first is None:
        t_first = pts
    t_last = pts
    tsft_zero += tsft == 0
    typ, sub = (fc >> 2) & 3, (fc >> 4) & 15
    key = (macs[a2] if a2 != 0xffff else '-', 'mgt' if typ == 0 else 'ctl%d' % sub if typ == 1 else 'data')
    e = by[key]
    e[0] += 1
    e[1] += ln
    e[2] += 1 if fc & 0x0800 else 0
    e[3]['%s/%s/%s' % (mcs, nss, bw)] += 1
    e[4] += sig
    e[5][macs[a1]] += 1
print('records %d, span %.1f s, tsft missing in %d' % (n, (t_last - t_first) / 1e6, tsft_zero))
for key, e in sorted(by.items(), key=lambda x: -x[1][1])[:30]:
    print('%-17s %-5s frames %8d  MB %8.1f  retry %5.1f%%  sig %4.0f  rates %s  to %s' % (
        key[0], key[1], e[0], e[1] / 1e6, 100 * e[2] / e[0], e[4] / e[0], e[3].most_common(3), e[5].most_common(2)))
