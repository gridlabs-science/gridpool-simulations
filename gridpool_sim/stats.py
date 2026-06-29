from __future__ import annotations

import math
from statistics import mean, pstdev, stdev


T_CRITICAL_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "n": 0,
            "mean": 0.0,
            "std_sample": 0.0,
            "std_population": 0.0,
            "stderr": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
        }

    n = len(values)
    value_mean = mean(values)
    sample_std = stdev(values) if n > 1 else 0.0
    stderr = sample_std / math.sqrt(n) if n > 1 else 0.0
    margin = t_critical_95(n - 1) * stderr if n > 1 else 0.0
    return {
        "n": n,
        "mean": value_mean,
        "std_sample": sample_std,
        "std_population": pstdev(values) if n > 1 else 0.0,
        "stderr": stderr,
        "ci95_low": value_mean - margin,
        "ci95_high": value_mean + margin,
    }


def t_critical_95(degrees_of_freedom: int) -> float:
    if degrees_of_freedom <= 0:
        return 0.0
    if degrees_of_freedom in T_CRITICAL_95:
        return T_CRITICAL_95[degrees_of_freedom]
    return 1.96
