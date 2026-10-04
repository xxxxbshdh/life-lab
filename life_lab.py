"""
Life Lab v2 - 生命体 AI 实验室(主入口)
统一菜单 + WorldContext:
  1 - 自主感知 Agent (神经进化决策 + 量子启发采样)
  2 - 生态系统     (基因遗传 + 小龙虾 + 繁殖/隧穿)
  3 - Boids 鸟群   (人工生命涌现)
  4 - 对话宠物     (LLM + 离线降级 + RAG + 持久化)
  5 - Manager 管家 (爱马仕视觉皮层 + 指令调度 + 浏览器学习)

全局 tick_count + 每 500 tick 打印:
  - 量子隧穿累计触发次数
  - 各模式核心指标
"""
from __future__ import annotations

import pygame

import font_utils
from core_types import WorldContext, advance_tick
import quantum_ops
from settings_store import get_settings
from ui_widgets import (
    INK, INK_SOFT, GOLD_DK, draw_status_card, StatusItem,
    draw_side_panel_bg, ScrollingLog, Slider, TextButton, Card, draw_label,
)

import life_agent
import mode_boids
import mode_ecosystem
import mode_pet
import mode_manager

WIDTH, HEIGHT = 800, 600
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
TITLE = (40, 80, 140)
SUB = (110, 110, 110)

MODES = [
    ("1 - 自主感知 Agent (神经进化 + 量子决策)",
     "数字生物:8-16-4 MLP + 量子采样 + 可交叉繁殖",
     life_agent.run),
    ("2 - 生态系统 (基因遗传 + 小龙虾)",
     "植物/食草/捕食/小龙虾: 交叉-突变-隧穿,触须+冲刺滑翔",
     mode_ecosystem.run),
    ("3 - Boids 鸟群 (人工生命 涌现)",
     "分离/对齐/聚合 三规则群体行为",
     mode_boids.run),
    ("4 - 拟人化对话宠物 (LLM + RAG)",
     "情绪/饥饿/好感度 + 真实LLM + 知识增强,离线规则降级",
     mode_pet.run),
    ("5 - Manager 管家 (视觉皮层 + 调度 + 学习)",
     "爱马仕世界感知/意图解析/跨模式调度/浏览器学习知识库",
     mode_manager.run),
]


def draw_menu(screen, font, big_font, ctx: WorldContext):
    screen.fill(WHITE)
    screen.blit(big_font.render("Life Lab v2 - 生命体 AI 实验室", True, TITLE),
                (120, 40))
    sub = ("量子隧穿启发·神经进化·基因遗传·小龙虾物种·爱马仕视觉·"
           "LLM 对话·RAG 知识库·统一管理面板")
    screen.blit(font.render(sub, True, SUB), (50, 86))
    for i, (title, desc, _) in enumerate(MODES):
        y = 130 + i * 70
        pygame.draw.rect(screen, (250, 250, 250), (40, y - 4, 720, 60))
        pygame.draw.rect(screen, (220, 220, 220), (40, y - 4, 720, 60), 1)
        screen.blit(font.render(title, True, BLACK), (55, y))
        screen.blit(font.render(desc, True, SUB), (55, y + 26))
    # 状态栏
    ts = quantum_ops.tunnel_stats()
    foot = (f"Tick {ctx.tick_count}  "
            f"隧穿累计 {ts['tunnel_triggers']} / 进化 {ts['evolution_total']} "
            f"(率≈{ts['tunnel_rate']*100:.3f}%)  "
            f"[S] 游戏设置   ESC 退出")
    screen.blit(font.render(foot, True, SUB), (30, 550))


# ---------- 游戏设置页（S 键呼出） ----------
# 分组设置的滑杆配置: (分组名, key, label, min, max, step, fmt)
_SETTINGS_GROUPS: list[tuple[str, list[tuple[str, str, float, float, float, str]]]] = [
    ("全局", [
        ("global.fps", "FPS", 10, 120, 1, "{label}: {v:.0f}"),
        ("global.auto_save_every_s", "自动存档(秒)", 3, 120, 1, "{label}: {v:.0f}"),
    ]),
    ("宠物", [
        ("pet.auto_sleep_s", "自动休眠(秒)", 5, 600, 5, "{label}: {v:.0f}"),
        ("pet.hunger_decay", "饥饿衰减/tick", 0.002, 0.2, 0.002, "{label}: {v:.3f}"),
        ("pet.affection_per_chat", "每聊天+好感", 0.0, 5.0, 0.1, "{label}: {v:.1f}"),
    ]),
    ("管家", [
        ("mgr.auto_sleep_s", "自动休眠(秒)", 5, 600, 5, "{label}: {v:.0f}"),
        ("mgr.vision_refresh_ticks", "视觉刷新(tick)", 10, 600, 10, "{label}: {v:.0f}"),
    ]),
    ("Agent", [
        ("agent.tunnel_prob_floor", "隧穿保底", 0.0, 0.1, 0.001, "{label}: {v:.3f}"),
        ("agent.hunger_decay", "饥饿衰减/tick", 0.01, 0.5, 0.005, "{label}: {v:.3f}"),
        ("agent.food_spawn_every", "食物刷新(tick)", 10, 500, 10, "{label}: {v:.0f}"),
    ]),
    ("生态", [
        ("eco.crossover_rate", "交叉率", 0.1, 1.0, 0.05, "{label}: {v:.2f}"),
        ("eco.mutation_rate", "突变率", 0.001, 0.3, 0.005, "{label}: {v:.3f}"),
        ("eco.birth_rate_herb", "食草出生率", 0.0, 0.02, 0.0005, "{label}: {v:.4f}"),
        ("eco.birth_rate_pred", "捕食出生率", 0.0, 0.01, 0.0002, "{label}: {v:.4f}"),
        ("eco.crayfish_sensitivity", "小龙虾灵敏度", 0.2, 2.0, 0.05, "{label}: {v:.2f}"),
        ("eco.plant_cap", "植物上限", 20, 300, 5, "{label}: {v:.0f}"),
        ("eco.metabolism_gain", "代谢消耗倍率", 0.2, 3.0, 0.05, "{label}: {v:.2f}"),
    ]),
    ("Boids", [
        ("boids.sep_w", "分离系数", 0.5, 5.0, 0.05, "{label}: {v:.2f}"),
        ("boids.ali_w", "对齐系数", 0.2, 3.0, 0.05, "{label}: {v:.2f}"),
        ("boids.coh_w", "聚合系数", 0.1, 3.0, 0.05, "{label}: {v:.2f}"),
        ("boids.max_speed", "最大速度", 1.0, 12.0, 0.2, "{label}: {v:.1f}"),
    ]),
]


def _build_settings_sliders(settings):
    """根据分组构造滑杆列表(网格布局):左/中/右三列或分两行。"""
    sliders: list[Slider] = []
    # 布局:每组占一整行,y += (分组标题 + N*滑杆高)
    x_cols = [30, 285, 540]
    col_w = 225
    y = 70
    settings_logs: ScrollingLog | None = None
    btn_reset: TextButton | None = None
    btn_close: TextButton | None = None
    # 简单:每组按自己一列铺开,组数 6 → 3列 × 2行的网格
    per_col_groups = [_SETTINGS_GROUPS[:3], _SETTINGS_GROUPS[3:]]
    for col_i, row_groups in enumerate(per_col_groups):
        cx = x_cols[col_i]
        cy = y
        for (grp_name, items) in row_groups:
            cy += 8  # 分组顶间距
            cy += 22  # 分组标题高
            for key, label, mn, mx, step, fmt in items:
                s = Slider(key=key, label=label,
                           min_v=mn, max_v=mx, step=step,
                           init_v=settings.get(key),
                           x=cx, y=cy, w=col_w, h=16,
                           fmt=fmt,
                           on_change=lambda k, v, s=settings: s.set(k, v))
                sliders.append(s)
                cy += 38
    return sliders


def draw_settings_page(screen, font, small_font, ctx, sliders, reset_btn, close_btn, log, settings):
    screen.fill(WHITE)
    # 顶部标题
    title_font = font_utils.make_font(30)
    try:
        screen.blit(title_font.render("【游戏 · 全局设置】（所有模式共用）", True, GOLD_DK),
                    (60, 18))
    except Exception:
        pass
    hint = ("拖拽滑杆实时生效 · 值自动保存到 settings.json   "
            "[S]/ESC 关闭设置   鼠标左键拖滑杆")
    draw_label(screen, small_font, hint, 30, 54, INK_SOFT)

    # 分组小标题(预先计算 y 位置)
    x_cols = [30, 285, 540]
    per_col_groups = [_SETTINGS_GROUPS[:3], _SETTINGS_GROUPS[3:]]
    y = 70
    for col_i, row_groups in enumerate(per_col_groups):
        cx = x_cols[col_i]
        cy = y
        for (grp_name, items) in row_groups:
            cy += 8
            # 分组小卡片标题条
            card = Card(cx - 4, cy - 4, 240, 22 + 38 * len(items) + 14, f"▎{grp_name}")
            inner = card.draw(screen, small_font)
            # 滑杆在 card.draw 之后再画一遍(位置重合,滑杆在 Card 内部)即可
            # 但是我们的 slider x/y 是按 cx/cy 预先计算好的,所以这里只是为了画卡背景;
            # 为让卡背景不盖住 slider 标签,我们把滑杆 draw 顺序放在 card.draw 之后:
            # (上面我们提前绘制过 sliders 列表的位置,这里重绘一次 slider 即可)
            cy += 22  # 分组标题
            cy += 38 * len(items) + 14  # 滑杆行 + 底部 padding
    # 再画一次所有 slider（盖在 Card 内部）
    for s in sliders:
        s.draw(screen, small_font, small_font)

    # 底部状态卡:当前 settings 分组关键字段一览
    ts = quantum_ops.tunnel_stats()
    draw_status_card(
        screen, font, small_font, 30, 498, 520, 92,
        "当前世界快照(主菜单)", [
            StatusItem("Tick", ctx.tick_count % 500, color=(100, 120, 200),
                       fmt="{label}: {v}/500"),
            StatusItem("隧穿触发",
                       min(100.0, 100.0 * ts['tunnel_triggers'] / max(1, ts['evolution_total'])),
                       color=(120, 100, 180),
                       fmt="{label}: {v:.1f}%"),
            StatusItem("FPS", settings.get_int("global.fps"), color=(80, 160, 120)),
            StatusItem("存档", settings.get_int("global.auto_save_every_s"),
                       color=(200, 140, 80), fmt="{label}: {v}s"),
        ]
    )

    # 右下按钮 + 活动日志
    if reset_btn is not None:
        reset_btn.draw(screen, small_font)
    if close_btn is not None:
        close_btn.draw(screen, small_font)
    if log is not None:
        log.title = "设置变更记录"
        log.draw(screen, font, small_font)


def _make_settings_buttons(sliders, settings, log):
    def _reset():
        settings.reset()
        # 把所有 slider 位置同步到最新值
        for s in sliders:
            s.v = settings.get_float(s.key)
        log.push(f"(系统) 已恢复全部默认值并写入 settings.json")

    def _close():
        # main loop 会根据 close_clicked 信号处理
        nonlocal close_clicked
        close_clicked.append(True)
    close_clicked: list[bool] = []

    reset_btn = TextButton(700 - 2 * 96, 564, 90, 26, "恢复默认", on_click=_reset)
    close_btn = TextButton(700 - 92, 564, 90, 26, "关闭(S)", on_click=lambda: close_clicked.append(True))
    return reset_btn, close_btn, close_clicked


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Life Lab v2 · 生命体AI实验室")
    clock = pygame.time.Clock()
    font = font_utils.make_font(22)
    small_font = font_utils.make_font(16)
    big_font = font_utils.make_font(34)
    ctx = WorldContext()

    settings = get_settings()

    # Settings 页面的 UI（懒初始化:第一次进 S 时创建,避免菜单启动慢）
    settings_ui = {"ready": False}

    def ensure_settings_ui():
        if settings_ui["ready"]:
            return
        sliders = _build_settings_sliders(settings)
        log = ScrollingLog(570, 498, 210, 56, title="设置变更记录", max_lines=40)
        reset_btn, close_btn, close_clicked = _make_settings_buttons(sliders, settings, log)

        def _on_change(key, val):
            log.push(f"{key} = {val!r}  →  已保存")

        settings.on_any_change(_on_change)
        settings_ui["sliders"] = sliders
        settings_ui["log"] = log
        settings_ui["reset_btn"] = reset_btn
        settings_ui["close_btn"] = close_btn
        settings_ui["close_clicked"] = close_clicked
        settings_ui["ready"] = True

    state: str | tuple = "menu"

    while True:
        if state == "menu":
            fps_capped = max(1, settings.get_int("global.fps"))
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit(); return
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        pygame.quit(); return
                    if e.key in (pygame.K_s,):
                        ensure_settings_ui()
                        state = "settings"
                        continue
                    if pygame.K_1 <= e.key <= pygame.K_5:
                        state = ("mode", e.key - pygame.K_1)
            advance_tick(ctx, every=500)
            draw_menu(screen, font, big_font, ctx)
            pygame.display.flip()
            clock.tick(fps_capped)

        elif state == "settings":
            ensure_settings_ui()
            fps_capped = max(1, settings.get_int("global.fps"))
            close_flag = settings_ui["close_clicked"]
            consumed = False
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit(); return
                # 滑杆 / 按钮 / 日志:自己消费鼠标事件
                for s in settings_ui["sliders"]:
                    if s.handle_event(e):
                        consumed = True; break
                if consumed: continue
                if settings_ui["reset_btn"].handle_event(e): continue
                if settings_ui["close_btn"].handle_event(e): continue
                if e.type == pygame.KEYDOWN:
                    if e.key in (pygame.K_ESCAPE, pygame.K_s):
                        state = "menu"; break
            if close_flag:
                # 清空"关闭"按钮信号
                close_flag.clear()
                state = "menu"
            advance_tick(ctx, every=500)
            draw_settings_page(
                screen, font, small_font, ctx,
                settings_ui["sliders"],
                settings_ui["reset_btn"],
                settings_ui["close_btn"],
                settings_ui["log"],
                settings,
            )
            pygame.display.flip()
            clock.tick(fps_capped)

        else:
            idx = state[1]  # ("mode", idx)
            fps_menu = max(1, settings.get_int("global.fps"))
            try:
                result = MODES[idx][2](screen, font, clock, ctx)
            except TypeError:
                result = MODES[idx][2](screen, font, clock)
            if result == "quit":
                pygame.quit(); return
            state = "menu"


if __name__ == "__main__":
    main()
