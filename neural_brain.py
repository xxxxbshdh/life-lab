"""
neural_brain.py - 纯 Python 实现紧凑 MLP 神经网络(不依赖 torch)
结构:8 输入 → 16 隐藏(tanh) → 4 输出(softmax)
权重列表 flat 后即可作为可遗传基因型(mutate / crossover 直接作用于其数组)。
决策由外部 quantum_ops.sample_from_softmax 采样实现量子启发。
"""
from __future__ import annotations

import math
import random
from typing import Any


def _tanh(x: float) -> float:
    if x > 20:
        return 1.0
    if x < -20:
        return -1.0
    e2 = math.exp(2 * x)
    return (e2 - 1) / (e2 + 1)


def _softmax(arr: list[float]) -> list[float]:
    if not arr:
        return []
    m = max(arr)
    es = [math.exp(x - m) for x in arr]
    s = sum(es)
    if s == 0:
        return [1.0 / len(arr)] * len(arr)
    return [e / s for e in es]


# NN 形状(固定,便于估算 genome_size)
INP_DIM = 8
HID_DIM = 16
OUT_DIM = 4
# W1: INP_DIM × HID_DIM;  b1: HID_DIM
# W2: HID_DIM × OUT_DIM;  b2: OUT_DIM
_W1_LEN = INP_DIM * HID_DIM  # 128
_B1_LEN = HID_DIM            # 16
_W2_LEN = HID_DIM * OUT_DIM  # 64
_B2_LEN = OUT_DIM            # 4
GENOME_SIZE = _W1_LEN + _B1_LEN + _W2_LEN + _B2_LEN  # 212


class NeuralBrain:
    def __init__(self, flat: list[float] | None = None):
        if flat is None:
            flat = self._random_init()
        self.flat = list(flat)
        if len(self.flat) != GENOME_SIZE:
            raise ValueError(f"NeuralBrain 权重长度应为 {GENOME_SIZE},得 {len(self.flat)}")
        # 预切片便于计算
        self.W1, self.b1, self.W2, self.b2 = self._split(self.flat)

    @staticmethod
    def genome_size() -> int:
        return GENOME_SIZE

    # ---------- 初始化 ----------
    @staticmethod
    def _random_init() -> list[float]:
        # Xavier-ish: W1/std=√(2/(INP+HID)); W2/std=√(2/(HID+OUT))
        std1 = math.sqrt(2.0 / (INP_DIM + HID_DIM))
        std2 = math.sqrt(2.0 / (HID_DIM + OUT_DIM))
        arr: list[float] = []
        for _ in range(_W1_LEN):
            arr.append(random.gauss(0, std1))
        for _ in range(_B1_LEN):
            arr.append(0.0)
        for _ in range(_W2_LEN):
            arr.append(random.gauss(0, std2))
        for _ in range(_B2_LEN):
            arr.append(0.0)
        return arr

    @staticmethod
    def _split(flat: list[float]):
        i = 0
        W1 = [flat[i + k * INP_DIM: i + (k + 1) * INP_DIM]
              for k in range(HID_DIM)]
        i += _W1_LEN
        b1 = flat[i: i + _B1_LEN]
        i += _B1_LEN
        W2 = [flat[i + k * HID_DIM: i + (k + 1) * HID_DIM]
              for k in range(OUT_DIM)]
        i += _W2_LEN
        b2 = flat[i: i + _B2_LEN]
        return W1, b1, W2, b2

    # ---------- 推理 ----------
    def forward(self, obs: list[float]) -> list[float]:
        if len(obs) != INP_DIM:
            obs = list(obs) + [0.0] * (INP_DIM - len(obs))
            obs = obs[:INP_DIM]
        # hidden = tanh(W1 · x + b1)
        h = []
        for k in range(HID_DIM):
            s = self.b1[k]
            row = self.W1[k]
            for j in range(INP_DIM):
                s += row[j] * obs[j]
            h.append(_tanh(s))
        # out = W2 · h + b2, 再 softmax
        o = []
        for k in range(OUT_DIM):
            s = self.b2[k]
            row = self.W2[k]
            for j in range(HID_DIM):
                s += row[j] * h[j]
            o.append(s)
        return _softmax(o)

    # ---------- 序列化 ----------
    def to_flat(self) -> list[float]:
        return list(self.flat)

    @classmethod
    def from_flat(cls, arr: list[float]) -> "NeuralBrain":
        return cls(flat=list(arr))

    # ---------- 遗传算子(调用 quantum_ops 保持口径一致) ----------
    def mutate(self, rate: float = 0.03, tunnel_rate: float = 0.001) -> dict:
        """原位突变,返回统计。"""
        import quantum_ops
        quantum_ops.EVOLUTION_TOTAL += 1
        mutations = 0
        tunnel_hits = 0
        # 繁殖层级:整个事件一次隧穿(取一位用 random 重采样 N(0,1))
        if random.random() < tunnel_rate:
            idx = random.randrange(GENOME_SIZE)
            self.flat[idx] = random.gauss(0, 0.5)
            quantum_ops.TUNNEL_COUNTER += 1
            tunnel_hits = 1
        for i in range(GENOME_SIZE):
            v, m = quantum_ops.gaussian_mutate(self.flat[i], rate=rate,
                                                sigma=0.1)
            mutations += m
            self.flat[i] = v
        self.W1, self.b1, self.W2, self.b2 = self._split(self.flat)
        return {"mutations": mutations, "tunnel_hits": tunnel_hits}

    def crossover(self, other: "NeuralBrain") -> "NeuralBrain":
        """均匀交叉产生新大脑。"""
        import quantum_ops
        child_flat = quantum_ops.crossover(self.flat, other.flat)
        return NeuralBrain(flat=child_flat)
