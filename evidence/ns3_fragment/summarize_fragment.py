"""Summarize all predefined ns-3 sender trials without treating senders as independent runs."""
from pathlib import Path
import csv,hashlib,json,statistics
import numpy as np
h=Path(__file__).resolve().parent
path=h/'fragment_trials_128.csv'
with path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
assert len(rows)==896
records=[]
for mode in ('single','serial','contending','hidden'):
    selected=[r for r in rows if r['mode']==mode]
    expected=128 if mode=='single' else 256
    assert len(selected)==expected
    groups={}
    for row in selected:
        run=int(row['run']); sender=int(row['sender'])
        assert 1<=run<=128 and sender in (1,2)
        assert int(row['mtu'])==114 and int(row['confirms'])==5
        assert sum(int(row[k]) for k in ('ack_success','no_ack','access_fail','other'))==5
        assert int(row['bad_payloads'])==0
        assert (int(row['distinct_fragments'])==5)==bool(int(row['message_received']))
        groups.setdefault(run,[]).append(row)
    assert set(groups)==set(range(1,129))
    assert all(len(x)==(1 if mode=='single' else 2) for x in groups.values())
    success=[r for r in selected if int(r['message_received'])]
    times=np.asarray([float(r['reassembly_ms']) for r in success],float)
    confirms=np.asarray([float(r['confirm_ms']) for r in selected],float)
    values=lambda field:np.asarray([float(r[field]) for r in selected],float)
    group_energy=[]
    for g in groups.values():
        assert len(set(r['group_radio_energy_j'] for r in g))==1
        group_energy.append(float(g[0]['group_radio_energy_j']))
    records.append({
        'mode':mode,'independent_rng_runs':len(groups),'sender_messages':len(selected),
        'messages_received_pct':100*sum(int(r['message_received']) for r in selected)/len(selected),
        'all_frames_acked_pct':100*sum(int(r['all_sender_acks']) for r in selected)/len(selected),
        'mean_confirm_ms':float(np.mean(confirms)),'median_confirm_ms':float(np.median(confirms)),
        'median_reassembly_ms_given_success':float(np.median(times)) if len(times) else None,
        'p95_reassembly_ms_given_success':float(np.quantile(times,.95)) if len(times) else None,
        'successful_messages_over_20ms_pct':100*float(np.mean(times>20)) if len(times) else None,
        'mean_sender_phy_frames':float(values('sender_phy_tx_frames').mean()),
        'mean_sender_phy_mac_bytes':float(values('sender_phy_tx_bytes').mean()),
        'no_ack_confirmations':int(values('no_ack').sum()),
        'channel_access_fail_confirmations':int(values('access_fail').sum()),
        'mean_group_modeled_rf_energy_j':float(np.mean(group_energy))
    })
out=h/'fragment_summary.csv'
with out.open('w',encoding='utf8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
receipt={'status':'PASS','source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
         'summary_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
         'independent_runs_per_scenario':128,'total_sender_messages':len(rows),
         'validation':'5 final confirmations per sender, all statuses counted, no invalid fragments, 114-byte MTU, correct sender/run counts',
         'interpretation':'PHY frame bytes exclude the PHY preamble/SFD/PHR; no exact retransmission count can be inferred from the aggregate frame counts when CCA failures occur. Group energy is once per run, not once per sender. RF current mapping is illustrative.',
         'scope':'three-node component test only; not a full-network performance evaluation'}
(h/'fragment_summary_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
print(json.dumps(records,indent=2))
