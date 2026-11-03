"""Observation-only V4.1 Phase 1; no control or physical state is changed."""
from collections import Counter
import numpy as np
from diagnostic import battery_path
from strengthening_model import ExtensionOptimized, ExtensionPADCAge
from service_model import radio_capacity

FIELDS = ['planning_event', 'forecast_base_feasible', 'planning_zero_fallback',
 'battery_pre_round_j', 'battery_pre_sync_j', 'battery_post_sync_j',
 'mandatory_base_energy_j', 'planned_listening_intensity', 'planned_credit_j',
 'released_credit_j', 'free_energy_after_holds_j', 'sync_attempted',
 'sync_completed', 'sync_windows_completed', 'sync_energy_paid_j',
 'sync_incomplete_energy_j', 'peer_cache_valid', 'traffic_eligible',
 'available_guards', 'used_guards', 'credit_denied', 'guard_denied',
 'peer_unavailable', 'admission_denied', 'decoding_failed', 'successful_hops',
 'fresh_deliveries', 'packet_expirations', 'actual_credit_used_j',
 'current_sender_energy_opportunity', 'current_bilateral_energy_opportunity',
 'actual_legal_transaction_opportunity', 'is_ch', 'actual_base_paid_j',
 'actual_control_paid_j', 'actual_data_paid_j', 'harvest_j', 'battery_end_j',
 'held_energy_j', 'held_guards', 'zero_credit', 'sync_full_energy_affordable',
 'current_role_capacity', 'battery_preharvest_j']
INDEX = {name:i for i,name in enumerate(FIELDS)}


class DiagnosticMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.diagnostic_data = np.zeros((self.sc.rounds, self.n, len(FIELDS)))
        self.diagnostic_failures = Counter()
        self.diagnostic_prefix_good = np.ones(self.n, dtype=bool)
        self._diag_ready = -1
        self._diag_active = False

    def install_plan(self):
        # Observe only the exact a=0, x=0 base: no guards or future service load.
        # The extra bank lookup is cached, verified against V3 forecast digests.
        _, risk, _, _ = self.bank.entries[self.t]
        fixed, _, _ = self.coefficients(self.t)
        costs = np.full((self.n, self.c['forecast_rounds']), fixed)
        margin, _, _ = battery_path(self.battery, self.c['battery_j'], risk,
                                    costs, self.c['reserve_j'])
        self.diagnostic_prefix_good = (margin >= -1e-10).all(axis=0)
        super().install_plan()

    def put(self, name, values):
        self.diagnostic_data[self._diag_t, :, INDEX[name]] = values

    def add(self, name, node, value=1):
        if self._diag_active:
            self.diagnostic_data[self._diag_t, node, INDEX[name]] += value

    def round(self):
        self._diag_t = self.t
        self._diag_active = True
        self.put('planning_event', int(self.t % self.c['period_rounds'] == 0))
        self.put('battery_pre_round_j', self.battery)
        self._diag_b0 = self.battery.copy()
        self._diag_off0 = self.off.copy()
        super().round()
        self.put('forecast_base_feasible', self.diagnostic_prefix_good)
        self.put('planning_zero_fallback', (~self.diagnostic_prefix_good) &
                 (self.listen_scale <= 1e-12) & (self.extra <= 1e-12))
        self.put('planned_listening_intensity', self.listen_scale)
        self.put('planned_credit_j', self.extra)
        self.put('released_credit_j', self.extra / self.c['period_rounds'])
        self.put('used_guards', self.slots_used)
        self.put('actual_credit_used_j', np.maximum(0, self._diag_q0-self.quota))
        self.put('actual_base_paid_j', self.round_base)
        self.put('actual_control_paid_j', self.round_control)
        self.put('actual_data_paid_j', self.round_comm)
        self.put('harvest_j', self.sc.harvest[self.sc.warm+self._diag_t])
        self.put('battery_preharvest_j', self._diag_b0-self.round_base-self.round_control-self.round_comm)
        self.put('battery_end_j', self.battery)
        self._diag_active = False

    def prepare_sync_activity(self, i, listen):
        c = self.c
        b0 = float(self.battery[i])
        core = (c['sleep_w']*c['round_seconds'] + c['radio_idle_w']*(listen-c['sync_listen_s'])
                + c['sense_j_per_bit']*c['packet_bits'])
        control = c['control_j_per_node_period']/c['period_rounds']
        window = c['radio_idle_w']*c['sync_listen_s']
        full = core+control+self.sync_window_count*window
        self.add('sync_full_energy_affordable', i,
                 int(b0 >= (max(c['recovery_j'], full) if self.off[i] else full)))
        super().prepare_sync_activity(i, listen)
        windows = int(self.sync_paid[:, i].sum())
        complete = windows == self.sync_window_count
        for name, value in dict(battery_pre_sync_j=b0-core-control if windows else b0,
                battery_post_sync_j=self.battery[i], sync_attempted=int(windows>0),
                sync_completed=int(complete), sync_windows_completed=windows,
                sync_energy_paid_j=windows*window,
                sync_incomplete_energy_j=0. if complete else windows*window,
                peer_cache_valid=int(self.last_message[i]==self.t and not self.cached_off[i]),
                traffic_eligible=int(complete and not self.off[i])).items():
            self.add(name, i, value)

    def read_only_packet(self, i):
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        cutoff = self.t-self.c['deadline_rounds']+1
        def priority(p):
            previous = self.local_forwarded_birth[i, p.source]
            return previous < cutoff and p.birth >= cutoff, p.birth-max(previous, cutoff-1), p.birth, -p.sequence
        return max(committed or queue, key=priority)

    def observe_ready(self):
        c = self.c; ph = self.phase(self.t)
        heads = np.zeros(self.n, bool); heads[self.ch] = True
        cap = radio_capacity(self.listen_profiles[ph], c)
        self._diag_q0 = self.quota.copy()
        base = (c['sleep_w']*c['round_seconds'] + c['sense_j_per_bit']*c['packet_bits']
                + c['control_j_per_node_period']/c['period_rounds']
                + self.sync_window_count*c['radio_idle_w']*c['sync_listen_s'])
        for name, values in dict(is_ch=heads, mandatory_base_energy_j=base,
                available_guards=np.where(self.off,0,cap), current_role_capacity=cap,
                free_energy_after_holds_j=np.maximum(0,self.battery-c['reserve_j']-self.forward_holds),
                held_energy_j=self.forward_holds, held_guards=self.forward_slot_holds,
                zero_credit=self.quota<=1e-12).items(): self.put(name, values)
        # Current preharvest endpoint-energy opportunities; never assert success.
        # Additional guards are fully charged. Receiver needs RX + forward hold
        # and two guards, sender needs request/data and one guard. Both endpoints
        # must already have completed sync and published current telemetry.
        free = np.maximum(0,self.battery-c['reserve_j']-self.forward_holds)
        eligible = ~self.off & self.sync_paid.all(axis=0) & (self.last_message==self.t)
        w = c['radio_idle_w']*c['guard_listen_s']
        for i in range(self.n):
            if not eligible[i] or not self.queues[i]: continue
            packet = self.read_only_packet(i)
            choices = self.neighbors.get(i, []) if heads[i] else [int(self.parent[i])]
            sender = bilateral = legal = False
            for receiver in choices:
                j = int(receiver)
                needed_i = self.tx_energy(i,j)+(self.control_cost(i,j)[0] if j<self.n else 0.)
                room_i = int(self.slots_left[i]-self.forward_slot_holds[i])
                if free[i]+1e-14 < needed_i+max(0,1-room_i)*w: continue
                sender = True
                if j < self.n and not eligible[j]: continue
                receiver_ok = True; receiver_legal = True
                if j < self.n:
                    nxt = int(self.reference_next[ph][j])
                    forward = self.tx_energy(j,nxt)+(self.control_cost(j,nxt)[0] if nxt<self.n else 0.)
                    needed_j = (self.control_cost(i,j)[1] + forward +
                                c['packet_bits']*(c['elec_j_per_bit']+c['aggregate_j_per_bit']))
                    room_j = int(self.slots_left[j]-self.forward_slot_holds[j])
                    receiver_ok = free[j]+1e-14 >= needed_j+max(0,2-room_j)*w
                    receiver_legal = (room_j>=2 and self.available(j)>=needed_j and
                                      len(self.queues[j])<c['max_queue'])
                bilateral |= receiver_ok
                legal |= (receiver_ok and receiver_legal and room_i>=1 and self.available(i,packet)>=needed_i)
            self.add('current_sender_energy_opportunity', i, int(sender))
            self.add('current_bilateral_energy_opportunity', i, int(bilateral))
            self.add('actual_legal_transaction_opportunity', i, int(legal))

    def route(self, i, chset):
        if self._diag_ready != self.t:
            self._diag_ready = self.t
            self.observe_ready()
        return super().route(i, chset)

    def block(self, packet, i, j, reason):
        if self._diag_active:
            role = 'CH' if i in self.ch else 'member'
            self.diagnostic_failures[role, reason] += 1
            field = ({'sender_credit':'credit_denied','receiver_credit':'credit_denied',
                'cached_receiver_credit':'credit_denied','listen_capacity':'guard_denied',
                'receiver_off':'peer_unavailable','known_receiver_unavailable':'peer_unavailable',
                'grant_denied':'admission_denied','forward_reserve':'admission_denied',
                'link_loss':'decoding_failed'}).get(reason)
            if field: self.add(field, i)
        return super().block(packet, i, j, reason)

    def attempt(self, i, j, packet):
        before = self.latest[packet.source]
        result = super().attempt(i, j, packet)
        if result[0]:
            self.add('successful_hops', i)
            if j==self.n and self.latest[packet.source]>before:
                self.add('fresh_deliveries', i)
        return result

    def finalize(self, packet, status):
        if status=='expired': self.add('packet_expirations', packet.source)
        return super().finalize(packet, status)

    def diagnostic_rows(self):
        a = self.diagnostic_data
        v = lambda name: a[:,:,INDEX[name]]
        rows=[]
        for role,is_ch in [('member',0),('CH',1),('all',None)]:
            mask = np.ones(a.shape[:2],bool) if is_ch is None else v('is_ch')==is_ch
            event = mask & (v('planning_event')>0)
            bad = mask & (v('forecast_base_feasible')==0)
            zero = bad & (v('zero_credit')>0)
            complete = mask & (v('sync_completed')>0)
            row=dict(kind='diagnostic',role=role,node_rounds=int(mask.sum()),
                plan_node_periods=int(event.sum()),base_infeasible_plan_node_periods=int((event&bad).sum()),
                prefix_infeasible_node_rounds=int(bad.sum()),prefix_bad_zero_credit_node_rounds=int(zero.sum()),
                M2_sender_energy_opportunities=int((zero&(v('current_sender_energy_opportunity')>0)).sum()),
                M2_bilateral_energy_opportunities=int((zero&(v('current_bilateral_energy_opportunity')>0)).sum()),
                M2_actual_legal_transactions=int((zero&(v('actual_legal_transaction_opportunity')>0)).sum()))
            for name in FIELDS:
                if name not in {'planning_event','forecast_base_feasible','is_ch'}:
                    row[name+'_sum']=float(v(name)[mask].sum())
            row['completed_available_guards']=float(v('available_guards')[complete].sum())
            row['completed_used_guards']=float(v('used_guards')[complete].sum())
            row['completed_released_credit_j']=float(v('released_credit_j')[complete].sum())
            row['completed_used_credit_j']=float(v('actual_credit_used_j')[complete].sum())
            rows.append(row)
        rows.extend(dict(kind='failure_reason',role=role,reason=reason,event_count=count)
                    for (role,reason),count in sorted(self.diagnostic_failures.items()))
        return rows


class DiagnosticOptimized(DiagnosticMixin, ExtensionOptimized):
    pass


class DiagnosticPADCAge(DiagnosticMixin, ExtensionPADCAge):
    pass
