"""pfstale.py <trace> <out prefix>: the headset's repeated frames in a Perfetto trace of a VD session, frame by frame.

The Quest compositor (com.oculus.vrruntimeservice, thread OVR::TimeWarp) composes each display frame in two screen
slices (SliceCpuStart: display frame index, screen slice), each a "TimeWarpSlice : F" with the app frame F it used;
it takes an app frame in "FetchFrameInternal : F" > "IngestFrame" after the app's xrEndFrame. VD's frame thread marks
"xrWaitFrame : F", "xrBeginFrame : F", "!xrEndFrame : F". A display frame whose first slice uses the same app frame
as the one before is a repeated (stale) frame; the frame that should have been there is the next one, G.

Writes <prefix>_frames.csv (per VD frame: when xrWaitFrame returned, xrEndFrame ended, the compositor ingested it,
the first display slice that used it; all in ms of the trace's boot clock) and <prefix>_stale.txt: per repeated
frame, how late G was and where its time went (the frame thread's states: running, runnable (and what ran on its
CPU instead), sleeping in which call; the compositor's wait for its GPU work), against the median frame."""
import bisect
import statistics
import sys
from collections import defaultdict

from perfetto.trace_processor import TraceProcessor

trace, out = sys.argv[1], sys.argv[2]
tp = TraceProcessor(trace=trace)


def rows(sql):
    return list(tp.query(sql))


def num(name, prefix):
    return int(float(name[len(prefix):]))


vd = rows("select tt.utid from slice s join thread_track tt on s.track_id = tt.id where s.name like 'xrWaitFrame : %' "
          "group by 1 order by count(*) desc limit 1")
if not vd:
    sys.exit('no VD frames in the trace')
vdu = vd[0].utid

# VD's frames
fr = defaultdict(dict)
for r in rows("select s.name, s.ts, s.dur from slice s join thread_track tt on s.track_id = tt.id where tt.utid = %d and "
              "(s.name like 'xrWaitFrame : %%' or s.name like 'xrBeginFrame : %%' or s.name like '!xrEndFrame : %%')" % vdu):
    if r.name.startswith('xrWaitFrame'):
        f = fr[num(r.name, 'xrWaitFrame : ')]; f['ws'] = r.ts; f['we'] = r.ts + r.dur
    elif r.name.startswith('xrBeginFrame'):
        fr[num(r.name, 'xrBeginFrame : ')]['bf'] = r.ts
    else:
        f = fr[num(r.name, '!xrEndFrame : ')]; f['es'] = r.ts; f['ee'] = r.ts + r.dur
for r in rows("select s.ts, p.name pn from slice s join slice p on s.parent_id = p.id where s.name = 'IngestFrame' and "
              "p.name like 'FetchFrameInternal : %'"):
    f = num(r.pn, 'FetchFrameInternal : ')
    if f in fr:
        fr[f].setdefault('ing', r.ts)
for r in rows("select s.ts, s.dur, s.name from slice s where s.name like 'WaitForClient : %'"):
    f = num(r.name, 'WaitForClient : ')
    if f in fr:
        fr[f].setdefault('wfc', r.dur)

# display slices: SliceCpuStart (display frame, screen slice) then that slice's TimeWarpSlice
starts = []
for r in rows("select s.ts, max(case when a.key = 'debug.frameIndex' then a.int_value end) d, "
              "max(case when a.key = 'debug.screenSlice' then a.int_value end) sl from slice s join args a using(arg_set_id) "
              "where s.name = 'SliceCpuStart' group by s.id order by s.ts"):
    starts.append((r.ts, r.d, r.sl))
st_ts = [s[0] for s in starts]
disp = {}   # display frame -> {slice: (ts, F)}
for r in rows("select ts, name from slice where name like 'TimeWarpSlice : %' order by ts"):
    i = bisect.bisect_right(st_ts, r.ts) - 1
    if i < 0:
        continue
    _, d, sl = starts[i]
    disp.setdefault(d, {})[sl] = (r.ts, num(r.name, 'TimeWarpSlice : '))
    f = fr.get(num(r.name, 'TimeWarpSlice : '))
    if f is not None and 'tw' not in f:
        f['tw'] = r.ts; f['disp'] = d

with open(out + '_frames.csv', 'w') as o:
    o.write('frame,wait_start_ms,wait_end_ms,begin_ms,end_start_ms,end_end_ms,ingest_ms,gpu_wait_ms,first_display_ms,display\n')
    for f in sorted(fr):
        x = fr[f]
        o.write('%d,%s,%s\n' % (f, ','.join('%.3f' % (x[k] / 1e6) if k in x else '' for k in
                                         ('ws', 'we', 'bf', 'es', 'ee', 'ing')),
                                ','.join([('%.3f' % (x['wfc'] / 1e6)) if 'wfc' in x else '',
                                          ('%.3f' % (x['tw'] / 1e6)) if 'tw' in x else '', str(x.get('disp', ''))])))

# typical frame
ok = [x for x in fr.values() if all(k in x for k in ('we', 'ee', 'ing', 'tw'))]
med = lambda v: statistics.median(v) if v else 0
work = med([x['ee'] - x['we'] for x in ok])
margin = med([x['tw'] - x['ing'] for x in ok])
wfc = med([x.get('wfc', 0) for x in ok])
waits = sorted(fr)
wint = med([fr[b]['we'] - fr[a]['we'] for a, b in zip(waits, waits[1:]) if b == a + 1 and 'we' in fr[a] and 'we' in fr[b]])

ds = sorted(d for d in disp if 0 in disp[d])
stale = []
for a, b in zip(ds, ds[1:]):
    if b != a + 1:
        continue
    fa, fb = disp[a][0][1], disp[b][0][1]
    if fb == fa:
        stale.append((b, fa + 1, disp[b][0][0]))
period = med([disp[b][0][0] - disp[a][0][0] for a, b in zip(ds, ds[1:]) if b == a + 1])
gaps = [(a, b) for a, b in zip(ds, ds[1:]) if b != a + 1]


def states(t0, t1):
    """The VD frame thread's states over [t0, t1]: list of (state, ms, cpu, blocked function, waker)."""
    res = []
    for r in rows("select ts, dur, state, cpu, io_wait, blocked_function bf, waker_utid wu from thread_state where utid = %d "
                  "and ts < %d and ts + dur > %d order by ts" % (vdu, t1, t0)):
        d = min(r.ts + r.dur, t1) - max(r.ts, t0)
        res.append((r.state, d / 1e6, r.cpu, r.bf, r.wu, max(r.ts, t0), min(r.ts + r.dur, t1)))
    return res


def in_slice(t0, t1):
    """The deepest slice of the VD frame thread covering most of [t0, t1]."""
    r = rows("select s.name, s.depth from slice s join thread_track tt on s.track_id = tt.id where tt.utid = %d and s.ts <= %d "
             "and s.ts + s.dur >= %d order by s.depth desc limit 1" % (vdu, (t0 + t1) // 2, (t0 + t1) // 2))
    return r[0].name if r else '-'


def who_ran(cpu, t0, t1):
    if cpu is None:
        return ''
    r = rows("select coalesce(p.name, t.name) n, t.name tn, sum(min(s.ts + s.dur, %d) - max(s.ts, %d)) d from sched s join thread t "
             "using(utid) left join process p using(upid) where s.cpu = %d and s.ts < %d and s.ts + s.dur > %d and s.utid != 0 "
             "group by 1, 2 order by d desc limit 3" % (t1, t0, cpu, t1, t0))
    return ', '.join('%s/%s %.2f' % (x.n, x.tn, x.d / 1e6) for x in r)


def tname(u):
    if u is None:
        return ''
    r = rows("select t.name tn, p.name pn from thread t left join process p using(upid) where t.utid = %d" % u)
    return '%s/%s' % (r[0].pn, r[0].tn) if r else ''


# the boot clock against the wall clock (logcat -v epoch), and the repeated frames in a list
clk = {r.clock_name: r.clock_value for r in rows("select clock_name, clock_value from clock_snapshot where snapshot_id = "
                                                 "(select min(snapshot_id) from clock_snapshot)")}
with open(out + '_stale.csv', 'w') as o:
    o.write('# realtime_minus_boottime_ns=%d\n' % (clk['REALTIME'] - clk['BOOTTIME']))
    o.write('display,display_ms,frame,ingest_late_ms\n')
    for d, g, tdisp in stale:
        x = fr.get(g, {})
        o.write('%d,%.3f,%d,%s\n' % (d, tdisp / 1e6, g, ('%.3f' % ((x['ing'] - tdisp) / 1e6)) if 'ing' in x else ''))

with open(out + '_stale.txt', 'w') as o:
    span =(ds[-1] - ds[0] + 1) * period / 6e10 if ds else 0
    o.write('display frames %d (%.2f min, period %.3f ms); repeated %d (%.2f/min); display gaps %s\n' % (
        len(ds), span, period / 1e6, len(stale), len(stale) / span if span else 0, gaps[:10]))
    o.write('median VD frame: xrWaitFrame interval %.3f ms, its work (xrWaitFrame return to xrEndFrame end) %.3f ms, '
            'ingest to display %.3f ms, compositor GPU wait %.3f ms\n\n' % (wint / 1e6, work / 1e6, margin / 1e6, wfc / 1e6))
    for d, g, tdisp in stale:
        x = fr.get(g, {})
        o.write('display %d at %.3f ms: frame %d ' % (d, tdisp / 1e6, g))
        if 'ing' not in x:
            o.write('never ingested; %s\n' % ({k: round(v / 1e6, 3) for k, v in x.items()}))
            continue
        o.write('ingested %.3f ms late (shown at display %s)\n' % ((x['ing'] - tdisp) / 1e6, x.get('disp')))
        p = fr.get(g - 1, {})
        if 'we' in x and 'we' in p:
            o.write('  xrWaitFrame returned %.3f ms after the last (median %.3f); work %.3f ms (median %.3f); '
                    'xrEndFrame end to ingest %.3f ms; compositor GPU wait %.3f ms\n' % (
                        (x['we'] - p['we']) / 1e6, wint / 1e6, (x['ee'] - x['we']) / 1e6, work / 1e6,
                        (x['ing'] - x['ee']) / 1e6, x.get('wfc', 0) / 1e6))
        t0 = x.get('we', x.get('ws', x['ing'] - 10 ** 7))
        tot = defaultdict(float)
        for stt, ms, cpu, bf, wu, a, b in states(t0, x['ing']):
            tot[stt] += ms
            if ms >= 0.3:
                extra = ''
                if stt in ('R', 'R+'):
                    extra = ' cpu %s: %s' % (cpu, who_ran(cpu, a, b))
                elif stt in ('S', 'D'):
                    extra = ' in %s%s; woken by %s' % (in_slice(a, b), (' (' + bf + ')') if bf else '', tname(wu))
                elif stt == 'Running':
                    extra = ' cpu %s in %s' % (cpu, in_slice(a, b))
                o.write('    %+.3f ms: %s %.3f ms%s\n' % ((a - t0) / 1e6, stt, ms, extra))
        o.write('  states: %s\n' % ', '.join('%s %.3f' % (k, v) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])))

# everything VD's process and the compositor did around each repeated frame (from the last frame's xrWaitFrame return
# to the late frame's ingest), slices of 0.1 ms and more, times in ms from the repeated display slice
with open(out + '_detail.txt', 'w') as o:
    for d, g, tdisp in stale:
        x, p = fr.get(g, {}), fr.get(g - 1, {})
        t0 = p.get('we', tdisp - 2 * period)
        t1 = x.get('ing', tdisp + 2 * period) + 10 ** 6
        o.write('== display %d, frame %d\n' % (d, g))
        for r in rows("select s.ts, s.dur, s.depth, s.name, t.name tn, p.name pn from slice s join thread_track tt on s.track_id = "
                      "tt.id join thread t using(utid) left join process p using(upid) where (p.name like 'VirtualDesktop%%' or "
                      "t.name = 'OVR::TimeWarp' or p.name like 'media.%%') and s.ts < %d and s.ts + s.dur > %d and (s.dur >= 100000 or "
                      "s.name like 'onWorkDone%%' or s.name like 'CCodecBufferChannel::onWorkDone%%' or s.name like 'TimeWarpSlice%%' "
                      "or s.name like 'IngestFrame%%' or s.name = 'acquireBuffer') order by s.ts" % (t1, t0)):
            o.write('  %+8.3f %7.3f  %-28s %s%s\n' % ((r.ts - tdisp) / 1e6, r.dur / 1e6, (r.pn or '')[-12:] + '/' + (r.tn or ''),
                                                    '  ' * r.depth, r.name[:110]))
print(open(out + '_stale.txt').read()[:3000])
