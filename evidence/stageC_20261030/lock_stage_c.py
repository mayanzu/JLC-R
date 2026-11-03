"""Freeze runner/protocol hashes into study_lock.json after a successful pilot."""
from pathlib import Path
import datetime, hashlib, json

HERE = Path(__file__).resolve().parent
STAGE_B = HERE.parent / 'stageB_20261030'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    pilot = json.loads((HERE / 'pilot' / 'completion.json').read_text(encoding='utf8'))
    if pilot['status'] != 'COMPLETE':
        raise SystemExit('Pilot failed; lock refused')
    lock = {
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'runner_sha256': sha(HERE / 'run_stage_c.py'),
        'protocol_sha256': sha(HERE / 'protocol_predefined.json'),
        'stage_b_protocol_sha256': sha(STAGE_B / 'protocol_predefined.json'),
        'pilot_completion_sha256': sha(HERE / 'pilot' / 'completion.json'),
        'note': 'confirmation requires these hashes to match run_stage_c.py and protocol_predefined.json',
    }
    (HERE / 'study_lock.json').write_text(json.dumps(lock, indent=2) + '\n', encoding='utf8')
    print(json.dumps(lock, indent=2))

if __name__ == '__main__':
    main()
