"""q.py <trace> <sql>...: run queries on a trace, print the rows."""
import sys
from perfetto.trace_processor import TraceProcessor
tp = TraceProcessor(trace=sys.argv[1])
for sql in sys.argv[2:]:
    rows = list(tp.query(sql))
    if not rows:
        print('(none)\n'); continue
    cols = list(rows[0].__dict__.keys())
    print(' | '.join(cols))
    for r in rows:
        print(' | '.join(str(getattr(r, c))[:90] for c in cols))
    print()
