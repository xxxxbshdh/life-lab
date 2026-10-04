"""
gene_ops.py - Gene 遗传算子
依赖:core_types.Gene / Phenotype、quantum_ops
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from core_types import Gene, Phenotype
import quantum_ops

# 映射常量
_SPEED_MIN, _SPEED_MAX = 1.0, 4.0
_VISION_MIN, _VISION_MAX = 50.0, 250.0
_AGG_MIN, _AGG_MAX = 0.0, 1.0
_REPRO_MIN, _REPRO_MAX = 40.0, 95.0
_META_MIN, _META_MAX = 0.04, 0.20  # 代谢速率(每 tick 能耗)


def random_gene() -> Gene:
    return Gene(
        speed_trait=random.random(),
        vision_trait=random.random(),
        aggression_trait=random.random(),
        reproduce_thr_trait=random.random(),
        metabolism_trait=random.random(),
        color_r=random.random(),
        color_g=random.random(),
        color_b=random.random(),
    )


def gene_to_phenotype(g: Gene) -> Phenotype:
    """线性映射基因型 → 表型真实参数"""
    speed = _SPEED_MIN + g.speed_trait * (_SPEED_MAX - _SPEED_MIN)
    vision = _VISION_MIN + g.vision_trait * (_VISION_MAX - _VISION_MIN)
    agg = _AGG_MIN + g.aggression_trait * (_AGG_MAX - _AGG_MIN)
    repr_ = _REPRO_MIN + g.reproduce_thr_trait * (_REPRO_MAX - _REPRO_MIN)
    meta = _META_MIN + g.metabolism_trait * (_META_MAX - _META_MIN)
    color = (
        int(max(0, min(255, g.color_r * 255))),
        int(max(0, min(255, g.color_g * 255))),
        int(max(0, min(255, g.color_b * 255))),
    )
    return Phenotype(
        speed=speed, vision_radius=vision, aggression=agg,
        reproduce_threshold=repr_, metabolism=meta, color_rgb=color,
    )


def reproduce(parent_a: Gene, parent_b: Gene,
              mutate_rate: float = 0.05,
              tunnel_rate: float = 0.001,
              ) -> tuple[Gene, dict]:
    """繁殖:均匀交叉 → 每位置高斯突变 → 每位置隧穿概率。
    返回 (子Gene, 统计字典 {mutations, tunnel_hits, crossover_positions})。
    """
    quantum_ops.EVOLUTION_TOTAL += 1

    a_arr = parent_a.as_list()
    b_arr = parent_b.as_list()
    # 交叉
    child_arr = quantum_ops.crossover(a_arr, b_arr)

    mutations = 0
    tunnel_hits = 0
    L = len(child_arr)

    # 整个繁殖事件一次隧穿判定(命中时只挑一个随机位"大跳变")
    if random.random() < tunnel_rate:
        i = random.randrange(L)
        child_arr[i] = random.random()
        quantum_ops.TUNNEL_COUNTER += 1
        tunnel_hits = 1

    # 逐基因位:高斯突变(小步)
    for i in range(L):
        v, m = quantum_ops.gaussian_mutate(child_arr[i], rate=mutate_rate, sigma=0.08)
        mutations += m
        child_arr[i] = v

    child = Gene.from_list(child_arr)
    stats = {
        "mutations": mutations,
        "tunnel_hits": tunnel_hits,
        "child_color": (child.color_r, child.color_g, child.color_b),
    }
    return child, stats


def gene_summary(g: Gene, digits=2) -> str:
    """HUD 用的短摘要。"""
    return (f"速{g.speed_trait:.{digits}f} 视{g.vision_trait:.{digits}f} "
            f"攻{g.aggression_trait:.{digits}f} 繁{g.reproduce_thr_trait:.{digits}f} "
            f"代{g.metabolism_trait:.{digits}f}")
