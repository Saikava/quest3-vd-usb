"""pfcam.py <prefix> [window ms]: the repeated frames (<prefix>_stale.csv from pfstale.py) against the headset's log
(logcatE_<prefix>.txt, logcat -v epoch): the colour cameras' calibration starting and stopping ("for purpose ocal"),
and every other log line within the window (default 100 ms) before each repeated frame. And how often a random
moment of the same run is that near a camera start/stop, for comparison."""
import bisect
import re
import sys
from collections import Counter

prefix = sys.argv[1]
win = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
lines = open(prefix + '_stale.csv').read().splitlines()
off = int(lines[0].split('=')[1])
stale = [(int(l.split(',')[0]), float(l.split(',')[1]), l.split(',')[3]) for l in lines[2:] if l]

log = []   # (boot ms, line)
for l in open('logcatE_%s.txt' % prefix, errors='replace'):
    m = re.match(r'\s*(\d+\.\d+)\s', l)
    if m:
        log.append(((float(m.group(1)) * 1e9 - off) / 1e6, l.rstrip()))
lt = [x[0] for x in log]
cams = [(t, 'start' if 'Starting' in l else 'stop') for t, l in log if 'for purpose ocal' in l and
        ('Starting cameras' in l or 'Stopping cameras' in l)]
ct = [c[0] for c in cams]


def near_cam(t, w):
    i = bisect.bisect_left(ct, t - w)
    return [(c[0] - t, c[1]) for c in cams[i:] if c[0] <= t + w]


tags = Counter()
for d, t, late in stale:
    nc = near_cam(t, 500)
    print('display %d at %.3f ms (late %s ms): cameras %s' % (d, t, late, ', '.join('%s %+.0f ms' % (k, dt) for dt, k in nc) or '-'))
    i = bisect.bisect_left(lt, t - win)
    j = bisect.bisect_right(lt, t + 20)
    for tt, l in log[i:j]:
        tag = re.sub(r'^\s*\d+\.\d+\s+\d+\s+\d+\s+\w\s+', '', l)[:150]
        print('    %+7.1f  %s' % (tt - t, tag))
        tags[tag.split(':')[0]] += 1
if stale and ct:
    t0, t1 = stale[0][1] - 60000, stale[-1][1] + 60000
    for w in (100, 300, 500):
        hit = sum(1 for _, t, _ in stale if near_cam(t, w))
        # the share of the run within w of a camera start/stop
        cover = sum(1 for k in range(int(t0), int(t1), 10) if near_cam(k, w)) / max(1, (t1 - t0) / 10)
        print('within %d ms of a camera start/stop: %d of %d repeated frames; %.1f%% of the run' % (w, hit, len(stale), 100 * cover))
print('log tags before repeated frames:', tags.most_common(15))
