"""Only public reference topology and already announced cache fields."""
def reference_upstreams(s,j):
    ph=s.phase(s.t)
    return [int(u) for u in s.ch if int(u)!=j and int(s.reference_next[ph][u])==j and j in s.neighbors.get(int(u),[])]
def cached_ready(s,u,j):
    cost=s.tx_energy(u,j)+s.control_cost(u,j)[0]
    return bool(s.last_message[u]==s.t and not s.cached_off[u] and s.cached_queue[u]>0 and
        s.cached_quota[u]>=cost and s.cached_battery[u]>=s.c['reserve_j']+cost)
