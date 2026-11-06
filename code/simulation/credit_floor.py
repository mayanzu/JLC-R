"""Enforce the verified floor after finite-precision prefix credit search.

The frozen solver returns a feasible lower approximation. Its floor was
checked by the intensity search, so retaining that floor is also feasible.
Reactive nodes keep their separate nonbinding permission semantics.
"""
import numpy as np

from diagnostic import battery_path


def enforce_credit_floor(controller):
    c = controller.c
    prefix = ~controller.fdc_active
    floor = controller.planned_floor
    correction = np.where(prefix, np.maximum(floor - controller.extra, 0.0), 0.0)
    affected = correction > 0
    if not affected.any():
        return

    costs = controller.base_profile(controller.t).copy()
    credit = controller.extra + correction
    costs[:, :c['period_rounds']] += credit[:, None] / c['period_rounds']
    point, risk, _, _ = controller.bank.entries[controller.t]
    paths = point[None] if controller.prediction_mode == 'P' else risk
    margin, _, _ = battery_path(controller.battery, c['battery_j'], paths,
                               costs, c['reserve_j'])
    if np.any(margin[:, affected] < -1e-10) or np.any(credit[affected] > c['battery_j'] + 1e-10):
        raise AssertionError('Communication floor was not prefix-feasible')

    controller.extra = credit
    controller.issued_credit += float(correction.sum())
    controller.cmax += correction
    controller.credit += correction
    controller.floor_correction_count += int(affected.sum())
    controller.floor_correction_max_j = max(controller.floor_correction_max_j,
                                          float(correction.max()))
    controller.floor_correction_total_j += float(correction.sum())
