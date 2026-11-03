"""Freeze the post hoc observational replay before starting it."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

H = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
out = H / 'packet_trace_lock.json'
if out.exists():
    raise SystemExit('Refusing to overwrite trace lock')
plan = json.loads((H / 'packet_trace_protocol.json').read_text(encoding='utf8'))
assert len(plan['cases']) == 9 and plan['classification'].startswith('post hoc')
lock = {'created_utc': datetime.now(timezone.utc).isoformat(),
        'protocol_sha256': sha(H / 'packet_trace_protocol.json'),
        'runner_sha256': sha(H / 'run_packet_trace.py'),
        'base_runner_sha256': sha(H / 'run_stage_b.py')}
out.write_text(json.dumps(lock, indent=2) + '\n', encoding='utf8')
print(json.dumps(lock, indent=2))
