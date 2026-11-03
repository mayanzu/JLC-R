"""Standalone source copied into src after prepare; no simulation on import."""
import math
def maximum_symmetric(c,header_bits=64):
    window=c['round_seconds']-max(range(0,int(c['round_seconds']),int(c['sync_interval_s'])))-c['sync_listen_s']
    n=c['nodes'];guard=c['guard_listen_s'];sync=c['sync_listen_s'];frame=(c['packet_bits']+header_bits)/c['bitrate_bps']
    feasible=[]
    for slots in range(1,int(math.floor((c['ch_listen_s']-sync)/guard+1e-9))+1):
        listen=sync+slots*guard;envelope=n*(listen-sync)+n*slots*frame
        if envelope<=window+1e-12:feasible.append((slots,listen,envelope))
    if not feasible:raise ValueError('no symmetric active radio slot fits')
    slots,listen,envelope=feasible[-1]
    return dict(slots=slots,listening_s=listen,envelope_s=envelope,window_s=window,
                next_slot_envelope_s=n*(slots+1)*(guard+frame))
