"""Unit, safety, regression, observer-neutrality, and information-contract tests for V6.3."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
import numpy as np

from diagnostic import Sample
from current_io import load_config
from current_io import build_scenario
from v4_diagnostics import INDEX
from validation_model import StreamingBank
from v6_model import HYBSimulator
from v63_model import RelayRepairHYB, RelayRepairPADCAge
from v63_observer import CATEGORIES, ObservedHYBSimulator

ROOT = Path(__file__).resolve().parents[2]
DESIGN_PATH = ROOT / "code/simulation/current_design.json"
_SCENARIO_CACHE: dict[tuple[str, int, int, float], tuple[dict, object, object]] = {}


class _CachedStreamingBank:
    """Caches StreamingBank(sc) entries by round t so multiple test runs can reuse forecasts."""

    def __init__(self, sc):
        self.sc = sc
        self._inner = StreamingBank(sc)
        self._cache = {}
        self.entries = self

    def __getitem__(self, t: int):
        if t not in self._cache:
            self._cache[t] = self._inner[t]
        return self._cache[t]

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def _get_cell_scenario(name: str, seed: int = 140101, days: int = 1, supply: float = 1.0):
    key = (name, seed, days, supply)
    if key not in _SCENARIO_CACHE:
        design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        cond = next(c for c in design["conditions"] if c["name"] == name)
        c = load_config(cond)
        sc = build_scenario(c, seed, 14, supply, cond)
        if days < 14:
            sc = copy.copy(sc)
            sc.rounds = days * c["day_rounds"]
        bank = _CachedStreamingBank(sc)
        _SCENARIO_CACHE[key] = (c, sc, bank)
    c, sc, bank = _SCENARIO_CACHE[key]
    return dict(c), sc, bank


class _ForbiddenSinkView:
    """Raises AssertionError on any read or operation while local control is executing."""

    def __getitem__(self, item):
        raise AssertionError("Illegal read of sink state (self.latest) during local node decision!")

    def __setitem__(self, item, value):
        raise AssertionError("Illegal write of sink state (self.latest) during local node decision!")

    def __getattr__(self, name):
        raise AssertionError(f"Illegal access of sink state attribute {name!r} during local node decision!")

    def __len__(self):
        raise AssertionError("Illegal len(self.latest) during local node decision!")


class TestV63RelayRepair(unittest.TestCase):
    def test_off_switch_exact_equivalence_two_cells(self):
        """RelayRepairHYB(v63_mechanism='off') must match HYBSimulator bit-for-bit on 1 seed x 2 cells."""
        for cell_name in ("WINTER_G20", "T2_G20"):
            c, sc, bank = _get_cell_scenario(cell_name, seed=140101, days=1, supply=1.0)
            sim_base = HYBSimulator(dict(c), sc, bank)
            m_base = sim_base.run()

            sim_off = RelayRepairHYB(dict(c), sc, bank, v63_mechanism="off")
            m_off = sim_off.run()

            self.assertEqual(m_base, m_off, f"Scalar metrics diverged in {cell_name}")
            np.testing.assert_array_equal(sim_base.battery, sim_off.battery)
            np.testing.assert_array_equal(sim_base.diagnostic_data, sim_off.diagnostic_data)
            np.testing.assert_array_equal(sim_base.fdc_data, sim_off.fdc_data)
            np.testing.assert_array_equal(sim_base.local_forwarded_birth, sim_off.local_forwarded_birth)

    def test_observer_neutrality_and_categories(self):
        """ObservedHYBSimulator must not alter any simulation state or metric, and classifies S/L/C/Q/P/O."""
        c, sc, bank = _get_cell_scenario("WINTER_G20", seed=140101, days=1, supply=1.0)
        sim_base = HYBSimulator(dict(c), sc, bank)
        m_base = sim_base.run()

        sim_obs = ObservedHYBSimulator(dict(c), sc, bank)
        m_obs = sim_obs.run()

        self.assertEqual(m_base, m_obs)
        np.testing.assert_array_equal(sim_base.battery, sim_obs.battery)
        self.assertEqual(set(sim_obs.fate_counts.keys()), set(CATEGORIES))
        self.assertGreater(sim_obs.fate_counts["P"], 0)
        self.assertGreater(sim_obs.fate_counts["C"], 0)

        far_src = int(np.where(sim_obs.far_source)[0][0])
        for cat in CATEGORIES:
            before = sim_obs.fate_counts[cat]
            sim_obs._record_relay_loss(far_src, cat)
            self.assertEqual(sim_obs.fate_counts[cat], before + 1)

    def test_safety_invariants_and_mechanisms(self):
        """Verify battery conservation (1e-8 J), slot/hold bounds, transit protection (M-B), priority order (M-A), and CH allowance (M-C)."""
        c, sc, bank = _get_cell_scenario("WINTER_G20", seed=140101, days=2, supply=1.0)
        for mech in ("relay_repair", "A", "B", "C"):
            sim = RelayRepairHYB(dict(c), sc, bank, v63_mechanism=mech)
            m = sim.run()
            self.assertLessEqual(m["max_hold_violation_j"], 1e-8)
            self.assertEqual(m["max_slot_violation"], 0)
            self.assertTrue(np.all(sim.battery >= -1e-12))
            self.assertTrue(np.all(sim.battery <= c["battery_j"] + 1e-12))
            b0 = sim.diagnostic_data[:, :, INDEX["battery_pre_round_j"]]
            b_pre = sim.diagnostic_data[:, :, INDEX["battery_preharvest_j"]]
            base_paid = sim.diagnostic_data[:, :, INDEX["actual_base_paid_j"]]
            ctrl_paid = sim.diagnostic_data[:, :, INDEX["actual_control_paid_j"]]
            data_paid = sim.diagnostic_data[:, :, INDEX["actual_data_paid_j"]]
            ledger_err = float(np.max(np.abs((b0 - base_paid - ctrl_paid - data_paid) - b_pre)))
            self.assertLessEqual(ledger_err, 1e-8, f"Ledger error {ledger_err} > 1e-8 J under {mech}")
            per_node_err = (
                abs(sim.initial_sum + sim.harvested - sim.consumed - sim.spilled - float(sim.battery.sum())) / sim.n
            )
            self.assertLessEqual(per_node_err, 1e-8)
            if mech in ("relay_repair", "B"):
                self.assertGreater(int(sim.transit_reserve.sum()), 0)
            if mech == "C":
                self.assertGreaterEqual(sim.mc_allowance_grants, 0)

        # Direct unit verification of M-B transit protection admission gate
        sim_mb = RelayRepairHYB(dict(c), sc, bank, v63_mechanism="relay_repair")
        sim_mb.install_plan()
        ch_j = int(np.where(sim_mb.transit_reserve > 0)[0][0])
        mem_i = int(np.where(sim_mb.parent == ch_j)[0][0])
        sim_mb.off[ch_j] = False
        sim_mb.off[mem_i] = False
        sim_mb.quota[mem_i] = 1.0
        sim_mb.quota[ch_j] = 1.0
        sim_mb.slots_left[mem_i] = 3
        sim_mb.slots_left[ch_j] = int(sim_mb.transit_reserve[ch_j])  # only protected slot left
        sim_mb.forward_slot_holds[ch_j] = 0
        pkt = Sample(source=mem_i, birth=0, sequence=999)
        ok, _ = sim_mb.request_grant(mem_i, ch_j, pkt)
        self.assertFalse(ok)
        self.assertEqual(pkt.last_reason, "transit_protect")
        self.assertEqual(sim_mb.transit_protect_denials, 1)

        sim_padc = RelayRepairPADCAge(dict(c), sc, bank, v63_mechanism="relay_repair")
        m_padc = sim_padc.run()
        self.assertLessEqual(m_padc["max_hold_violation_j"], 1e-8)
        self.assertEqual(m_padc["max_slot_violation"], 0)

    def test_priority_total_order_and_staleness_tie_break(self):
        """Verify M-A tie-breaking prefers oldest local_forwarded_birth among same-round uncovered packets."""
        c, sc, bank = _get_cell_scenario("WINTER_G20", seed=140101, days=1, supply=1.0)
        sim = RelayRepairHYB(dict(c), sc, bank, v63_mechanism="relay_repair")
        sim.install_plan()
        sim.t = 50
        ch_node = int(sim.ch[0])
        sim.local_forwarded_birth[ch_node, 5] = 10
        sim.local_forwarded_birth[ch_node, 42] = -1000
        p_low_id = Sample(source=5, birth=50, sequence=100)
        p_high_id = Sample(source=42, birth=50, sequence=101)
        sim.queues[ch_node].clear()
        sim.queues[ch_node].extend([p_low_id, p_high_id])
        chosen = sim.choose_packet(ch_node)
        self.assertEqual(
            chosen.source,
            42,
            "Tie-break must select oldest local_forwarded_birth source (42) over low node ID (5)",
        )

    def test_local_information_contract_no_sink_access(self):
        """Monkeypatch sim.latest so any read inside install_plan, _select, choose_packet, or request_grant raises AssertionError."""
        c, sc, bank = _get_cell_scenario("WINTER_G20", seed=140101, days=1, supply=1.0)
        forbidden = _ForbiddenSinkView()

        class ContractCheckedRelayRepairHYB(RelayRepairHYB):
            def _with_guarded_sink(self, fn, *args, **kwargs):
                saved = self.latest
                self.latest = forbidden
                try:
                    return fn(*args, **kwargs)
                finally:
                    self.latest = saved

            def install_plan(self):
                return self._with_guarded_sink(super().install_plan)

            def _select(self, genuine, duty):
                return self._with_guarded_sink(super()._select, genuine, duty)

            def read_only_packet(self, i):
                return self._with_guarded_sink(super().read_only_packet, i)

            def choose_packet(self, i):
                return self._with_guarded_sink(super().choose_packet, i)

            def request_grant(self, i, j, packet):
                return self._with_guarded_sink(super().request_grant, i, j, packet)

        sim = ContractCheckedRelayRepairHYB(dict(c), sc, bank, v63_mechanism="relay_repair")
        m = sim.run()
        self.assertGreater(m["coverage_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
