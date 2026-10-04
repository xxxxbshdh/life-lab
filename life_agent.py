"""
Life Agent v2 - 自主感知 Agent 模式(神经进化版)
- Agent 的决策由 NeuralBrain(8-16-4 MLP)给出,不再用规则。
- 量子启发:softmax 输出按概率采样(不是 argmax),模拟叠加坍缩。
- 按 E 进化:Top 脑与次优脑交叉 + 隧穿/高斯突变产生新 Agent。
- run(screen, font, clock, ctx) 接口与主菜单统一。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum

import pygame

import font_utils
import gene_ops
import quantum_ops
from core_types import WorldContext, advance_tick
from neural_brain import NeuralBrain
from settings_store import get_settings
from ui_widgets import (
    PANEL_X, SIDE_PANEL_W, SIDE_GAP,
    draw_side_panel_bg, ScrollingLog, Slider, StatusItem, draw_status_card,
    GOLD_DK, GREEN, BLUE, INK, draw_label, TextButton,
)

WIDTH, HEIGHT = 800, 600
FPS = 60
MAIN_W = 560

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (0, 200, 0)
RED = (200, 0, 0)
BLUE = (0, 100, 255)
YELLOW = (255, 200, 0)
GRAY = (150, 150, 150)
LIGHT_GRAY = (210, 210, 210)
PURPLE = (150, 80, 200)
VIOLET = (120, 100, 180)
INK_SOFT = (90, 94, 108)


class Action(Enum):
    MOVE_TO_FOOD = 0
    EAT = 1
    REST = 2
    WANDER = 3


ACTION_ZH = ["觅食移动", "进食", "休息", "探索"]


@dataclass
class Food:
    x: float
    y: float
    energy: float = 25.0


class Agent:
    def __init__(self, x: float, y: float,
                 brain: NeuralBrain | None = None,
                 gene=None):
        self.x = x
        self.y = y
        self.energy = 80.0
        self.hunger = 30.0
        self.mood = "neutral"  # happy/neutral/sad
        self.age = 0
        self.alive = True

        self.brain = brain or NeuralBrain()
        self.gene = gene or gene_ops.random_gene()
        self.phenotype = gene_ops.gene_to_phenotype(self.gene)
        self.vision_radius = self.phenotype.vision_radius
        self.speed = self.phenotype.speed
        self.last_action: Action = Action.WANDER
        self.last_probs: list[float] = [0.25, 0.25, 0.25, 0.25]
        # 死亡时仍保留 brain,供 Top 进化
        self.score = 0.0  # 死亡时 age + energy 快照,作为 fitness

    # ---------- 感知 ----------
    def perceive(self, foods):
        visible = []
        for f in foods:
            d = math.hypot(f.x - self.x, f.y - self.y)
            if d <= self.vision_radius:
                visible.append((f, d))
        visible.sort(key=lambda kv: kv[1])
        return visible

    # ---------- 决策(NN + 量子采样) ----------
    def think(self, visible_food) -> Action:
        if not self.alive:
            return Action.REST
        # 构造 8 维观测
        mood_code = {"happy": 1.0, "neutral": 0.0, "sad": -1.0}[self.mood]
        if visible_food:
            f, d = visible_food[0]
            ang = math.atan2(f.y - self.y, f.x - self.x)
            fa_sin = math.sin(ang)
            fa_cos = math.cos(ang)
            fd_norm = min(1.0, d / self.vision_radius)
        else:
            fa_sin = 0.0
            fa_cos = 0.0
            fd_norm = 1.0
        # 简化:威胁 = 0 占位,保留接口
        ta_sin, ta_cos = 0.0, 0.0
        obs = [
            self.energy / 100.0,
            self.hunger / 100.0,
            mood_code,
            fa_sin, fa_cos, fd_norm,
            ta_cos, ta_sin,
        ]
        probs = self.brain.forward(obs)
        self.last_probs = probs
        idx = quantum_ops.sample_from_softmax(probs)
        return Action(idx)

    # ---------- 行动 ----------
    def act(self, action: Action, visible_food, foods,
            hunger_decay: float = 0.04, tunnel_floor: float = 0.005):
        if not self.alive:
            return
        self.last_action = action
        meta = self.phenotype.metabolism

        # 量子隧穿保底:极低概率强迫一次"探索/进食"跃迁
        if random.random() < tunnel_floor:
            if visible_food:
                action = Action.EAT
            else:
                action = Action.WANDER

        if action == Action.MOVE_TO_FOOD and visible_food:
            f, _ = visible_food[0]
            self.move_toward(f.x, f.y)
            self.energy -= 0.05 + meta * 0.5
        elif action == Action.EAT:
            if visible_food:
                f, d = visible_food[0]
                if d < 15:
                    self.energy = min(100, self.energy + f.energy)
                    self.hunger = max(0, self.hunger - 40)
                    if f in foods:
                        foods.remove(f)
                    self.mood = "happy"
            else:
                self.energy -= meta * 0.3
        elif action == Action.REST:
            self.energy = min(100, self.energy + 0.25)
            self.mood = "neutral"
        elif action == Action.WANDER:
            self.wander()
            self.energy -= 0.06 + meta * 0.4

        self.hunger = min(100, self.hunger + hunger_decay)
        if self.hunger > 80:
            self.energy -= 0.1
        if self.energy < 20:
            self.mood = "sad"
        if self.energy <= 0:
            self.alive = False
            self.score = self.age + max(0, self.energy) + self.hunger * 0.0
        self.age += 1

    def move_toward(self, tx, ty):
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        if d > 0:
            self.x += (dx / d) * self.speed
            self.y += (dy / d) * self.speed
        self._clamp()

    def wander(self):
        ang = random.uniform(0, 2 * math.pi)
        self.x += math.cos(ang) * self.speed
        self.y += math.sin(ang) * self.speed
        self._clamp()

    def _clamp(self):
        self.x = max(10, min(MAIN_W - 10, self.x))
        self.y = max(10, min(HEIGHT - 10, self.y))


# ---------- 环境 ----------
class Environment:
    def __init__(self, world_w: int = MAIN_W, world_h: int = HEIGHT,
                 food_spawn_every: int = 80, food_cap: int = 30):
        self.world_w = max(60, int(world_w))
        self.world_h = max(60, int(world_h))
        self.foods: list[Food] = []
        self._tick = 0
        self.food_spawn_every = max(1, int(food_spawn_every))
        self.food_cap = max(5, int(food_cap))
        self.spawn_food(15)

    def spawn_food(self, n=1):
        for _ in range(n):
            self.foods.append(Food(
                x=random.uniform(20, self.world_w - 20),
                y=random.uniform(20, self.world_h - 20),
            ))

    def update(self):
        self._tick += 1
        if self._tick % max(1, self.food_spawn_every) == 0 and len(self.foods) < self.food_cap:
            self.spawn_food(1)


# ---------- 渲染 ----------
def draw_agent(screen, agent: Agent):
    color = {"happy": GREEN, "neutral": BLUE, "sad": RED}.get(agent.mood, GRAY)
    if not agent.alive:
        color = GRAY
    pygame.draw.circle(screen, LIGHT_GRAY, (int(agent.x), int(agent.y)),
                       int(agent.vision_radius), 1)
    # 表型颜色叠加外圈(显示基因特征)
    col = agent.phenotype.color_rgb
    pygame.draw.circle(screen, col, (int(agent.x), int(agent.y)), 14, 1)
    pygame.draw.circle(screen, color, (int(agent.x), int(agent.y)), 10)


def draw_food(screen, f: Food):
    pygame.draw.circle(screen, YELLOW, (int(f.x), int(f.y)), 4)


def draw_hud(screen, agent: Agent, env: Environment, font, small_font, clock, ctx: WorldContext,
             max_x: int = MAIN_W):
    """把左上角HUD与右下NN概率条限制在主区(0..max_x)内,避免越到右侧面板。"""
    hud_lines = [
        f"FPS {int(clock.get_fps())}  Tick {ctx.tick_count}",
        f"Age {agent.age}   存活:{agent.alive}",
        f"能量 {agent.energy:5.1f}    饥饿 {agent.hunger:5.1f}",
        f"情绪 {agent.mood}   最近动作 {ACTION_ZH[agent.last_action.value]}",
        f"速度 {agent.speed:.2f} 视野 {agent.vision_radius:.0f}",
        f"基因型 {gene_ops.gene_summary(agent.gene, digits=2)}",
        f"进化次数 {ctx.agent_evolution_count}",
        "R 重生   E 进化   ESC 返回",
    ]
    for i, line in enumerate(hud_lines):
        draw_label(screen, small_font, line, 8, 8 + i * 16, BLACK)

    # 能量/饥饿进度条（紧凑）
    bx, by = 8, 148
    pygame.draw.rect(screen, GRAY, (bx, by, 180, 8), 1)
    pygame.draw.rect(screen, GREEN, (bx + 1, by + 1, max(0, int(1.78 * agent.energy)), 6))
    pygame.draw.rect(screen, GRAY, (bx, by + 10, 180, 8), 1)
    pygame.draw.rect(screen, RED, (bx + 1, by + 11, max(0, int(1.78 * agent.hunger)), 6))
    # NN 4 条概率条(放在 bottom-right of 主区)
    rx = max_x - 175
    ry = HEIGHT - 12 - 4 * 20
    draw_label(screen, small_font, "NN决策分布(量子采样)", rx, ry - 18, PURPLE)
    for i, name in enumerate(["觅食", "进食", "休息", "探索"]):
        draw_label(screen, small_font, name, rx, ry + i * 20, BLACK)
        pygame.draw.rect(screen, GRAY, (rx + 40, ry + i * 20 + 4, 130, 10), 1)
        w = int(agent.last_probs[i] * 128)
        pygame.draw.rect(screen, PURPLE, (rx + 41, ry + i * 20 + 5, max(0, w), 8))


# ---------- 主循环 ----------
def _update_ctx(ctx: WorldContext, agent: Agent, env: Environment):
    ctx.agent_obj = agent
    # Top/Second brain:存活的用 age+energy 估算;死亡的用 score
    cur = agent.brain.to_flat()
    if ctx.agent_best_brain_flat is None:
        ctx.agent_best_brain_flat = cur
        ctx.agent_second_brain_flat = cur
    else:
        # 只有 fitness 改善才换 Top
        cur_fit = agent.score if not agent.alive else agent.age + agent.energy
        prev_fit = ctx.agent_evolution_count * 5.0 + 80.0  # 占位;只按当前更优替换
        # 简化:直接作为当前 best,原 best 下沉为 second
        if cur != ctx.agent_best_brain_flat:
            ctx.agent_second_brain_flat = ctx.agent_best_brain_flat
            ctx.agent_best_brain_flat = cur


def run(screen, font, clock, ctx: WorldContext):
    import font_utils as _fu
    settings = get_settings()
    small_font = _fu.make_font(15)

    # ---- 从 settings 读取环境参数初始化 ----
    fse = max(1, int(settings.get_float("agent.food_spawn_every")))
    env = Environment(world_w=MAIN_W, world_h=HEIGHT, food_spawn_every=fse, food_cap=30)

    # 若 ctx 已有 agent_best_brain_flat,优先以此 brain 生成新 Agent(保持进化链)
    brain = None
    if ctx.agent_best_brain_flat is not None:
        try:
            brain = NeuralBrain.from_flat(ctx.agent_best_brain_flat)
        except Exception:
            brain = None
    agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2, brain=brain)

    # Manager 标记的重置 -> 生成全新随机个体
    if getattr(ctx, "agent_reset_pending", False):
        ctx.agent_reset_pending = False
        agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2)
    _update_ctx(ctx, agent, env)

    # ---- 右侧面板 ----
    sx0 = PANEL_X + SIDE_GAP
    sw0 = SIDE_PANEL_W - 2 * SIDE_GAP
    activity_log = ScrollingLog(sx0, 44, sw0, 176, title="活动日志", max_lines=220)
    activity_log.push("启动模式1:自主Agent(神经进化+量子采样)")
    sliders = [
        Slider(key="agent.tunnel_prob_floor", label="隧穿保底",
               min_v=0.0, max_v=0.1, step=0.001,
               init_v=settings.get_float("agent.tunnel_prob_floor"),
               x=sx0, y=234, w=sw0, h=16, fmt="{label}: {v:.3f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="agent.hunger_decay", label="饥饿衰减/tick",
               min_v=0.01, max_v=0.5, step=0.005,
               init_v=settings.get_float("agent.hunger_decay"),
               x=sx0, y=292, w=sw0, h=16, fmt="{label}: {v:.3f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="agent.food_spawn_every", label="食物刷新(tick)",
               min_v=10, max_v=500, step=10,
               init_v=settings.get_float("agent.food_spawn_every"),
               x=sx0, y=350, w=sw0, h=16, fmt="{label}: {v:.0f}",
               on_change=lambda k, v, e=env, s=settings: (s.set(k, v),
                    setattr(e, "food_spawn_every", max(1, int(v))))),
    ]

    last_action = agent.last_action
    tick_counter = 0
    dead_for_ticks = 0
    auto_respawn_after = 90  # 约 1.5 秒 @60fps

    # ---- 底部快捷按钮(右侧面板最下方一行 3 个) ----
    btn_y = HEIGHT - 14 - 28
    btn_h = 28
    btn_gap = 10
    btn_w = (sw0 - 2 * btn_gap) // 3

    def _do_reset():
        nonlocal agent, dead_for_ticks
        agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2)
        _update_ctx(ctx, agent, env)
        activity_log.push("🔘[按钮] R 重生:随机基因/随机脑")
        dead_for_ticks = 0

    def _do_evolve():
        nonlocal agent
        bf = ctx.agent_best_brain_flat
        sf = ctx.agent_second_brain_flat
        if bf is None:
            activity_log.push("🔘[进化] 尚无Top脑,跳过")
            return
        a1 = NeuralBrain.from_flat(bf)
        a2 = NeuralBrain.from_flat(sf) if sf is not None else NeuralBrain()
        mut_rate = max(0.0, min(1.0, settings.get_float("eco.mutation_rate")
                                if "eco.mutation_rate" in settings.defaults else 0.06))
        child = a1.crossover(a2)
        stats = child.mutate(rate=mut_rate,
                             tunnel_rate=max(0.0, settings.get_float("agent.tunnel_prob_floor")))
        ctx.agent_second_brain_flat = ctx.agent_best_brain_flat
        ctx.agent_best_brain_flat = child.to_flat()
        ctx.agent_evolution_count += 1
        agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2, brain=child)
        _update_ctx(ctx, agent, env)
        activity_log.push(
            f"🔘[按钮] E进化#{ctx.agent_evolution_count}:突变{stats['mutations']}位,"
            f"隧穿{'Y' if stats['tunnel_hits'] else 'N'}")
        dead_for_ticks = 0

    def _do_food50():
        env.spawn_food(50)
        activity_log.push(f"🔘[按钮] +50食物 (合计{len(env.foods)})")

    buttons = [
        TextButton(sx0 + 0 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "R 重生", on_click=_do_reset),
        TextButton(sx0 + 1 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "E 进化", on_click=_do_evolve),
        TextButton(sx0 + 2 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "+50食物", on_click=_do_food50),
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
                elif event.key == pygame.K_r:
                    agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2)
                    _update_ctx(ctx, agent, env)
                    activity_log.push("R:Agent已重置(随机基因/随机脑)")
                    dead_for_ticks = 0
                elif event.key == pygame.K_e:
                    # 进化:Top × Second 繁殖
                    bf = ctx.agent_best_brain_flat
                    sf = ctx.agent_second_brain_flat
                    if bf is None:
                        activity_log.push("[进化]尚无Top脑,跳过")
                        a1 = NeuralBrain()
                    else:
                        a1 = NeuralBrain.from_flat(bf)
                    if sf is None:
                        a2 = NeuralBrain()
                    else:
                        a2 = NeuralBrain.from_flat(sf)
                    child = a1.crossover(a2)
                    stats = child.mutate(
                        rate=max(0.0, min(1.0, settings.get_float("eco.mutation_rate")
                                          if "eco.mutation_rate" in settings.defaults else 0.06)),
                        tunnel_rate=max(0.0, settings.get_float("agent.tunnel_prob_floor")))
                    ctx.agent_second_brain_flat = ctx.agent_best_brain_flat
                    ctx.agent_best_brain_flat = child.to_flat()
                    ctx.agent_evolution_count += 1
                    note = (f"E:进化 #{ctx.agent_evolution_count}: 突变{stats['mutations']}位,"
                            f" 隧穿{'Y' if stats['tunnel_hits'] else 'N'}")
                    print(f"[继承] Top脑 × Second脑 → 新生Agent: " + note)
                    activity_log.push(note)
                    agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2, brain=child)
                    _update_ctx(ctx, agent, env)
                    dead_for_ticks = 0

        env.update()
        visible = agent.perceive(env.foods)
        action = agent.think(visible)
        hunger_decay = max(0.0, settings.get_float("agent.hunger_decay"))
        tunnel_floor = max(0.0, settings.get_float("agent.tunnel_prob_floor"))
        agent.act(action, visible, env.foods,
                  hunger_decay=hunger_decay, tunnel_floor=tunnel_floor)
        _update_ctx(ctx, agent, env)
        tick_counter += 1

        # ---------- 自动复活(避免死亡后卡住) ----------
        if not agent.alive:
            dead_for_ticks += 1
            if dead_for_ticks >= auto_respawn_after:
                # 优先用进化(Top脑+突变),否则随机基因
                if ctx.agent_evolution_count > 0 and ctx.agent_best_brain_flat is not None:
                    bf = ctx.agent_best_brain_flat
                    try:
                        a1 = NeuralBrain.from_flat(bf)
                    except Exception:
                        a1 = NeuralBrain()
                    a2 = NeuralBrain.from_flat(ctx.agent_second_brain_flat) if ctx.agent_second_brain_flat is not None else NeuralBrain()
                    mut_rate = max(0.0, min(1.0, settings.get_float("eco.mutation_rate")
                                            if "eco.mutation_rate" in settings.defaults else 0.06))
                    child = a1.crossover(a2)
                    stats = child.mutate(
                        rate=mut_rate,
                        tunnel_rate=max(0.0, settings.get_float("agent.tunnel_prob_floor")))
                    ctx.agent_second_brain_flat = ctx.agent_best_brain_flat
                    ctx.agent_best_brain_flat = child.to_flat()
                    ctx.agent_evolution_count += 1
                    agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2, brain=child)
                    activity_log.push(
                        f"♻️ 自动复活(进化) #{ctx.agent_evolution_count}: 突变{stats['mutations']}位,"
                        f" 隧穿{'Y' if stats['tunnel_hits'] else 'N'}")
                else:
                    agent = Agent(x=MAIN_W / 2, y=HEIGHT / 2)
                    activity_log.push("♻️ 自动复活(随机新生)")
                _update_ctx(ctx, agent, env)
                dead_for_ticks = 0
        else:
            dead_for_ticks = 0

        # 活动日志:动作切换 / 死亡 / 进食
        if action != last_action:
            activity_log.push(f"动作切换: {ACTION_ZH[last_action.value]} → {ACTION_ZH[action.value]}")
            last_action = action
        if action == Action.EAT and agent.mood == "happy" and tick_counter % 10 == 0:
            # 避免刷屏,但保证可见
            pass
        if not agent.alive and tick_counter % 30 == 1:
            activity_log.push(f"⚠️ Agent已死亡! 年龄{agent.age},按R重生或E进化")

        # ---------- 绘制 ----------
        screen.fill(WHITE)
        pygame.draw.line(screen, GOLD_DK, (MAIN_W - 1, 0), (MAIN_W - 1, HEIGHT), 2)
        for f in env.foods:
            draw_food(screen, f)
        draw_agent(screen, agent)
        draw_hud(screen, agent, env, font, small_font, clock, ctx, max_x=MAIN_W)

        # ---- 右侧 560..800 ----
        inner = draw_side_panel_bg(screen, "🧠 Agent · 活动/设置", small_font)
        activity_log.x = inner.x; activity_log.y = inner.y
        activity_log.w = inner.w; activity_log.h = 176
        activity_log.draw(screen, font, small_font)
        base_y = inner.y + 176 + 12
        positions = [0, 58, 116]
        for s, g in zip(sliders, positions):
            s.x = inner.x; s.w = inner.w; s.y = base_y + g
            s.draw(screen, small_font, small_font)
        # 状态卡(给底部按钮行留 42px = 28 高 + 14 上间距)
        card_y = base_y + 178
        card_h = max(60, (HEIGHT - 56) - card_y)  # HEIGHT-14-42
        ts = quantum_ops.tunnel_stats()
        rate_pct = min(100.0, 100.0 * ts['tunnel_rate'])
        energy_pct = max(0.0, min(100.0, float(agent.energy)))
        hunger_pct = max(0.0, min(100.0, float(agent.hunger)))
        age_pct = min(100.0, agent.age / 10.0 * 100.0 if agent.age < 10 else 100.0)
        alive_v = 100.0 if agent.alive else 0.0
        foods_pct = min(100.0, 100.0 * len(env.foods) / max(1, env.food_cap))
        evol_pct = min(100.0, ctx.agent_evolution_count / max(1, 20) * 100.0)
        draw_status_card(
            screen, font, small_font, inner.x, card_y, inner.w, card_h,
            "Agent 运行状态", [
                StatusItem("能量", energy_pct, color=GREEN, fmt="{label}: {v:.0f}%"),
                StatusItem("饥饿", hunger_pct, color=RED, fmt="{label}: {v:.0f}%"),
                StatusItem("存活", alive_v, color=(GREEN if agent.alive else GRAY),
                           fmt="{label}: " + ("Y" if agent.alive else "N")),
                StatusItem("年龄", age_pct, color=BLUE,
                           fmt="{label}: " + str(int(agent.age))),
                StatusItem("食物", foods_pct, color=YELLOW,
                           fmt="{label}: " + str(len(env.foods))),
                StatusItem("进化#", evol_pct, color=PURPLE,
                           fmt="{label}: " + str(int(ctx.agent_evolution_count))),
                StatusItem("隧穿%", float(rate_pct), color=VIOLET),
            ]
        )
        # 底部按钮行(最上层,不被任何东西盖住)
        for b in buttons:
            b.draw(screen, small_font)

        pygame.display.flip()
        advance_tick(ctx, every=500)
        clock.tick(max(1, settings.get_int("global.fps")))


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Life Agent v2 - 神经进化")
    clock = pygame.time.Clock()
    font = font_utils.make_font(22)
    ctx = WorldContext()
    run(screen, font, clock, ctx)
    pygame.quit()


if __name__ == "__main__":
    main()
