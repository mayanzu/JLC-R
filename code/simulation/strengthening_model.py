"""V3 paired extensions; original controller definitions remain explicit controls."""
from collections import Counter
import hashlib
import numpy as np
from diagnostic import Sample
from joint_model import JointSimulator
from optimized_model import OptimizedSimulator
from matched_age_baseline import MatchedAgeDutySimulator
from recent_baselines import DutyControlSimulator
from service_model import radio_capacity
from simulator import keyed_uniform


def sync_configuration(c):
    """One shared S100/S200 schedule; no controller-specific physical rules."""
    cfg = dict(c)
    interval = int(cfg.get('sync_interval_s', 100))
    if interval not in (100, 200):
        raise ValueError('Only the fixed S100/S200 configurations are supported')
    starts = tuple(range(0, int(cfg['round_seconds']), interval))
    if starts[-1] != 800 or cfg['sync_listen_s'] != .020:
        raise ValueError('Frozen last-window and duration assumptions changed')
    if cfg.get('joint_sync_execution'):
        count = len(starts)
        extra = (count-1)*cfg['sync_listen_s']
        if cfg.get('sync_window_count', count) != count:
            raise ValueError('Window count conflicts with the common schedule')
        if abs(cfg.get('sync_extra_listen_s', extra)-extra) > 1e-12:
            raise ValueError('Planner extra sync cost conflicts with the executor')
        if cfg.get('clock_drift_ppm', 20) != 20 or not cfg.get('sync_required_for_traffic', True):
            raise ValueError('Frozen clock/qualification assumptions changed')
        cfg.update(sync_interval_s=interval, sync_window_count=count,
                   sync_extra_listen_s=extra, clock_drift_ppm=20,
                   sync_required_for_traffic=True)
    return cfg, starts


class ResourceMixin:
    def __init__(self, c, *args, **kwargs):
        c, self.sync_window_starts_s = sync_configuration(c)
        self.sync_window_count = len(self.sync_window_starts_s)
        super().__init__(c, *args, **kwargs)
        self.resources = {role: Counter() for role in ['member', 'CH']}
        self.capacity_hist = Counter()
        rng = np.random.default_rng(np.random.SeedSequence([self.sc.seed, 909]))
        self.clock_bias = rng.uniform(-20e-6, 20e-6, self.n)
        self.sync_paid = np.zeros((self.sync_window_count, self.n), dtype=bool)
        self.sync_initial_j = self.sync_extra_j = 0.
        self.sync_missed_windows = self.timing_misses = 0
        self.successful_hops = np.zeros(self.n, dtype=int)

    def prepare_sync_activity(self, i, listen):
        """Reserve scheduled work, then pay every configured sync window.

        No within-round recharge. Failed nodes publish no new telemetry. The
        original 20 ms is removed from scheduled cost and charged at window 0.
        """
        c = self.c
        core = (c['sleep_w']*c['round_seconds'] + c['radio_idle_w']*(listen-c['sync_listen_s'])
                + c['sense_j_per_bit']*c['packet_bits'])
        control = c['control_j_per_node_period']/c['period_rounds']
        window = c['radio_idle_w']*c['sync_listen_s']
        if self.off[i] and self.battery[i] >= max(c['recovery_j'], core+control+window):
            self.off[i] = False
        if not self.off[i] and self.battery[i] >= core+control+window:
            # This work is reserved before synchronization; it cannot spend
            # energy promised to any of the later windows or borrow harvest.
            self.debit(i, core, 'base')
            self.debit(i, control, 'control')
            for k, window_start_s in enumerate(self.sync_window_starts_s):
                if self.battery[i]+1e-14 < window:
                    break
                self.debit(i, window, 'base')
                self.sync_paid[k, i] = True
                if k == 0:
                    self.sync_initial_j += window
                else:
                    self.sync_extra_j += window
            self.guard_energy += c['radio_idle_w']*(listen-c['sync_listen_s'])
            if self.sync_paid[:, i].all():
                self.generated += 1
                packet = Sample(i, self.t, self.t*self.n+i)
                if len(self.queues[i]) < c['max_queue']:
                    self.queues[i].append(packet)
                else:
                    self.overflow += 1
                    packet.last_reason = 'queue_overflow'
                    self.finalize(packet, 'overflow')
                self.cached_battery[i] = self.battery[i]
                self.cached_quota[i] = self.quota[i]
                self.cached_queue[i] = len(self.queues[i])
                self.cached_off[i] = False
                self.last_message[i] = self.t
                return
        else:
            self.debit(i, min(self.battery[i], c['off_w']*c['round_seconds']), 'base')
        self.off[i] = True
        self.unsensed += 1
        self.outcomes['unsensed'] += 1
        self.sample_status[self.t*self.n+i] = 5
        self.slots_left[i] = 0
        self.cached_off[i] = True

    def attempt(self, i, j, packet):
        c = self.c
        if c.get('joint_sync_execution'):
            # All abstract sequential transactions occupy [800.02,900) s.
            # Conservative age bound is the common system sync interval.
            jitter = (2*keyed_uniform(self.sc.seed, 990, self.t, i, j, packet.sequence)-1)*c['sync_jitter_s']
            other = self.clock_bias[j] if j < self.n else 0.
            offset = abs((self.clock_bias[i]-other)*c.get('sync_interval_s',100)+jitter)+c['sync_turnaround_s']
            if offset > c['guard_listen_s']:
                self.timing_misses += 1
                if j < self.n:
                    saved = self.off[j]
                    self.off[j] = True
                    try:
                        return super().attempt(i, j, packet)
                    finally:
                        self.off[j] = saved
                # Sink timing failure: charged sender guard and request cost.
                if self.available(i, packet) >= self.tx_energy(i, j) and self.slots_left[i]-self.forward_slot_holds[i]+int(packet.sequence in self.hold_slots)>0:
                    self.use_slot(i, packet)
                    self.release_hold(packet)
                    self.debit(i, self.tx_energy(i, j), 'comm')
                self.block(packet, i, j, 'receiver_off')
                return False, 'receiver_off'
        result = super().attempt(i, j, packet)
        if result[0]:
            self.successful_hops[i] += 1
        return result

    def round(self):
        t = self.t
        self.sync_paid[:] = False
        before = self.successful_hops.copy()
        super().round()
        ph = self.phase(t)
        c = self.c
        ref = self.reference_listening[ph]
        actual = self.listen_profiles[ph]
        kr = radio_capacity(ref, c)
        ka = radio_capacity(actual, c)
        fixed = np.full(self.n, c['cm_listen_s'])
        fixed[self.ch] = c['ch_listen_s']
        fraction = np.maximum(0, actual-c['sync_listen_s']-ka*c['guard_listen_s'])*1000
        heads = np.zeros(self.n, dtype=bool)
        heads[self.ch] = True
        for role, mask in [('member', ~heads), ('CH', heads)]:
            r = self.resources[role]
            r['node_rounds'] += int(mask.sum())
            for name, values in dict(tau_ref_ms=ref*1000, tau_fixed_ms=fixed*1000,
                    K_ref=kr, K_actual=ka, listening_intensity=self.listen_scale,
                    tau_actual_ms=actual*1000, reference_cap_hit=(ref>=fixed-1e-12),
                    unused_fractional_listening_ms=fraction, planned_credit_j=self.extra,
                    released_credit_j=self.extra/c['period_rounds'],
                    available_guards=np.where(self.off, 0, ka), used_guard_transactions=self.slots_used,
                    unused_credit_j=np.maximum(0, self.quota), successful_forwarding=self.successful_hops-before).items():
                r[name] += float(np.asarray(values)[mask].sum())
            for value, count in zip(*np.unique(kr[mask], return_counts=True)):
                self.capacity_hist[role, int(value)] += int(count)
        if c.get('joint_sync_execution'):
            self.sync_missed_windows += int((~self.sync_paid).sum())
            # Original time envelope omitted extra sync; enforce the actual
            # late-round service interval, including both endpoint airtimes.
            envelope = float(np.maximum(0, actual[~self.off]-c['sync_listen_s']).sum()
                             +self.slots_used.sum()*c['packet_bits']/c['bitrate_bps'])
            if envelope > 99.98:
                raise AssertionError('Late-round transaction envelope exceeded')

    def metrics(self):
        row = super().metrics()
        row.update(sync_initial_energy_j=self.sync_initial_j, sync_extra_energy_j=self.sync_extra_j,
                   sync_energy_j=self.sync_initial_j+self.sync_extra_j,
                   sync_missed_windows=self.sync_missed_windows, timing_misses=self.timing_misses,
                   clock_sha256=hashlib.sha256(self.clock_bias.tobytes()).hexdigest(),
                   floor_enabled=int(not self.c.get('no_reference_floor', False) and self.joint_listening),
                   guard_ms=self.c['guard_listen_s']*1000,
                   sync_interval_s=self.c.get('sync_interval_s',100) if self.c.get('joint_sync_execution') else 900,
                   sync_window_count=self.sync_window_count,
                   sync_window_duration_s=self.c['sync_listen_s'],
                   sync_energy_per_window_j=self.c['radio_idle_w']*self.c['sync_listen_s'],
                   jitter_semantics='relative_link',
                   jitter_bound_ms=1000*self.c.get('sync_jitter_s', 0), clock_drift_ppm=20,
                   planning_mode='integer' if getattr(self, 'slot_planning', False) else 'continuous',
                   selector_mode='local-age' if getattr(self, 'age_scheduling', False) or getattr(self, 'duty_age', False) else 'newest-first')
        return row

    def resource_rows(self):
        rows = []
        for role, counters in self.resources.items():
            rows.append(dict(kind='role_mean', role=role, **{k:(v/counters['node_rounds'] if k!='node_rounds' else v)
                        for k,v in counters.items()}))
        for (role, slots), count in sorted(self.capacity_hist.items()):
            rows.append(dict(kind='K_ref_distribution', role=role, K_ref=slots, node_rounds=count))
        return rows


class ExtensionJoint(ResourceMixin, JointSimulator):
    pass


class ExtensionOptimized(ResourceMixin, OptimizedSimulator):
    def slot_plan(self, t, scale):
        costs, floor, slots, ratios = super().slot_plan(t, scale)
        if self.c.get('no_reference_floor'):
            floor = np.zeros_like(floor)
        return costs, floor, slots, ratios


class ExtensionPADC(ResourceMixin, DutyControlSimulator):
    pass


class ExtensionPADCAge(ResourceMixin, MatchedAgeDutySimulator):
    duty_age = True
