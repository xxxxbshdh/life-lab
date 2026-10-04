"""
core_types.py - Life Lab v2 跨模块公共类型
所有模块都依赖此文件,不要反向依赖任何模式模块。
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------- 枚举 ----------
class EntityKind(str, Enum):
    AGENT = "agent"
    BOID = "boid"
    HERB = "herb"           # 食草动物
    PRED = "pred"           # 捕食者
    CRAYFISH = "crayfish"   # 小龙虾
    PLANT = "plant"


class InstructionIntent(str, Enum):
    SPAWN_PLANTS = "spawn_plants"
    RESET_AGENT = "reset_agent"
    PET_SEND_MSG = "pet_send_msg"
    ECO_ADJUST = "eco_adjust"
    STUDY_URL = "study_url"
    LEARN_TEXT = "learn_text"
    FREE_TEXT = "free_text"


# ---------- 数据结构 ----------
@dataclass
class Gene:
    """可遗传的基因型:5 个 trait + 3 维颜色码,全部 ∈ [0, 1]"""
    speed_trait: float = 0.5
    vision_trait: float = 0.5
    aggression_trait: float = 0.5
    reproduce_thr_trait: float = 0.5
    metabolism_trait: float = 0.5
    # 外观码(用于渲染颜色,也遗传)
    color_r: float = 0.5
    color_g: float = 0.5
    color_b: float = 0.5

    def as_list(self) -> list[float]:
        return [
            self.speed_trait, self.vision_trait, self.aggression_trait,
            self.reproduce_thr_trait, self.metabolism_trait,
            self.color_r, self.color_g, self.color_b,
        ]

    @classmethod
    def from_list(cls, arr: list[float]) -> "Gene":
        return cls(*arr[:8])


@dataclass
class Phenotype:
    """基因型映射后的真实物理参数"""
    speed: float
    vision_radius: float
    aggression: float
    reproduce_threshold: float
    metabolism: float
    color_rgb: tuple[int, int, int]


@dataclass
class WorldEntity:
    """统一世界实体:供 VisionCortex 等模块读取"""
    entity_id: int
    kind: EntityKind
    x: float
    y: float
    energy: float = 50.0
    gene: Optional[Gene] = None


@dataclass
class ParsedInstruction:
    """Manager 解析用户指令后得到的结构化意图"""
    intent: InstructionIntent
    payload: dict = field(default_factory=dict)

    def get(self, key, default=None):
        return self.payload.get(key, default)


# ---------- 全局 ID 生成 ----------
_ENTITY_ID = 0


def next_entity_id() -> int:
    global _ENTITY_ID
    _ENTITY_ID += 1
    return _ENTITY_ID


def reset_entity_ids() -> None:
    global _ENTITY_ID
    _ENTITY_ID = 0


# ---------- 全局 WorldContext ----------
# 由 life_lab 主程序维护,所有子模式共享
@dataclass
class WorldContext:
    # 子模式引用(可能为 None,未启动则为默认实例)
    agent_obj: object | None = None               # life_agent.Agent
    agent_best_brain_flat: list[float] | None = None
    agent_second_brain_flat: list[float] | None = None
    agent_evolution_count: int = 0

    ecosystem_plants: list | None = None          # list[Plant]
    ecosystem_herbs: list | None = None
    ecosystem_preds: list | None = None
    ecosystem_crayfish: list | None = None

    pet_obj: object | None = None                 # mode_pet.Pet
    pet_log: list[str] | None = None              # 对话日志
    pet_inbox: list[str] | None = None            # Manager→Pet 待展示消息队列(模式5写,模式4读)

    boids_list: list | None = None                # list[mode_boids.Boid]

    manager_memory: list[str] | None = None
    manager_learned_urls: list[str] | None = None

    # 全局节拍计数(主菜单每 tick +1,切模式不清零)
    tick_count: int = 0

    # 为 Manager 面板调度准备的"立即操作队列"(Manager 发指令后,下一次进入该模式时应用)
    pending_spawn_plants: int = 0  # 进入生态后立即新增的植物数
    agent_reset_pending: bool = False  # Manager 说"重置 Agent"后,进入模式1会重建随机个体

    def as_world_entities(self) -> list[WorldEntity]:
        """把当前世界所有实体统一成 WorldEntity 列表,给 VisionCortex / 统计用。"""
        ents: list[WorldEntity] = []
        # Agent
        a = self.agent_obj
        if a is not None:
            try:
                ents.append(WorldEntity(
                    entity_id=next_entity_id(), kind=EntityKind.AGENT,
                    x=float(a.x), y=float(a.y), energy=float(a.energy),
                    gene=None if not getattr(a, 'gene', None) else a.gene,
                ))
            except Exception:
                pass
        # Ecosystem
        def _add_from(ls, kind: EntityKind, energy_default: float):
            if ls is None:
                return
            for obj in ls:
                try:
                    pos = getattr(obj, 'pos', None)
                    if pos is not None:
                        x, y = float(pos.x), float(pos.y)
                    else:
                        x, y = float(getattr(obj, 'x', 0)), float(getattr(obj, 'y', 0))
                    e = float(getattr(obj, 'energy', energy_default))
                    g = getattr(obj, 'gene', None)
                    ents.append(WorldEntity(entity_id=next_entity_id(),
                                            kind=kind, x=x, y=y, energy=e, gene=g))
                except Exception:
                    pass
        _add_from(self.ecosystem_plants, EntityKind.PLANT, 10)
        _add_from(self.ecosystem_herbs, EntityKind.HERB, 50)
        _add_from(self.ecosystem_preds, EntityKind.PRED, 60)
        _add_from(self.ecosystem_crayfish, EntityKind.CRAYFISH, 55)
        # Boids
        if self.boids_list is not None:
            for b in self.boids_list:
                try:
                    pos = getattr(b, 'pos', None)
                    if pos is None:
                        continue
                    ents.append(WorldEntity(entity_id=next_entity_id(),
                                            kind=EntityKind.BOID,
                                            x=float(pos.x), y=float(pos.y),
                                            energy=30))
                except Exception:
                    pass
        return ents


# ---------- 全局 tick 推进 + 500 tick 快照 ----------
# 所有模式(含菜单)主循环内统一调用:
#    printed = advance_tick(ctx, every=500)
# 避免每个模块各自写 tick+=1 与 %500 判断导致不一致。
_LAST_PRINTED_TICK_GLOBAL: dict = {"v": -1}


def _snapshot_world(ctx: "WorldContext") -> dict:
    """收集用于 500 tick 打印的世界快照。"""
    a_age = a_alive = a_energy = None
    if ctx.agent_obj is not None:
        a_age = getattr(ctx.agent_obj, "age", None)
        a_alive = getattr(ctx.agent_obj, "alive", None)
        a_energy = getattr(ctx.agent_obj, "energy", None)
    plants_n = len(ctx.ecosystem_plants) if ctx.ecosystem_plants else 0
    herbs_n = len(ctx.ecosystem_herbs) if ctx.ecosystem_herbs else 0
    preds_n = len(ctx.ecosystem_preds) if ctx.ecosystem_preds else 0
    cray_n = len(ctx.ecosystem_crayfish) if ctx.ecosystem_crayfish else 0
    bo = len(ctx.boids_list) if ctx.boids_list else 0
    p_mood = p_hunger = p_aff = None
    if ctx.pet_obj is not None:
        p_mood = getattr(ctx.pet_obj, "mood", None)
        p_hunger = int(getattr(ctx.pet_obj, "hunger", 0))
        p_aff = int(getattr(ctx.pet_obj, "affection", 0))
    m_aff = m_urls = None
    try:
        sp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "manager_state.json")
        if os.path.exists(sp):
            with open(sp, "r", encoding="utf-8") as f:
                d = json.load(f)
            m_aff = d.get("affection")
            m_urls = len(d.get("learned_urls") or [])
    except Exception:
        pass
    ts: dict = {"tunnel_triggers": 0, "evolution_total": 0, "tunnel_rate": 0.0}
    try:
        import quantum_ops  # 本地 import 避免循环依赖
        ts = quantum_ops.tunnel_stats()
    except Exception:
        pass
    return {
        "tick": ctx.tick_count,
        "ts": ts,
        "agent": (a_age, a_alive, a_energy, ctx.agent_evolution_count),
        "eco": (plants_n, herbs_n, preds_n, cray_n, ctx.pending_spawn_plants),
        "boids": bo,
        "pet": (p_mood, p_hunger, p_aff),
        "manager": (m_aff, m_urls),
    }


def _format_snapshot(s: dict) -> str:
    ts = s["ts"]
    a_age, a_alive, a_energy, a_evol = s["agent"]
    plants_n, herbs_n, preds_n, cray_n, pend = s["eco"]
    bo = s["boids"]
    p_mood, p_hunger, p_aff = s["pet"]
    m_aff, m_urls = s["manager"]
    return (
        f"\n===== [tick {s['tick']}] 隧穿统计 =====\n"
        f"  TUNNEL_COUNTER = {ts['tunnel_triggers']}\n"
        f"  EVOLUTION_TOTAL = {ts['evolution_total']}\n"
        f"  rate = {ts['tunnel_rate']*100:.4f}%\n"
        "---- 世界快照 ----\n"
        f"  Agent: age={a_age} alive={a_alive} energy={a_energy} evol={a_evol}\n"
        f"  生态: 植物{plants_n} 食草{herbs_n} 捕食{preds_n} 小龙虾{cray_n} 挂起投放:{pend}\n"
        f"  Boids: {bo}\n"
        f"  宠物: mood={p_mood} hunger={p_hunger} affection={p_aff}\n"
        f"  Manager: affection={m_aff} 已学习URL数={m_urls}\n"
    )


def advance_tick(ctx: "WorldContext", every: int = 500) -> bool:
    """把 ctx.tick_count 推进一步,并在每 `every` tick 打印一次世界快照。

    返回这一帧是否触发了打印(方便调用方额外自定义)。
    """
    ctx.tick_count += 1
    last = _LAST_PRINTED_TICK_GLOBAL["v"]
    # 用差值判定,避免因 tick 回退/跨模式恢复导致漏打
    if ctx.tick_count - last >= every:
        _LAST_PRINTED_TICK_GLOBAL["v"] = ctx.tick_count
        snap = _snapshot_world(ctx)
        print(_format_snapshot(snap), flush=True)
        return True
    return False


def reset_tick_print_state() -> None:
    """测试或调试用:重置 500-tick 打印记忆。"""
    _LAST_PRINTED_TICK_GLOBAL["v"] = 0
