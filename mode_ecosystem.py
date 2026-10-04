"""
Ecosystem v2 - 生态系统模式(基因遗传 + 小龙虾物种)
  - 植物 / 食草动物 / 捕食者 / 小龙虾(触须 + 冲刺-滑翔)
  - 每只动物携带 Gene → 表型,繁殖时交叉+突变+隧穿
  - 小龙虾 8 方向触须 HUD 小标记
  - run(screen, font, clock, ctx) 统一接口
"""
from __future__ import annotations

import math
import random

import pygame

import font_utils
import gene_ops
from core_types import Gene, WorldContext, advance_tick
from settings_store import get_settings
from ui_widgets import (
    PANEL_X, SIDE_PANEL_W, SIDE_GAP,
    draw_side_panel_bg, ScrollingLog, Slider, StatusItem, draw_status_card,
    GOLD_DK, GREEN, BLUE, INK, draw_label, TextButton,
)

WIDTH, HEIGHT = 800, 600
FPS = 60
MAIN_W = 560  # 主区宽（世界绘制范围）
VIOLET = (120, 100, 180)
GRAY = (120, 120, 120)
INK_SOFT = (90, 94, 108)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (0, 180, 0)
GRAY = (150, 150, 150)


class Plant:
    def __init__(self, x, y, energy=10):
        self.pos = pygame.Vector2(x, y)
        self.energy = energy


class Animal:
    def __init__(self, x, y, kind: str, gene: Gene | None = None):
        self.pos = pygame.Vector2(x, y)
        self.vel = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        self.energy = 50.0
        self.kind = kind    # 'herb' / 'pred' / 'crayfish'
        self.age = 0
        self.gene = gene or gene_ops.random_gene()
        self.phenotype = gene_ops.gene_to_phenotype(self.gene)

    @property
    def speed(self) -> float:
        return self.phenotype.speed

    @property
    def vision(self) -> float:
        return self.phenotype.vision_radius


# ---------- 小龙虾 ----------
class Crayfish(Animal):
    """小龙虾:8 方向触须 + 冲刺/滑翔 两阶段移动 + 杂食。"""
    SPRINT = 3  # 冲刺帧数
    GLIDE = 5   # 滑翔帧数

    def __init__(self, x, y, gene: Gene | None = None):
        super().__init__(x, y, kind="crayfish", gene=gene)
        self.phase_tick = 0
        self.phase = "sprint"  # sprint 或 glide
        self.antenna: list[float] = [0.0] * 8  # 8 方向距离(归一化 0~1)

    def update_antenna(self, plants, herbs, preds, sensitivity: float = 1.0):
        """每 tick 重新计算 8 方向触须距离(找最近的障碍/食物)。

        sensitivity > 1 → 感知更强(MAX_R 放大),远处物体与墙也能让触须有读数
        sensitivity < 1 → 迟钝,触须大多被归一化到接近1(相当于"空档",会更多探索)
        """
        MAX_R = 80.0 * max(0.1, float(sensitivity))
        angles = [math.radians(a) for a in range(0, 360, 45)]
        others = []
        for p in plants:
            others.append((p.pos.x, p.pos.y, "food"))
        for h in herbs:
            if h is not self:
                others.append((h.pos.x, h.pos.y, "prey" if h.energy < 40 else "obj"))
        for pr in preds:
            others.append((pr.pos.x, pr.pos.y, "threat"))
        for i, a in enumerate(angles):
            # 射线步进,查最近物体或边界
            dx, dy = math.cos(a), math.sin(a)
            d = MAX_R
            for (ox, oy, t) in others:
                # 点到射线距离在一定阈值内视为碰撞
                relx, rely = ox - self.pos.x, oy - self.pos.y
                proj = relx * dx + rely * dy
                if 0 < proj < d:
                    perp = abs(-rely * dx + relx * dy)
                    if perp < 6:
                        d = min(d, proj)
            # 墙体
            if dx > 0:
                d = min(d, (WIDTH - self.pos.x) / dx) if dx > 0 else d
            elif dx < 0:
                d = min(d, -self.pos.x / dx)
            if dy > 0:
                d = min(d, (HEIGHT - self.pos.y) / dy)
            elif dy < 0:
                d = min(d, -self.pos.y / dy)
            self.antenna[i] = max(0.0, min(1.0, d / MAX_R))

    def step_physics(self):
        self.phase_tick += 1
        if self.phase == "sprint" and self.phase_tick >= self.SPRINT:
            self.phase = "glide"
            self.phase_tick = 0
        elif self.phase == "glide" and self.phase_tick >= self.GLIDE:
            self.phase = "sprint"
            self.phase_tick = 0
            # 新冲刺方向:触须最短的反方向(逃离威胁)或最长的方向(探索空档)
            # 简单:选 antenna 最大(空档最大)的方向
            best_i = max(range(8), key=lambda i: self.antenna[i])
            ang = math.radians(best_i * 45)
            self.vel.x = math.cos(ang) * self.speed * 1.5
            self.vel.y = math.sin(ang) * self.speed * 1.5
        if self.phase == "sprint":
            # 加速: 滑翔期间速度无衰减地维持;冲刺期间略加推力
            if self.vel.length() > 0:
                pass
        else:
            # 滑翔期间轻微衰减
            self.vel *= 0.98
        self.pos += self.vel
        # 默认全局限制,具体环境会在 tick_ecosystem 末尾再夹紧一次
        self.pos.x = max(5, min(WIDTH - 5, self.pos.x))
        self.pos.y = max(5, min(HEIGHT - 5, self.pos.y))


# ---------- 生态核心 ----------
class Ecosystem:
    def __init__(self, world_w: int = WIDTH, world_h: int = HEIGHT):
        self.world_w = int(world_w)
        self.world_h = int(world_h)
        self.plants: list[Plant] = [Plant(random.uniform(0, self.world_w), random.uniform(0, self.world_h))
                                    for _ in range(40)]
        self.herbs: list[Animal] = [Animal(random.uniform(0, self.world_w), random.uniform(0, self.world_h), "herb")
                                    for _ in range(15)]
        self.preds: list[Animal] = [Animal(random.uniform(0, self.world_w), random.uniform(0, self.world_h), "pred")
                                    for _ in range(4)]
        self.crayfish: list[Crayfish] = [Crayfish(random.uniform(0, self.world_w), random.uniform(0, self.world_h))
                                         for _ in range(5)]

    def spawn_plants(self, n):
        for _ in range(n):
            self.plants.append(Plant(random.uniform(0, self.world_w), random.uniform(0, self.world_h)))


def _nearest(objs, pos, maxr=250):
    best = None
    bd = maxr
    for o in objs:
        d = pos.distance_to(o.pos)
        if d < bd:
            bd = d
            best = o
    return best, bd


def _reproduce_pair(parent_a: Animal, parent_b: Animal, kind: str,
                    cross_rate: float = 0.85, mutate_rate: float = 0.06):
    # cross_rate 控制"是否做交叉";不命中时相当于无性繁殖(父本A基因突变)
    import dataclasses
    if random.random() <= cross_rate:
        child_gene, _ = gene_ops.reproduce(parent_a.gene, parent_b.gene,
                                           mutate_rate=mutate_rate)
    else:
        a_copy = dataclasses.replace(parent_a.gene)
        child_gene, _ = gene_ops.reproduce(a_copy, a_copy, mutate_rate=mutate_rate)
    if kind == "crayfish":
        c = Crayfish((parent_a.pos.x + parent_b.pos.x) / 2,
                     (parent_a.pos.y + parent_b.pos.y) / 2, gene=child_gene)
    else:
        c = Animal((parent_a.pos.x + parent_b.pos.x) / 2,
                   (parent_a.pos.y + parent_b.pos.y) / 2,
                   kind=kind, gene=child_gene)
    c.energy = 35
    return c


def step_animal(a: Animal, env: Ecosystem):
    if a.kind == "herb":
        target, d = _nearest(env.plants, a.pos, a.vision)
    else:  # pred
        candidates = env.herbs + env.crayfish
        target, d = _nearest(candidates, a.pos, a.vision)
    if target is not None:
        v = pygame.Vector2(target.pos.x - a.pos.x, target.pos.y - a.pos.y)
        if v.length() > 0:
            a.vel += v.normalize() * 0.15
    else:
        a.vel += pygame.Vector2(random.uniform(-0.1, 0.1), random.uniform(-0.1, 0.1))
    if a.vel.length() > a.speed:
        a.vel.scale_to_length(a.speed)
    a.pos += a.vel
    ww = getattr(env, "world_w", WIDTH)
    wh = getattr(env, "world_h", HEIGHT)
    a.pos.x = max(5, min(ww - 5, a.pos.x))
    a.pos.y = max(5, min(wh - 5, a.pos.y))
    a.energy -= a.phenotype.metabolism


def tick_ecosystem(env: Ecosystem):
    # ---------- 读取 settings（若 settings_store 可用） ----------
    try:
        s = get_settings()
        meta_gain = max(0.1, float(s.get_float("eco.metabolism_gain")))
        cross_rate = max(0.0, min(1.0, float(s.get_float("eco.crossover_rate"))))
        mutate_rate = max(0.0, min(1.0, float(s.get_float("eco.mutation_rate"))))
        birth_herb = max(0.0, float(s.get_float("eco.birth_rate_herb")))
        birth_pred = max(0.0, float(s.get_float("eco.birth_rate_pred")))
    except Exception:
        meta_gain, cross_rate, mutate_rate = 1.0, 0.85, 0.06
        birth_herb, birth_pred = 0.004, 0.0022

    # 植物
    if random.random() < 0.3 and len(env.plants) < 60:
        env.spawn_plants(1)

    # 食草
    for h in env.herbs[:]:
        step_animal(h, env)
        h.energy -= (meta_gain - 1.0) * h.phenotype.metabolism
        for p in env.plants[:]:
            if h.pos.distance_to(p.pos) < 10:
                env.plants.remove(p)
                h.energy = min(100, h.energy + 30)
                break
        if h.energy > h.phenotype.reproduce_threshold and random.random() < birth_herb:
            mate, _ = _nearest([x for x in env.herbs if x is not h], h.pos, 200)
            if mate is not None:
                h.energy -= 30
                env.herbs.append(_reproduce_pair(h, mate, "herb",
                                                  cross_rate=cross_rate,
                                                  mutate_rate=mutate_rate))
        if h.energy <= 0:
            env.herbs.remove(h)
        h.age += 1

    # 捕食者
    for p in env.preds[:]:
        step_animal(p, env)
        p.energy -= (meta_gain - 1.0) * p.phenotype.metabolism
        for h in env.herbs[:] + env.crayfish[:]:
            if p.pos.distance_to(h.pos) < 10:
                if isinstance(h, Crayfish):
                    env.crayfish.remove(h)
                else:
                    env.herbs.remove(h)
                p.energy = min(100, p.energy + 40)
                break
        if p.energy > p.phenotype.reproduce_threshold and random.random() < birth_pred:
            mate, _ = _nearest([x for x in env.preds if x is not p], p.pos, 250)
            if mate is not None:
                p.energy -= 35
                env.preds.append(_reproduce_pair(p, mate, "pred",
                                                  cross_rate=cross_rate,
                                                  mutate_rate=mutate_rate))
        if p.energy <= 0:
            env.preds.remove(p)
        p.age += 1

    # 小龙虾
    try:
        cray_sens = max(0.1, float(get_settings().get_float("eco.crayfish_sensitivity")))
    except Exception:
        cray_sens = 0.9
    birth_cray = 0.004  # 暂与 herb 默认接近
    for c in env.crayfish[:]:
        # 灵敏度倍率:影响 update_antenna 中 distance 归一化(用 sens 放大感知深度)
        c.update_antenna(env.plants, env.herbs, env.preds, sensitivity=cray_sens)
        c.step_physics()
        c.energy -= c.phenotype.metabolism * (0.9 * meta_gain)
        # 进食
        ate = False
        for p in env.plants[:]:
            if c.pos.distance_to(p.pos) < 10:
                env.plants.remove(p)
                c.energy = min(100, c.energy + 25)
                ate = True
                break
        if not ate and c.energy < 40:
            # 饥饿:攻击食草幼体
            for h in env.herbs[:]:
                if h.energy < 45 and c.pos.distance_to(h.pos) < 14:
                    env.herbs.remove(h)
                    c.energy = min(100, c.energy + 40)
                    ate = True
                    break
        if c.energy > c.phenotype.reproduce_threshold and random.random() < birth_cray:
            mate, _ = _nearest([x for x in env.crayfish if x is not c], c.pos, 200)
            if mate is not None:
                c.energy -= 30
                env.crayfish.append(_reproduce_pair(c, mate, "crayfish",
                                                     cross_rate=cross_rate,
                                                     mutate_rate=mutate_rate))
        if c.energy <= 0:
            env.crayfish.remove(c)
        c.age += 1

    # 统一夹紧到 env.world_w/world_h（避免旧版 WIDTH 与 MAIN_W 不一致）
    ww = getattr(env, "world_w", WIDTH)
    wh = getattr(env, "world_h", HEIGHT)
    for seq in (env.plants, env.herbs, env.preds, env.crayfish):
        for ent in seq:
            ent.pos.x = max(0, min(ww, ent.pos.x))
            ent.pos.y = max(0, min(wh, ent.pos.y))


def _color_for(a: Animal, default):
    # 表型颜色主色,混合一点默认种色以区分物种
    r, g, b = a.phenotype.color_rgb
    if a.kind == "herb":
        r = int((r + 150) / 2); g = int((g + 100) / 2); b = int((b + 40) / 2)
    elif a.kind == "pred":
        r = int((r + 200) / 2); g = int((g + 40) / 2); b = int((b + 40) / 2)
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _draw_crayfish(screen, c: Crayfish):
    color = _color_for(c, (255, 140, 0))
    pygame.draw.circle(screen, color, (int(c.pos.x), int(c.pos.y)), 7)
    # 触须 HUD 标记:8 条短线
    for i, a in enumerate(range(0, 360, 45)):
        rad = math.radians(a)
        L = 6 + 12 * c.antenna[i]
        x1 = c.pos.x + math.cos(rad) * 8
        y1 = c.pos.y + math.sin(rad) * 8
        x2 = c.pos.x + math.cos(rad) * (8 + L)
        y2 = c.pos.y + math.sin(rad) * (8 + L)
        pygame.draw.line(screen, (255, 100, 0), (int(x1), int(y1)),
                         (int(x2), int(y2)), 1)


def _draw_world(screen, env: Ecosystem, max_x: int | None = None):
    """若 max_x 给定,只显示 x<max_x 的实体并把世界限制在 0..max_x。"""
    mx = max_x if (max_x is not None and max_x > 0) else WIDTH
    for p in env.plants:
        if p.pos.x < mx:
            pygame.draw.circle(screen, GREEN, (int(p.pos.x), int(p.pos.y)), 4)
    for h in env.herbs:
        if h.pos.x < mx:
            pygame.draw.circle(screen, _color_for(h, (150, 100, 40)),
                               (int(h.pos.x), int(h.pos.y)), 6)
    for pr in env.preds:
        if pr.pos.x < mx:
            pygame.draw.circle(screen, _color_for(pr, (200, 40, 40)),
                               (int(pr.pos.x), int(pr.pos.y)), 8)
    for c in env.crayfish:
        if c.pos.x < mx:
            _draw_crayfish(screen, c)


def _update_ctx(env: Ecosystem, ctx: WorldContext):
    ctx.ecosystem_plants = env.plants
    ctx.ecosystem_herbs = env.herbs
    ctx.ecosystem_preds = env.preds
    ctx.ecosystem_crayfish = env.crayfish


def run(screen, font, clock, ctx: WorldContext):
    import quantum_ops as _qo
    import font_utils as _fu
    settings = get_settings()
    small_font = _fu.make_font(15)

    env = Ecosystem(world_w=MAIN_W, world_h=HEIGHT)
    # 应用 Manager 面板挂起的投放
    if ctx.pending_spawn_plants > 0:
        env.spawn_plants(ctx.pending_spawn_plants)
        ctx.pending_spawn_plants = 0
    _update_ctx(env, ctx)
    tick = 0

    # ---- 右侧面板 ----
    sx0 = PANEL_X + SIDE_GAP
    sw0 = SIDE_PANEL_W - 2 * SIDE_GAP
    activity_log = ScrollingLog(sx0, 44, sw0, 196, title="活动日志", max_lines=200)
    activity_log.push("启动生态系统模式")
    sliders = [
        Slider(key="eco.plant_cap", label="植物上限",
               min_v=20, max_v=300, step=5,
               init_v=settings.get_float("eco.plant_cap"),
               x=sx0, y=252, w=sw0, h=16, fmt="{label}: {v:.0f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="eco.metabolism_gain", label="代谢消耗(×)",
               min_v=0.2, max_v=3.0, step=0.05,
               init_v=settings.get_float("eco.metabolism_gain"),
               x=sx0, y=310, w=sw0, h=16, fmt="{label}: {v:.2f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="eco.crossover_rate", label="交叉率",
               min_v=0.1, max_v=1.0, step=0.05,
               init_v=settings.get_float("eco.crossover_rate"),
               x=sx0, y=368, w=sw0, h=16, fmt="{label}: {v:.2f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="eco.mutation_rate", label="突变率",
               min_v=0.001, max_v=0.3, step=0.005,
               init_v=settings.get_float("eco.mutation_rate"),
               x=sx0, y=426, w=sw0, h=16, fmt="{label}: {v:.3f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="eco.birth_rate_herb", label="食草出生率(‰)",
               min_v=0.0, max_v=20.0, step=0.2,
               init_v=settings.get_float("eco.birth_rate_herb") * 1000.0,
               x=sx0, y=484, w=sw0, h=16, fmt="{label}: {v:.1f}",
               on_change=lambda k, v, s=settings: s.set(k, v / 1000.0)),
        Slider(key="eco.birth_rate_pred", label="捕食出生率(‰)",
               min_v=0.0, max_v=10.0, step=0.1,
               init_v=settings.get_float("eco.birth_rate_pred") * 1000.0,
               x=sx0, y=542, w=sw0, h=16, fmt="{label}: {v:.1f}",
               on_change=lambda k, v, s=settings: s.set(k, v / 1000.0)),
    ]

    # ---- 底部快捷按钮 2 列 ----
    btn_y = HEIGHT - 14 - 28
    btn_h = 28
    btn_gap = 10
    btn_w = (sw0 - btn_gap) // 2

    def _do_plant20():
        env.spawn_plants(20)
        activity_log.push(f"🔘[按钮] +20 植物 (合计{len(env.plants)})")

    def _do_species_seed():
        for _ in range(3):
            env.herbs.append(Animal(random.uniform(0, env.world_w), random.uniform(0, env.world_h), "herb"))
        for _ in range(1):
            env.preds.append(Animal(random.uniform(0, env.world_w), random.uniform(0, env.world_h), "pred"))
        for _ in range(2):
            env.crayfish.append(Crayfish(random.uniform(0, env.world_w), random.uniform(0, env.world_h)))
        activity_log.push(
            f"🔘[按钮] 播撒物种:+3食草+1捕食+2🦞, "
            f"合计H{len(env.herbs)}/P{len(env.preds)}/C{len(env.crayfish)}")

    buttons = [
        TextButton(sx0 + 0 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "+20 植物", on_click=_do_plant20),
        TextButton(sx0 + 1 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "+物种种子", on_click=_do_species_seed),
    ]

    while True:
        consumed_mouse = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                for s in sliders:
                    if s.handle_event(event):
                        consumed_mouse = True; break
                if not consumed_mouse and event.type == pygame.MOUSEBUTTONDOWN:
                    for b in buttons:
                        if b.handle_event(event):
                            consumed_mouse = True; break
            if consumed_mouse: continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "menu"
                elif event.key == pygame.K_SPACE:
                    env.spawn_plants(5)
                    activity_log.push(f"投放+5植物 合计{len(env.plants)}")

        tick_ecosystem(env)
        # 植物上限按 settings 裁剪（保留存活）
        try:
            cap = max(10, int(settings.get_int("eco.plant_cap")))
        except Exception:
            cap = 60
        if len(env.plants) > cap:
            env.plants = env.plants[-cap:]
        _update_ctx(env, ctx)
        tick += 1

        # ---------- 绘制 ----------
        screen.fill(WHITE)
        pygame.draw.line(screen, GOLD_DK, (MAIN_W - 1, 0), (MAIN_W - 1, HEIGHT), 2)
        _draw_world(screen, env, max_x=MAIN_W)
        hud = font.render(
            f"[生态] 植物{len(env.plants)}  食草{len(env.herbs)}  "
            f"捕食{len(env.preds)}  🦞{len(env.crayfish)}   tick={tick}   "
            f"(空格+5  ESC返回)", True, BLACK)
        screen.blit(hud, (8, 8))
        # 物种基因摘要（主区内）
        def _mean_gene(xs):
            if not xs:
                return None
            n = len(xs)
            return [
                sum(x.gene.as_list()[i] for x in xs) / n for i in range(5)
            ]
        mh = _mean_gene(env.herbs)
        mp = _mean_gene(env.preds)
        mc = _mean_gene(env.crayfish)
        lines2 = []
        if mh:
            lines2.append(f"食草均:速{mh[0]:.2f} 视{mh[1]:.2f} 攻{mh[2]:.2f} 繁{mh[3]:.2f} 代{mh[4]:.2f}")
        if mp:
            lines2.append(f"捕食均:速{mp[0]:.2f} 视{mp[1]:.2f} 攻{mp[2]:.2f} 繁{mp[3]:.2f} 代{mp[4]:.2f}")
        if mc:
            lines2.append(f"🦞均:速{mc[0]:.2f} 视{mc[1]:.2f} 攻{mc[2]:.2f} 繁{mc[3]:.2f} 代{mc[4]:.2f}")
        for i, line in enumerate(lines2):
            draw_label(screen, small_font, line, 8, 36 + i * 16, INK_SOFT)

        # ---- 右侧 560..800 ----
        inner = draw_side_panel_bg(screen, "🌿 生态 · 活动/设置", small_font)
        activity_log.x = inner.x; activity_log.y = inner.y
        activity_log.w = inner.w; activity_log.h = 160
        activity_log.draw(screen, font, small_font)
        base_y = inner.y + 160 + 12
        positions = [0, 44, 88, 132, 176, 220]
        for s, g in zip(sliders, positions):
            s.x = inner.x; s.w = inner.w; s.y = base_y + g
            s.draw(screen, small_font, small_font)
        card_y = base_y + 268
        card_h = max(40, (HEIGHT - 56) - card_y)  # 底部按钮行留 42
        total_ents = len(env.plants) + len(env.herbs) + len(env.preds) + len(env.crayfish)
        ts = _qo.tunnel_stats()
        rate_pct = min(100.0, 100.0 * ts['tunnel_rate'])
        draw_status_card(
            screen, font, small_font, inner.x, card_y, inner.w, card_h,
            "生态状态", [
                StatusItem("植物", float(min(100, len(env.plants))), color=(90, 160, 90),
                           fmt=f"{{label}}:{len(env.plants)}"),
                StatusItem("食草", float(min(100, len(env.herbs))), color=(160, 140, 70),
                           fmt=f"{{label}}:{len(env.herbs)}"),
                StatusItem("捕食", float(min(100, len(env.preds))), color=(200, 100, 90),
                           fmt=f"{{label}}:{len(env.preds)}"),
                StatusItem("🦞", float(min(100, len(env.crayfish))), color=(180, 60, 80),
                           fmt=f"{{label}}:{len(env.crayfish)}"),
                StatusItem("隧穿%", float(rate_pct), color=VIOLET),
                StatusItem("总实体", float(min(100, total_ents)), color=BLUE,
                           fmt=f"{{label}}:{total_ents}"),
            ]
        )
        for b in buttons:
            b.draw(screen, small_font)
        pygame.display.flip()
        advance_tick(ctx, every=500)
        clock.tick(max(1, settings.get_int("global.fps")))


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Ecosystem v2")
    clock = pygame.time.Clock()
    font = font_utils.make_font(22)
    run(screen, font, clock, WorldContext())
    pygame.quit()


if __name__ == "__main__":
    main()
