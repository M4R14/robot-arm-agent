from typing import List


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def distance(a: List[float], b: List[float]) -> float:
    return sum((ai - bi) ** 2 for ai, bi in zip(a, b)) ** 0.5
