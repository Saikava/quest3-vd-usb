"""survey.py <trace>: what is in a trace: the biggest producers of slices (process, thread, category, name), ftrace
event counts, logcat tags, counters."""
import sys
from perfetto.trace_processor import TraceProcessor
tp = TraceProcessor(trace=sys.argv[1])


def show(sql):
    rows = list(tp.query(sql))
    if not rows:
        print('(none)'); return
    cols = list(rows[0].__dict__.keys())
    print(' | '.join(cols))
    for r in rows:
        print(' | '.join(str(getattr(r, c))[:70] for c in cols))
    print()


show("select (max(ts)-min(ts))/1e9 as dur_s from sched")
show("""select p.name as proc, s.category, count(*) n from slice s
  left join thread_track tt on s.track_id = tt.id left join thread t using(utid) left join process p using(upid)
  group by 1,2 order by n desc limit 40""")
show("""select p.name as proc, t.name as thread, s.name, count(*) n, round(avg(dur)/1e6, 3) avg_ms from slice s
  left join thread_track tt on s.track_id = tt.id left join thread t using(utid) left join process p using(upid)
  group by 1,2,3 order by n desc limit 70""")
show("select name, count(*) n from ftrace_event group by 1 order by n desc limit 20")
show("select tag, count(*) n from android_logs group by 1 order by n desc limit 15")
show("select t.name, count(*) n from track t join counter c on c.track_id=t.id group by 1 order by n desc limit 30")
