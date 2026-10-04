"""
quantum_ops.py - 量子启发算子
  1. sample_from_softmax: 从 softmax 概率分布采样(模拟叠加态坍缩)
  2. tunnel_mutate: 极低概率"量子隧穿"式大跳变,其余高斯小步
  3. crossover: 均匀交叉(父本同位置各 50%)

全局 TUNNEL_COUNTER 用于统计每 500 tick 的隧穿次数。
"""
from __future__ import annotations

import math
import random
from typing import Tuple

# ---------- 全局计数器 ----------
TUNNEL_COUNTER: int = 0
EVOLUTION_TOTAL: int = 0


def reset_stats() -> None:
    global TUNNEL_COUNTER, EVOLUTION_TOTAL
    TUNNEL_COUNTER = 0
    EVOLUTION_TOTAL = 0


def tunnel_stats() -> dict:
    return {
        "tunnel_triggers": TUNNEL_COUNTER,
        "evolution_total": EVOLUTION_TOTAL,
        "tunnel_rate": (TUNNEL_COUNTER / EVOLUTION_TOTAL) if EVOLUTION_TOTAL else 0.0,
    }


# ---------- 1. 叠加坍缩决策 ----------
def sample_from_softmax(probs: list[float]) -> int:
    """按概率分布采样一个索引(模拟波函数坍缩)。
    probs 无需严格归一化,内部自动 sum。
    """
    s = sum(probs)
    if s <= 0 or len(probs) == 0:
        return 0
    r = random.random() * s
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if acc >= r:
            return i
    return len(probs) - 1


def softmax(arr: list[float]) -> list[float]:
    """数值稳定 softmax。"""
    if not arr:
        return []
    m = max(arr)
    es = [math.exp(x - m) for x in arr]
    s = sum(es)
    if s == 0:
        return [1.0 / len(arr)] * len(arr)
    return [e / s for e in es]


# ---------- 2. 隧穿突变 ----------
def tunnel_mutate(value: float, prob: float = 0.001,
                  normal_sigma: float = 0.02) -> Tuple[float, bool]:
    """对单个 [0,1] 值做突变。

    - 以 prob 概率触发"量子隧穿":直接随机重采样 [0,1] 任意值;
    - 否则做高斯 N(0, normal_sigma) 小步扰动,裁剪回 [0,1]。
    返回 (新值, 是否触发了隧穿)。
    """
    global TUNNEL_COUNTER
    if random.random() < prob:
        TUNNEL_COUNTER += 1
        return random.random(), True
    new_v = value + random.gauss(0, normal_sigma)
    if new_v < 0:
        new_v = 0.0
    elif new_v > 1:
        new_v = 1.0
    return new_v, False


def gaussian_mutate(value: float, rate: float = 0.05,
                    sigma: float = 0.08) -> Tuple[float, int]:
    """单基因位标准突变:rate 概率触发高斯步长。返回 (新值, 0/1 是否突变)。"""
    if random.random() < rate:
        v = value + random.gauss(0, sigma)
        if v < 0:
            v = 0.0
        elif v > 1:
            v = 1.0
        return v, 1
    return value, 0


# ---------- 3. 交叉 ----------
def crossover(a: list[float], b: list[float]) -> list[float]:
    """均匀交叉:每个位置 50% 取 a,50% 取 b。"""
    if len(a) != len(b):
        raise ValueError(f"crossover 长度不匹配 {len(a)} vs {len(b)}")
    child = []
    for va, vb in zip(a, b):
        child.append(va if random.random() < 0.5 else vb)
    return child
