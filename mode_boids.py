"""
Boids 鸟群 - 人工生命经典
个体遵循三条简单规则,涌现出群体行为:
  1. 分离 separation:避免拥挤
  2. 对齐 alignment:与邻居方向一致
  3. 聚合 cohesion:朝邻居中心移动
"""
import math
import random

import pygame

import font_utils
from core_types import WorldContext, advance_tick
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
BLUE = (50, 120, 200)
VIOLET = (120, 100, 180)
INK_SOFT = (90, 94, 108)


class Boid:
    def __init__(self, x, y):
        self.pos = pygame.Vector2(x, y)
        a = random.uniform(0, 2 * math.pi)
        self.vel = pygame.Vector2(math.cos(a), math.sin(a)) * 3


def flock(boids, b, perc=60, sep=25):
    """计算作用于 b 的加速度(三规则合成)"""
    align = pygame.Vector2()
    cohes = pygame.Vector2()
    separ = pygame.Vector2()
    c = 0
    sc = 0
    for o in boids:
        if o is b:
            continue
        d = b.pos.distance_to(o.pos)
        if d < perc:
            align += o.vel
            cohes += o.pos
            c += 1
            if 0 < d < sep:
                diff = (b.pos - o.pos) / d
                separ += diff
                sc += 1
    if c > 0:
        align /= c
        if align.length() > 0:
            align = align.normalize() * 3 - b.vel
        cohes /= c
        cohes -= b.pos
        if cohes.length() > 0:
            cohes = cohes.normalize() * 3 - b.vel
    if sc > 0 and separ.length() > 0:
        separ = separ.normalize() * 3
    # 权重:分离最强,聚合最弱
    return align * 1.0 + cohes * 0.8 + separ * 1.5


def run(screen, font, clock, ctx: WorldContext | None = None):
    """运行 Boids 模式。返回 'menu' 或 'quit'。"""
    import quantum_ops as _qo
    import font_utils as _fu
    settings = get_settings()
    small_font = _fu.make_font(15)

    boids = [Boid(random.uniform(0, MAIN_W), random.uniform(0, HEIGHT))
             for _ in range(80)]
    if ctx is not None:
        ctx.boids_list = boids

    # ---- 右侧面板 ----
    sx0 = PANEL_X + SIDE_GAP
    sw0 = SIDE_PANEL_W - 2 * SIDE_GAP
    activity_log = ScrollingLog(sx0, 44, sw0, 196, title="活动日志", max_lines=200)
    activity_log.push("启动鸟群模式(Boids)")
    sliders = [
        Slider(key="boids.sep_w", label="分离系数",
               min_v=0.5, max_v=5.0, step=0.05,
               init_v=settings.get_float("boids.sep_w"),
               x=sx0, y=252, w=sw0, h=16, fmt="{label}: {v:.2f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="boids.ali_w", label="对齐系数",
               min_v=0.2, max_v=3.0, step=0.05,
               init_v=settings.get_float("boids.ali_w"),
               x=sx0, y=310, w=sw0, h=16, fmt="{label}: {v:.2f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="boids.coh_w", label="聚合系数",
               min_v=0.1, max_v=3.0, step=0.05,
               init_v=settings.get_float("boids.coh_w"),
               x=sx0, y=368, w=sw0, h=16, fmt="{label}: {v:.2f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="boids.max_speed", label="最大速度",
               min_v=1, max_v=12, step=0.2,
               init_v=settings.get_float("boids.max_speed"),
               x=sx0, y=426, w=sw0, h=16, fmt="{label}: {v:.1f}",
               on_change=lambda k, v: settings.set(k, v)),
    ]

    tick = 0

    # ---- 底部快捷按钮: 2 列 ----
    btn_y = HEIGHT - 14 - 28
    btn_h = 28
    btn_gap = 10
    btn_w = (sw0 - btn_gap) // 2

    def _do_add20():
        for _ in range(20):
            boids.append(Boid(random.uniform(0, MAIN_W), random.uniform(0, HEIGHT)))
        activity_log.push(f"🔘[按钮] +20 鸟 合计{len(boids)}")

    def _do_reset_slow():
        # 清空+30只慢速随机鸟 + max_speed 设为2.5(通过 settings 不强制)
        boids.clear()
        for _ in range(30):
            b = Boid(random.uniform(0, MAIN_W), random.uniform(0, HEIGHT))
            # 直接缩速度向量到慢
            try:
                if b.vel.length() > 0:
                    b.vel.scale_to_length(min(2.0, b.vel.length()))
            except Exception:
                pass
            boids.append(b)
        activity_log.push(f"🔘[按钮] 重置慢速鸟群(30只) 合计{len(boids)}")

    buttons = [
        TextButton(sx0 + 0 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "+20 鸟", on_click=_do_add20),
        TextButton(sx0 + 1 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "重置慢速", on_click=_do_reset_slow),
    ]

    while True:
        consumed_mouse = False
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return "quit"
            if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                for s in sliders:
                    if s.handle_event(e):
                        consumed_mouse = True; break
                if not consumed_mouse and e.type == pygame.MOUSEBUTTONDOWN:
                    for b in buttons:
                        if b.handle_event(e):
                            consumed_mouse = True; break
            if consumed_mouse: continue
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return "menu"
                elif e.key == pygame.K_SPACE:
                    # +10 只鸟
                    for _ in range(10):
                        boids.append(Boid(random.uniform(0, MAIN_W), random.uniform(0, HEIGHT)))
                    activity_log.push(f"鸟群+10 合计{len(boids)}")

        # 按 settings 提取规则系数
        try:
            sep_w = float(settings.get("boids.sep_w"))
            ali_w = float(settings.get("boids.ali_w"))
            coh_w = float(settings.get("boids.coh_w"))
            max_v = max(0.5, float(settings.get("boids.max_speed")))
        except Exception:
            sep_w, ali_w, coh_w, max_v = 2.0, 1.0, 0.8, 4.0

        for b in boids:
            base = flock(boids, b)
            acc = pygame.Vector2(
                base.x * (sep_w + ali_w + coh_w) / 3.0,
                base.y * (sep_w + ali_w + coh_w) / 3.0,
            )
            b.vel += acc * 0.08
            if b.vel.length() > max_v:
                b.vel.scale_to_length(max_v)
            b.pos += b.vel
            if b.pos.x < 0:
                b.pos.x = MAIN_W
            elif b.pos.x > MAIN_W:
                b.pos.x = 0
            if b.pos.y < 0:
                b.pos.y = HEIGHT
            elif b.pos.y > HEIGHT:
                b.pos.y = 0
        tick += 1

        # ---- 绘制 ----
        screen.fill(WHITE)
        pygame.draw.line(screen, GOLD_DK, (MAIN_W - 1, 0), (MAIN_W - 1, HEIGHT), 2)
        for b in boids:
            ang = math.atan2(b.vel.y, b.vel.x)
            tip = (b.pos.x + math.cos(ang) * 8, b.pos.y + math.sin(ang) * 8)
            l = (b.pos.x + math.cos(ang + 2.5) * 6, b.pos.y + math.sin(ang + 2.5) * 6)
            r = (b.pos.x + math.cos(ang - 2.5) * 6, b.pos.y + math.sin(ang - 2.5) * 6)
            pygame.draw.polygon(screen, BLUE, [tip, l, r])

        draw_label(screen, font, f"Boids: {len(boids)}  (空格+10  ESC返回) tick={tick}",
                   8, 8, BLACK)

        # ---- 右侧 560..800 ----
        inner = draw_side_panel_bg(screen, "🐦 Boids · 活动/设置", small_font)
        activity_log.x = inner.x; activity_log.y = inner.y
        activity_log.w = inner.w; activity_log.h = 196
        activity_log.draw(screen, font, small_font)
        base_y = inner.y + 196 + 12
        positions = [0, 58, 116, 174]
        for s, g in zip(sliders, positions):
            s.x = inner.x; s.w = inner.w; s.y = base_y + g
            s.draw(screen, small_font, small_font)
        # 汇总平均速度 & 隧穿
        total_v = sum(b.vel.length() for b in boids) / max(1, len(boids))
        avg_v_pct = min(100.0, 100.0 * total_v / 12.0)
        ts = _qo.tunnel_stats()
        rate_pct = min(100.0, 100.0 * ts['tunnel_rate'])
        count_pct = min(100.0, 100.0 * len(boids) / max(1, 300))
        card_y = base_y + 232
        card_h = max(40, (HEIGHT - 56) - card_y)
        draw_status_card(
            screen, font, small_font, inner.x, card_y, inner.w, card_h,
            "运行状态", [
                StatusItem("鸟群数", float(count_pct), color=BLUE,
                           fmt=f"{{label}}:{len(boids)}"),
                StatusItem("平均速度", float(avg_v_pct), color=GREEN,
                           fmt=f"速度:{total_v:.2f}"),
                StatusItem("分离", float(min(100, 100*sep_w/5)), color=(200, 100, 90),
                           fmt=f"{{label}}:{sep_w:.2f}"),
                StatusItem("对齐", float(min(100, 100*ali_w/3)), color=(160, 140, 70),
                           fmt=f"{{label}}:{ali_w:.2f}"),
                StatusItem("聚合", float(min(100, 100*coh_w/3)), color=(90, 160, 90),
                           fmt=f"{{label}}:{coh_w:.2f}"),
                StatusItem("隧穿%", float(rate_pct), color=VIOLET),
            ]
        )
        for b in buttons:
            b.draw(screen, small_font)

        pygame.display.flip()
        if ctx is not None:
            advance_tick(ctx, every=500)
        clock.tick(max(1, settings.get_int("global.fps")))


if __name__ == "__main__":
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Boids Flocking")
    clock = pygame.time.Clock()
    font = font_utils.make_font(22)
    run(screen, font, clock)
    pygame.quit()
