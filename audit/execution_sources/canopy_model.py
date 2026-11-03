"""Exploratory crop-canopy coupling for the agricultural extension experiments.

This module is *not* part of the frozen JLC-R confirmation path. It is imported
by ``simulator.py`` only when a configuration explicitly sets
``canopy_channel_lambda``. The frozen geometric link model is retained byte for
byte when that key is absent.

Model (exploratory stress test, not a calibrated crop-physiology model):

* A smooth, spatially correlated canopy intensity field ``c_i`` in [0, 1] is
  generated from node positions with a seeded plane-wave superposition. The
  same field is shared by every controller in a seed-matched comparison.
* Energy transmittance at stage ``k`` is
  ``T_i = T_max - (T_max - T_min) c_i``, multiplying the node solar scale.
* Link decoding probability is
  ``p_ij = p_ij^0 [1 - lambda_k (c_i + c_j) / 2]``, clipped to a legal range.
"""
from __future__ import annotations

import numpy as np

STAGE_RANGES = {"I": (0.85, 1.00), "II": (0.70, 0.90), "III": (0.50, 0.80)}
STAGE_LAMBDA = {"I": 0.0, "II": 0.10, "III": 0.20}
PROB_FLOOR = 0.35


def spatial_canopy(pos, seed, wavelength_m=110.0, n_waves=6):
    """Smooth canopy intensity in [0, 1] from a seeded plane-wave field."""
    pos = np.asarray(pos, dtype=float)
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 55]))
    direction = rng.uniform(0.0, 2.0 * np.pi, n_waves)
    amplitude = rng.uniform(0.4, 1.0, n_waves)
    phase = rng.uniform(0.0, 2.0 * np.pi, n_waves)
    wave = 2.0 * np.pi / float(wavelength_m)
    field = np.zeros(len(pos))
    for k in range(n_waves):
        field += amplitude[k] * np.cos(
            wave * (pos[:, 0] * np.cos(direction[k]) + pos[:, 1] * np.sin(direction[k]))
            + phase[k]
        )
    field = (field - field.min()) / max(field.max() - field.min(), 1e-12)
    return field


def transmittance(canopy, stage):
    """Stage energy transmittance from the shared canopy intensity."""
    high, low = STAGE_RANGES[stage]
    return high - (high - low) * np.asarray(canopy, dtype=float)


def channel_factor(canopy, lam):
    """Symmetric pair attenuation factor for the canopy-linked channel."""
    canopy = np.asarray(canopy, dtype=float)
    return np.clip(1.0 - float(lam) * 0.5 * (canopy[:, None] + canopy[None, :]), 0.0, 1.0)
