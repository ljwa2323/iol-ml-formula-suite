# -*- coding: utf-8 -*-
"""
IOL power formulas: SRK/T, Holladay 1, Haigis.
Thin-lens (vergence) framework. All lengths in mm except where noted.
K in D; P, SE in D. V = 12 mm (vertex distance).

Main usage (target refraction -> IOL power P):
  from iol_formulas import haigis_iol_power, holladay1_iol_power, srkt_iol_power
  P = srkt_iol_power(AL=24, K=44, target_SE=0, A_constant=118.9)
  P = holladay1_iol_power(AL=24, K=44, target_SE=0, SF=1.5)
  P = haigis_iol_power(AL=24, ACD=3, K=44, target_SE=0, a0=1.1, a1=0.4, a2=0.1)

Predicted SE from given P: haigis_se_pred, holladay1_se_pred, srkt_se_pred.
K from K1,K2: average_K(K1, K2). Haigis (a0,a1,a2): data/haigis_constants.json.
"""

import math
from typing import Optional, Tuple

# --- Constants (mm, D, m as noted) ---
V = 12.0                    # vertex distance, mm
NA = 1.336                  # aqueous/vitreous index
KERATOMETRIC = 337.5        # r = KERATOMETRIC / K when K in D, r in mm


def _k_to_r_mm(K: float) -> float:
    """Convert K (D) to corneal radius r (mm). r = 337.5 / K."""
    if K <= 0:
        raise ValueError("K must be positive")
    return KERATOMETRIC / K


# =============================================================================
# 1) Haigis
# ELP: d = a0 + a1*ACD + a2*AL. Optical: n=1.336, n_c=1.3315, dx=0.012 m.
# R in m for D_c. In q, (AL-d) and d in m.
# =============================================================================

def haigis_se_pred(
    AL: float,
    ACD: float,
    K: float,
    P: float,
    a0: float,
    a1: float,
    a2: float,
) -> float:
    """
    Haigis: predicted SE at spectacle plane given IOL power P.

    Args:
        AL: axial length, mm
        ACD: anterior chamber depth, mm
        K: average corneal power, D (use (K1+K2)/2)
        P: IOL power, D
        a0, a1, a2: Haigis constants (e.g. from haigis_constants.json)

    Returns:
        SE_pred: predicted refraction at spectacle plane, D
    """
    n, nc, dx = 1.336, 1.3315, 0.012  # m
    d = a0 + a1 * ACD + a2 * AL
    R_m = _k_to_r_mm(K) / 1000.0
    Dc = (nc - 1) / R_m
    L_m = (AL - d) / 1000.0
    d_m = d / 1000.0
    den_q = n * L_m + d_m * (n - P * L_m)
    if abs(den_q) < 1e-12:
        return float("nan")
    q = n * (n - P * L_m) / den_q
    den_se = 1 + dx * (q - Dc)
    if abs(den_se) < 1e-12:
        return float("nan")
    return (q - Dc) / den_se


def haigis_iol_power(
    AL: float,
    ACD: float,
    K: float,
    target_SE: float,
    a0: float,
    a1: float,
    a2: float,
    P_min: float = 0.0,
    P_max: float = 40.0,
    tol: float = 1e-4,
    max_iter: int = 80,
) -> Optional[float]:
    """
    Haigis: IOL power P for target refraction (closed-form not available; iterative).

    Args:
        AL, ACD, K, a0, a1, a2: as in haigis_se_pred
        target_SE: target refraction at spectacle plane, D (e.g. 0 for emmetropia)
        P_min, P_max: search bounds for P, D
        tol: stop when |SE_pred - target_SE| < tol
        max_iter: max bisection steps

    Returns:
        P: IOL power in D, or None if not converged
    """
    def f(p):
        return haigis_se_pred(AL, ACD, K, p, a0, a1, a2) - target_SE

    a, b = P_min, P_max
    fa, fb = f(a), f(b)
    if fa * fb > 0:
        return None
    for _ in range(max_iter):
        c = (a + b) / 2
        fc = f(c)
        if abs(fc) < tol:
            return round(c, 2)
        if fa * fc < 0:
            b, fb = c, fc
        else:
            a, fa = c, fc
    return round((a + b) / 2, 2)


# =============================================================================
# 2) Holladay 1
# R_ag = max(R,7), AG = min(12.5*AL/23.45, 13.5), ACD_geo = 0.56 + R_ag - sqrt(R_ag^2 - AG^2/4)
# AL_m = AL + 0.2. n_a=1.336, n_c=4/3, V=12. Closed form: P = (A - SE* C)/(B - SE* D).
# =============================================================================

def _holladay1_intermediates(AL: float, K: float) -> Tuple[float, float, float, float]:
    """R in mm. Returns R, R_ag, ACD_geo, AL_m."""
    R = _k_to_r_mm(K)
    R_ag = max(R, 7.0)
    AG = min(12.5 * AL / 23.45, 13.5)
    disc = R_ag * R_ag - (AG * AG) / 4
    if disc < 0:
        disc = 0
    ACD_geo = 0.56 + R_ag - math.sqrt(disc)
    AL_m = AL + 0.2
    return R, R_ag, ACD_geo, AL_m


def holladay1_se_pred(AL: float, K: float, P: float, SF: float = 1.5) -> float:
    """
    Holladay 1: predicted SE at spectacle plane given IOL power P.

    Args:
        AL: axial length, mm
        K: average corneal power, D
        P: IOL power, D
        SF: Surgeon Factor, mm (default 1.5)

    Returns:
        SE_pred: D
    """
    R, _Rag, ACD_geo, AL_m = _holladay1_intermediates(AL, K)
    nc = 4.0 / 3.0
    ELP = ACD_geo + SF
    u = NA * R - (nc - 1) * AL_m
    w = NA * R - (nc - 1) * ELP
    num = 1000 * NA * u - P * (AL_m - ELP) * w
    den = NA * (V * u + AL_m * R) - 0.001 * P * (AL_m - ELP) * (V * w + ELP * R)
    if abs(den) < 1e-12:
        return float("nan")
    return num / den


def holladay1_iol_power(AL: float, K: float, target_SE: float, SF: float = 1.5) -> Optional[float]:
    """
    Holladay 1: IOL power P for target refraction (closed form).

    Args:
        AL, K, SF (default 1.5): as in holladay1_se_pred
        target_SE: target SE at spectacle plane, D

    Returns:
        P: D, or None if B - target_SE*D ~ 0
    """
    R, _Rag, ACD_geo, AL_m = _holladay1_intermediates(AL, K)
    nc = 4.0 / 3.0
    ELP = ACD_geo + SF
    u = NA * R - (nc - 1) * AL_m
    w = NA * R - (nc - 1) * ELP
    A = 1000 * NA * u
    B = (AL_m - ELP) * w
    C = NA * (V * u + AL_m * R)
    D = 0.001 * (AL_m - ELP) * (V * w + ELP * R)
    den = B - target_SE * D
    if abs(den) < 1e-9:
        return None
    P = (A - target_SE * C) / den
    return round(P, 2)


# =============================================================================
# 3) SRK/T
# K=337.5/r, LCOR, Cw, H, ACDconst, offset, ACD_est, RETHICK, LOPT.
# n_a=1.336, n_cml=0.333, V=12. r in mm. Closed form: P = (A - SE* C)/(B - SE* D).
# =============================================================================

def _srkt_intermediates(AL: float, K: float, A_constant: float) -> Tuple[float, float, float]:
    """Returns r (mm), ACD_est (mm), LOPT (mm)."""
    r = _k_to_r_mm(K)
    if AL <= 24.2:
        LCOR = AL
    else:
        LCOR = -3.446 + 1.715 * AL - 0.0237 * (AL * AL)
    Cw = -5.40948 + 0.58412 * LCOR + 0.098 * K
    disc = r * r - (Cw * Cw) / 4
    if disc < 0:
        disc = 0
    H = r - math.sqrt(disc)
    ACDconst = 0.62467 * A_constant - 68.747
    offset = ACDconst - 3.336
    ACD_est = H + offset
    RETHICK = 0.65696 - 0.02029 * AL
    LOPT = AL + RETHICK
    return r, ACD_est, LOPT


def srkt_se_pred(AL: float, K: float, P: float, A_constant: float) -> float:
    """
    SRK/T: predicted SE at spectacle plane given IOL power P.

    Args:
        AL: axial length, mm
        K: average corneal power, D
        P: IOL power, D
        A_constant: SRK/T A-constant

    Returns:
        SE_pred: D
    """
    r, ACD_est, LOPT = _srkt_intermediates(AL, K, A_constant)
    nc = 0.333
    u = NA * r - nc * LOPT
    w = NA * r - nc * ACD_est
    num = 1000 * NA * u - P * (LOPT - ACD_est) * w
    den = NA * (V * u + LOPT * r) - 0.001 * P * (LOPT - ACD_est) * (V * w + ACD_est * r)
    if abs(den) < 1e-12:
        return float("nan")
    return num / den


def srkt_iol_power(AL: float, K: float, target_SE: float, A_constant: float) -> Optional[float]:
    """
    SRK/T: IOL power P for target refraction (closed form).

    Args:
        AL, K, A_constant: as in srkt_se_pred
        target_SE: target SE at spectacle plane, D

    Returns:
        P: D, or None if B - target_SE*D ~ 0
    """
    r, ACD_est, LOPT = _srkt_intermediates(AL, K, A_constant)
    nc = 0.333
    u = NA * r - nc * LOPT
    w = NA * r - nc * ACD_est
    A = 1000 * NA * u
    B = (LOPT - ACD_est) * w
    C = NA * (V * u + LOPT * r)
    D = 0.001 * (LOPT - ACD_est) * (V * w + ACD_est * r)
    den = B - target_SE * D
    if abs(den) < 1e-9:
        return None
    P = (A - target_SE * C) / den
    return round(P, 2)


# =============================================================================
# Convenience: K from K1,K2
# =============================================================================

def average_K(K1: float, K2: float) -> float:
    """Average corneal power from K1, K2 (D)."""
    return (K1 + K2) / 2.0


__all__ = [
    "haigis_se_pred", "haigis_iol_power",
    "holladay1_se_pred", "holladay1_iol_power",
    "srkt_se_pred", "srkt_iol_power",
    "average_K",
]
