"""pfclock.py <trace> <prefix>: for a light trace (no compositor marks, so no pfstale.py), writes <prefix>_stale.csv
with only the clock line (realtime - boottime) and the header, so that pfdec.py / slowlog.py can read the run (its
repeated frames then come from logcat's VrApi lines: ../../vrapi90.py)."""
import sys
from perfetto.trace_processor import TraceProcessor
tp = TraceProcessor(trace=sys.argv[1])
clk = {r.clock_name: r.clock_value for r in tp.query("select clock_name, clock_value from clock_snapshot where snapshot_id = "
                                                     "(select min(snapshot_id) from clock_snapshot)")}
with open(sys.argv[2] + '_stale.csv', 'w') as o:
    o.write('# realtime_minus_boottime_ns=%d\n' % (clk['REALTIME'] - clk['BOOTTIME']))
    o.write('display,display_ms,frame,ingest_late_ms\n')
