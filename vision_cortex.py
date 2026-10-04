"""
vision_cortex.py - 爱马仕视觉皮层(高品质结构化世界感知)
输入:WorldEntity 列表 + 网格尺寸 N
输出:3 通道"视觉图" + 中文摘要

不依赖 numpy,纯 Python 矩阵实现。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from core_types import WorldEntity, EntityKind

WIDTH, HEIGHT = 800, 600  # 世界尺寸,用于网格归一化


@dataclass
class VisionFrame:
    density: dict[str, list[list[int]]]
    energy_heat: list[list[float]]
    attention: list[list[float]]
    grid_size: int
    entity_count: dict[str, int] = field(default_factory=dict)


class VisionCortex:
    def __init__(self, grid_size: int = 16):
        self.grid_size = grid_size

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        gx = min(self.grid_size - 1,
                 max(0, int(x / WIDTH * self.grid_size)))
        gy = min(self.grid_size - 1,
                 max(0, int(y / HEIGHT * self.grid_size)))
        return gx, gy

    def render(self, entities: list[WorldEntity],
               manager_pos: tuple[float, float] = (WIDTH / 2, HEIGHT / 2)) -> VisionFrame:
        N = self.grid_size
        kinds: dict[str, list[list[int]]] = {
            k.value: [[0] * N for _ in range(N)] for k in EntityKind
        }
        energy = [[0.0] * N for _ in range(N)]
        counts: dict[str, int] = {k.value: 0 for k in EntityKind}

        for e in entities:
            gx, gy = self._cell(e.x, e.y)
            if e.kind.value in kinds:
                kinds[e.kind.value][gy][gx] += 1
                counts[e.kind.value] += 1
            energy[gy][gx] += e.energy

        # attention: 距离 manager_pos 越近越显著
        attention = [[0.0] * N for _ in range(N)]
        maxd = math.hypot(WIDTH, HEIGHT)
        for y in range(N):
            for x in range(N):
                cx = (x + 0.5) * WIDTH / N
                cy = (y + 0.5) * HEIGHT / N
                d = math.hypot(cx - manager_pos[0], cy - manager_pos[1])
                attention[y][x] = 1.0 - (d / maxd)
        return VisionFrame(density=kinds, energy_heat=energy,
                           attention=attention, grid_size=N,
                           entity_count=counts)

    def summarize(self, frame: VisionFrame, topk: int = 5) -> str:
        N = frame.grid_size
        # 每种物种找 topk 个最密集网格
        parts = []
        for kind, mat in frame.density.items():
            hot: list[tuple[int, int, int]] = []
            for y in range(N):
                for x in range(N):
                    if mat[y][x] > 0:
                        hot.append((mat[y][x], x, y))
            hot.sort(reverse=True)
            if hot:
                c = frame.entity_count.get(kind, 0)
                if c == 0:
                    continue
                v, x, y = hot[0]
                zh = _zh_kind(kind)
                region = _region_name(x, y, N)
                density_desc = "密集" if v >= 3 else "出现"
                parts.append(f"{zh}(共{c}只)在{region}最{density_desc}({v}只/格)")
        if not parts:
            return "世界空无一物,一片宁静。"
        # 汇总能量热点
        eh = frame.energy_heat
        peak = (0.0, 0, 0)
        for y in range(N):
            for x in range(N):
                if eh[y][x] > peak[0]:
                    peak = (eh[y][x], x, y)
        if peak[0] > 1.0:
            parts.append(f"能量热点在{_region_name(peak[1], peak[2], N)},"
                         f"总能量≈{int(peak[0])}")
        return "; ".join(parts[:topk]) + "。"


def _zh_kind(k: str) -> str:
    return {
        "agent": "自主Agent",
        "boid": "Boids鸟",
        "herb": "食草动物",
        "pred": "捕食者",
        "crayfish": "小龙虾",
        "plant": "植物",
    }.get(k, k)


def _region_name(gx: int, gy: int, N: int) -> str:
    # 用文字方位描述,便于 LLM 理解
    if N <= 1:
        return "中心"
    if gy < N // 3:
        v = "北"
    elif gy > 2 * N // 3:
        v = "南"
    else:
        v = "中"
    if gx < N // 3:
        h = "西"
    elif gx > 2 * N // 3:
        h = "东"
    else:
        h = "中"
    base = {"北北": "北", "南南": "南", "西西": "西", "东东": "东",
            "中中": "中央"}.get(v + h, v + h)
    return f"{base}(区域{gx}:{gy})"
