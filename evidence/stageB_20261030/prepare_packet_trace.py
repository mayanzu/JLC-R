"""Lock a small post hoc observational replay; no simulation is launched here."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

H = Path(__file__).resolve().parent
parent = H / 'protocol_predefined.json'
p = json.loads(parent.read_text(encoding='utf8'))
cells = [('WINTER_G20', .7), ('T3_G20', 1.), ('T3_G20', .7)]
seeds = p['seeds'][:3]  # fixed parent-protocol order, no outcome-based selection
cases = []
for seed in seeds:
    for condition, supply in cells:
        ref = [c for c in p['cases'] if c['method'] == 'JLC-R' and c['seed'] == seed
               and c['condition'] == condition and float(c['supply']) == supply]
        assert len(ref) == 1
        ref_dir = H / 'confirmation' / f"case_{ref[0]['index']:06d}"
        val = json.loads((ref_dir / 'validation.json').read_text(encoding='utf8'))
        assert val['status'] == 'PASS'
        hashes = {name: hashlib.sha256((ref_dir / name).read_bytes()).hexdigest()
                  for name in ('record.json', 'node_ledgers.csv', 'arrays.npz')}
        cases.append({'index': len(cases)+1, 'seed': seed, 'condition': condition,
                      'supply': supply, 'method': 'TRACE-DIAG', 'days': 14,
                      'reference_index': ref[0]['index'], 'reference_sha256': hashes})
spec = {
    'created_utc': datetime.now(timezone.utc).isoformat(),
    'classification': 'post hoc observational diagnostic, not a new confirmation or independent outcome',
    'purpose': 'observe source versus relay final packet holder and whether a forwarding hold was ever recorded',
    'selection': 'first three seeds in existing locked protocol, crossed with all three chosen winter cells',
    'scope': 'nine exact trajectory replays of already completed frozen JLC-R cases',
    'safety': 'instrumentation only; require exact original latest, battery and sample-status arrays and identical node ledgers',
    'limitations': ['The final holder and last reported block are descriptive, not causal attribution.',
                    'Nine cases do not estimate population-wide mechanism effects.',
                    'A recorded hold followed by delivery does not show that the hold caused delivery.',
                    'There is no downstream-aware cadence intervention in this diagnostic.'],
    'parent_protocol_sha256': hashlib.sha256(parent.read_bytes()).hexdigest(),
    'seeds': seeds, 'conditions': cells, 'cases': cases,
}
path = H / 'packet_trace_protocol.json'
if path.exists():
    raise SystemExit('Refusing to overwrite the observational plan')
path.write_text(json.dumps(spec, indent=2) + '\n', encoding='utf8')
print(json.dumps({'status': 'PREPARED', 'cases': len(cases), 'path': str(path),
                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, indent=2))
