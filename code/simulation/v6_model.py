"""V6 candidate: fallback duty-credit (FDC) on genuine JLC-SA fallback only.

One mechanism. When the JLC-SA plan yields zero listening scale and zero
period credit at issuance (the genuine-fallback flag shared with OC-v1),
gated nodes substitute the validated PADC-DC duty rule computed from current
observable state only, with integer slot planning and nonbinding permission.
All physical transaction checks stay unchanged. Off-switch restores JLC-SA.
"""
import numpy as np

from recent_baselines import padc_duty
from strengthening_model import ExtensionJoint, ExtensionPADC
from v4_diagnostics import DiagnosticMixin, DiagnosticOptimized

FDC_FIELDS = ["triggered", "activated", "duty", "selective_gate_pass",
              "uncovered_fresh_packets"]
FDC_INDEX = {k: i for i, k in enumerate(FDC_FIELDS)}


class DiagnosticPADC(DiagnosticMixin, ExtensionPADC):
    """PADC-DC under the common diagnostic harness (no local-age scheduler)."""

    def read_only_packet(self, i):
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        return max(committed or queue, key=lambda p: (p.birth, -p.sequence))


class DiagnosticJoint(DiagnosticMixin, ExtensionJoint):
    """JLC-R / JLC-R-FIXED under the common diagnostic harness (policy arg)."""

    def read_only_packet(self, i):
        queue = self.queues[i]
        committed = [p for p in queue if self.holds.get(p.sequence, (-1, 0))[0] == i]
        return max(committed or queue, key=lambda p: (p.birth, -p.sequence))


class FDCSimulator(DiagnosticOptimized):
    def __init__(self, c, sc, bank):
        super().__init__(c, sc, bank)
        self.fdc_enabled = bool(c.get("fdc_enabled", False))
        self.fdc_selective = bool(c.get("fdc_selective", True))
        self.fdc_genuine = np.zeros(self.n, bool)
        self.fdc_active = np.zeros(self.n, bool)
        self.fdc_duty = np.zeros(self.n)
        self.fdc_triggered_periods = 0
        self.fdc_activated_periods = 0
        self.fdc_data = np.zeros((sc.rounds, self.n, len(FDC_FIELDS)))

    def _uncovered_fresh(self, i, cutoff):
        for p in self.queues[i]:
            if p.birth >= cutoff and self.local_forwarded_birth[i, p.source] < cutoff:
                return True
        return False

    def _duty(self):
        c = self.c
        period = c["period_rounds"]
        ph = self.phase(self.t)
        full_base = (c["sleep_w"] * c["round_seconds"]
                     + c["radio_idle_w"] * (self.reference_listening[ph]
                                            + c.get("sync_extra_listen_s", 0.))
                     + c["sense_j_per_bit"] * c["packet_bits"]
                     + c["control_j_per_node_period"] / period)
        full_demand = self.phase_structures[ph][2] + self.grant_profiles[ph]
        point = self.bank.entries[self.t][0]
        predicted = point[:, :period].sum(axis=1)
        return padc_duty((self.battery + predicted) / c["battery_j"],
                         predicted, period * (full_base + full_demand))

    def _select(self, genuine, duty):
        c = self.c
        cutoff = self.t - c["deadline_rounds"] + 1
        if self.fdc_selective:
            gate = np.array([self._uncovered_fresh(i, cutoff) if genuine[i] else False
                             for i in range(self.n)], dtype=bool)
            return genuine & gate
        return genuine.copy()

    def install_plan(self):
        super().install_plan()
        if not self.fdc_enabled:
            return
        c = self.c
        period = c["period_rounds"]
        genuine = ((~self.diagnostic_prefix_good)
                   & (self.listen_scale <= 1e-12) & (self.extra <= 1e-12))
        self.fdc_genuine = genuine.copy()
        duty = np.asarray(self._duty(), dtype=float)
        use = self._select(genuine, duty)
        self.fdc_active = use.copy()
        self.fdc_duty = np.where(use, duty, 0.)
        self.fdc_triggered_periods += int(genuine.sum())
        self.fdc_activated_periods += int(use.sum())
        if not use.any():
            return
        # Recompute integer slot profiles for the mixed scale vector. The
        # slot planner is deterministic, so untouched nodes are unchanged.
        old_scale = self.listen_scale.copy()
        ratios_old = self.slot_plan(self.t, old_scale)[3]
        new_scale = np.where(use, duty, old_scale)
        _, floor_new, slots_new, ratios_new = self.slot_plan(self.t, new_scale)
        ph = self.phase(self.t)
        self.listen_scale = new_scale
        self.planned_floor = floor_new
        self.plan_profiles = c["sync_listen_s"] + c["guard_listen_s"] * slots_new
        self.listen_profiles = [p.copy() for p in self.plan_profiles]
        self.actual_profiles = [p.copy() for p in self.plan_profiles]
        self.runtime_cap_profiles = [s.copy() for s in slots_new]
        self.scale_sum += float((ratios_new[ph] - ratios_old[ph]).sum())
        self.scale_count += 0  # denominator unchanged; numerator corrected
        # Nonbinding permission for gated nodes only (PADC semantic). The
        # physical kernel (battery/reserve/holds/slots/queues/decoder) binds.
        base_new = self.base_profile(self.t)
        new_extra = self.extra.copy()
        new_extra[use] = period * c["battery_j"]
        self.issued_credit += float((new_extra - self.extra).sum())
        self.extra = new_extra
        self.cmax = base_new[:, :period].sum(axis=1) + self.extra
        self.credit = self.cmax.copy()
        bad = self.extra + c["battery_j"] / 2 ** 15 + 1e-9 < floor_new
        self.joint_floor_failures += int(bad.sum())
        if bad.any():
            raise AssertionError("FDC plan lost its communication floor")

    def round(self):
        self._fdc_t = self.t
        super().round()
        if self.fdc_enabled and self.t < self.sc.rounds:
            self.fdc_data[self.t, :, FDC_INDEX["triggered"]] = self.fdc_genuine.astype(float)
            self.fdc_data[self.t, :, FDC_INDEX["activated"]] = self.fdc_active.astype(float)
            self.fdc_data[self.t, :, FDC_INDEX["duty"]] = self.fdc_duty

    def metrics(self):
        row = super().metrics()
        row.update(method="JLC-R-FDC",                   fdc_enabled=int(self.fdc_enabled),
                   fdc_selective=int(self.fdc_selective),
                   fdc_triggered_node_periods=self.fdc_triggered_periods,
                   fdc_activated_node_periods=self.fdc_activated_periods)
        return row

    def fdc_rows(self):
        rows = []
        for role, mask in [("all", np.ones(self.n, bool)),
                           ("member", np.array([i not in set(self.ch.tolist()) for i in range(self.n)])),
                           ("CH", np.array([i in set(self.ch.tolist()) for i in range(self.n)]))]:
            rows.append(dict(kind="fdc", role=role,
                             triggered=int(self.fdc_data[:, :, FDC_INDEX["triggered"]][:, mask].sum()),
                             activated=int(self.fdc_data[:, :, FDC_INDEX["activated"]][:, mask].sum())))
        return rows


class HYBSimulator(FDCSimulator):
    """Candidate 2: widened state-aware hybrid with latch (period dwell + exit margin).

    Trigger = uncovered-fresh demand AND (genuine fallback OR thin JLC plan OR
    latched-hybrid with JLC scale below the exit margin). Same duty substitution,
    same physical kernel, same off-switch lineage (hyb off -> FDC; fdc off -> JLC-SA).
    """

    def __init__(self, c, sc, bank):
        super().__init__(c, sc, bank)
        self.hyb_enabled = bool(c.get("hyb_enabled", False))
        self.hyb_latched = np.zeros(self.n, bool)
        self.hyb_thin_added_periods = 0

    def _select(self, genuine, duty):
        if not self.hyb_enabled:
            return super()._select(genuine, duty)
        c = self.c
        enter_thr = float(c.get("hyb_thin_scale", 0.98))
        exit_thr = float(c.get("hyb_exit_scale", 0.99))
        cutoff = self.t - c["deadline_rounds"] + 1
        demand = np.array([self._uncovered_fresh(i, cutoff) for i in range(self.n)], dtype=bool)
        thin = self.listen_scale < enter_thr
        stay = self.hyb_latched & (self.listen_scale < exit_thr)
        use = demand & (genuine | thin | stay)
        self.hyb_latched = use.copy()
        self.hyb_thin_added_periods += int((use & ~genuine).sum())
        return use

    def install_plan(self):
        if self.hyb_enabled and not self.fdc_enabled:
            raise ValueError("hyb requires fdc_enabled")
        super().install_plan()

    def metrics(self):
        row = super().metrics()
        row.update(method="JLC-R-HYB",
                   hyb_enabled=int(self.hyb_enabled),
                   hyb_thin_added_node_periods=self.hyb_thin_added_periods)
        return row
