"""
Life Lab v2 游戏式 UI 控件（所有模式 + 主菜单共用）
====================================================
统一色板、卡片、标签、滑杆、滚动活动日志、状态条（进度条）。

使用约定：
1) 所有模式统一在屏幕右侧预留 240px = 控制面板区。
2) 参数修改只改 settings_store，模式内部在下一次 tick 时读取生效，避免状态机乱飞。
3) 控件事件（鼠标按下/拖动/释放）统一由 handle_event(e) 分发。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import pygame

# ---------- 统一色板 (爱马仕风：金+米白+紫蓝) ----------
GOLD = (222, 176, 55)
GOLD_DK = (176, 135, 30)
CREAM = (252, 247, 232)
PAPER = (248, 250, 252)
INK = (38, 38, 48)
INK_SOFT = (90, 94, 108)
LINE = (210, 214, 222)
VIOLET = (120, 100, 180)
VIOLET_LT = (180, 168, 220)
SLEEP_COL = (150, 120, 190)
GREEN = (98, 170, 98)
RED = (220, 110, 90)
BLUE = (80, 150, 230)
PINK = (255, 180, 200)

# ---------- 尺寸 ----------
SIDE_PANEL_W = 240  # 右侧面板宽（模式 800x600：主区 560）
SIDE_GAP = 8
PANEL_X = 800 - SIDE_PANEL_W  # 560


@dataclass
class WidgetBase:
    x: int
    y: int
    w: int
    h: int

    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)


# ==========================
#  卡片 (Card)
# ==========================
class Card:
    def __init__(self, x: int, y: int, w: int, h: int, title: str = ""):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.title = title

    def draw(self, screen, font) -> pygame.Rect:
        """画卡片+标题；返回内部可画区域（去掉外边距/标题栏）"""
        outer = pygame.Rect(self.x, self.y, self.w, self.h)
        inner_fill = pygame.Rect(self.x + 2, self.y + 2, self.w - 4, self.h - 4)
        # 金边 + 米白内
        pygame.draw.rect(screen, GOLD, outer, border_radius=8)
        pygame.draw.rect(screen, PAPER, inner_fill, border_radius=7)
        if self.title:
            bar = pygame.Rect(self.x + 3, self.y + 3, self.w - 6, 22)
            pygame.draw.rect(screen, (245, 236, 205), bar,
                             border_top_left_radius=7, border_top_right_radius=7)
            try:
                sfc = font.render(self.title, True, INK)
            except Exception:
                sfc = None
            if sfc is not None:
                screen.blit(sfc, (self.x + 10, self.y + 5))
            inner_top = self.y + 28
        else:
            inner_top = self.y + 6
        inner = pygame.Rect(self.x + 8, inner_top,
                            self.w - 16, self.y + self.h - 6 - inner_top)
        return inner


def draw_label(screen, font, text: str, x, y, color=INK, shadow=False) -> int:
    """画一行文字并返回其逻辑宽度。"""
    try:
        sfc = font.render(text, True, color)
    except Exception:
        return 0
    if shadow:
        shadow_sfc = font.render(text, True, (255, 255, 255, 255))
        screen.blit(shadow_sfc, (x + 1, y + 1))
    screen.blit(sfc, (x, y))
    return sfc.get_width()


# ==========================
#  状态条 (StatusBar / StatusCard)
# ==========================
@dataclass
class StatusItem:
    label: str
    value: float  # 0..100 (或 clamped)
    color: tuple = VIOLET
    fmt: str = "{label}: {v:.0f}"  # v 是原始数值(未除100)


def draw_status_card(screen, font, small_font, x, y, w, h,
                     title: str, items: list[StatusItem]) -> None:
    card = Card(x, y, w, h, title)
    inner = card.draw(screen, font)
    if not items:
        return
    slot_h = inner.h // len(items)
    for i, it in enumerate(items):
        iy = inner.y + i * slot_h + 4
        ih = max(14, min(18, slot_h - 4))
        draw_label(screen, small_font, it.fmt.format(label=it.label, v=it.value),
                   inner.x, iy, INK)
        bar_x = inner.x
        bar_y = iy + 18
        if bar_y + ih > inner.y + inner.h:
            break  # 空间不够不画条
        pygame.draw.rect(screen, (230, 232, 238),
                         (bar_x, bar_y, inner.w, ih), border_radius=4)
        ratio = max(0.0, min(1.0, it.value / 100.0))
        if ratio > 0:
            pygame.draw.rect(screen, it.color,
                             (bar_x, bar_y, int(inner.w * ratio), ih),
                             border_radius=4)


# ==========================
#  活动日志 (ScrollingLog) — 最近 N 条，尾部自动向上滚
# ==========================
class ScrollingLog:
    def __init__(self, x: int, y: int, w: int, h: int,
                 max_lines: int = 60, title: str = "活动"):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.lines: list[tuple[float, str]] = []  # (tick_or_ts, text)
        self.max_lines = max_lines
        self.title = title

    def push(self, text: str, ts: Optional[float] = None) -> None:
        if ts is None:
            ts = time_monotonic()
        self.lines.append((ts, text))
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def draw(self, screen, font, small_font) -> None:
        card = Card(self.x, self.y, self.w, self.h, self.title)
        inner = card.draw(screen, font)
        # 从最后一条往前堆，超出容器截断
        line_h = 16
        max_rows = max(1, inner.h // line_h)
        shown = list(reversed(self.lines[-max_rows:]))
        for i, (_ts, line) in enumerate(shown):
            yy = inner.y + i * line_h
            if yy + line_h > inner.y + inner.h:
                break
            draw_label(screen, small_font, _clip(line, 36),
                       inner.x, yy, INK_SOFT if i % 2 else INK)


def _clip(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def time_monotonic() -> float:
    try:
        import time
        return time.monotonic()
    except Exception:
        return 0.0


# ==========================
#  滑杆 (Slider)
# ==========================
class Slider:
    def __init__(self, key: str, label: str,
                 min_v: float, max_v: float, init_v: float,
                 x: int, y: int, w: int, h: int = 18,
                 step: float | None = None,
                 fmt: str = "{label}: {v:.2f}",
                 on_change: Optional[Callable[[str, float], None]] = None):
        self.key = key
        self.label = label
        self.min_v, self.max_v = float(min_v), float(max_v)
        self.v = float(init_v)
        self.x, self.y, self.w, self.h = x, y, w, h
        self.step = None if step is None else float(step)
        self.fmt = fmt
        self.on_change = on_change
        self._dragging = False

    def set(self, v: float) -> None:
        v = max(self.min_v, min(self.max_v, float(v)))
        if self.step is not None and self.step > 0:
            v = round((v - self.min_v) / self.step) * self.step + self.min_v
            v = max(self.min_v, min(self.max_v, v))
        if abs(v - self.v) > 1e-9:
            self.v = v
            if self.on_change is not None:
                try:
                    self.on_change(self.key, self.v)
                except Exception:
                    pass

    def _ratio(self) -> float:
        if abs(self.max_v - self.min_v) < 1e-12:
            return 0.0
        return (self.v - self.min_v) / (self.max_v - self.min_v)

    def handle_event(self, e) -> bool:
        """返回 True 代表事件被本滑杆消费。"""
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self._hit(e.pos):
                self._dragging = True
                self._set_from_mouse(e.pos[0])
                return True
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if self._dragging:
                self._dragging = False
                return True
        elif e.type == pygame.MOUSEMOTION and self._dragging:
            self._set_from_mouse(e.pos[0])
            return True
        return False

    def _hit(self, pos) -> bool:
        # 扩大一点命中区（标签 + 轨道）
        r = pygame.Rect(self.x, self.y - 2, self.w, self.h + 14)
        return r.collidepoint(pos)

    def _set_from_mouse(self, mx: int) -> None:
        t = (mx - (self.x + 4)) / max(1.0, self.w - 8)
        t = max(0.0, min(1.0, t))
        self.set(self.min_v + (self.max_v - self.min_v) * t)

    def draw(self, screen, small_font, label_font=None) -> None:
        f = label_font or small_font
        txt = self.fmt.format(label=self.label, v=self.v)
        draw_label(screen, f, txt, self.x, self.y - 14, INK)
        # 轨道
        track = pygame.Rect(self.x + 2, self.y + 2, self.w - 4, self.h - 4)
        pygame.draw.rect(screen, (230, 232, 238), track, border_radius=6)
        # 填充
        ratio = self._ratio()
        fill_w = int(max(0.0, track.w) * ratio)
        if fill_w > 0:
            fill = pygame.Rect(track.x, track.y, fill_w, track.h)
            pygame.draw.rect(screen, GOLD, fill, border_radius=6)
        # 把手
        hx = int(track.x + max(0.0, min(track.w, track.w * ratio)))
        handle = pygame.Rect(hx - 5, self.y - 1, 10, self.h + 2)
        pygame.draw.rect(screen, GOLD_DK, handle, border_radius=4)


# ==========================
#  工具栏：小型 Icon 按钮（文字矩形+金边）
# ==========================
class TextButton:
    def __init__(self, x: int, y: int, w: int, h: int, text: str,
                 on_click: Optional[Callable[[], None]] = None,
                 color=GOLD_DK, text_color=INK):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text = text
        self.on_click = on_click
        self.color = color
        self.text_color = text_color

    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)

    def handle_event(self, e) -> bool:
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.rect().collidepoint(e.pos):
                if self.on_click is not None:
                    try:
                        self.on_click()
                    except Exception:
                        pass
                return True
        return False

    def draw(self, screen, font) -> None:
        outer = self.rect()
        fill = pygame.Rect(outer.x + 1, outer.y + 1,
                           outer.w - 2, outer.h - 2)
        pygame.draw.rect(screen, self.color, outer, border_radius=6)
        pygame.draw.rect(screen, CREAM, fill, border_radius=5)
        try:
            sfc = font.render(self.text, True, self.text_color)
        except Exception:
            return
        sx = outer.x + max(0, (outer.w - sfc.get_width()) // 2)
        sy = outer.y + max(0, (outer.h - sfc.get_height()) // 2)
        screen.blit(sfc, (sx, sy))


# ==========================
#  统一：侧边栏的背景（所有模式共用，保证风格一致）
# ==========================
def draw_side_panel_bg(screen, title: str, font) -> pygame.Rect:
    """画出整个 240px 右侧面板背景 + 标题条，返回内部工作区 Rect。"""
    outer = pygame.Rect(PANEL_X, 0, SIDE_PANEL_W, 600)
    pygame.draw.rect(screen, (250, 246, 234), outer)
    pygame.draw.rect(screen, GOLD, outer, 2, border_radius=2)
    # 标题栏
    head = pygame.Rect(PANEL_X + 2, 2, SIDE_PANEL_W - 4, 28)
    pygame.draw.rect(screen, GOLD, head, border_radius=4)
    pygame.draw.rect(screen, (252, 245, 220),
                     (head.x + 2, head.y + 2, head.w - 4, head.h - 4),
                     border_radius=3)
    try:
        sfc = font.render(title, True, GOLD_DK)
    except Exception:
        sfc = None
    if sfc is not None:
        screen.blit(sfc, (PANEL_X + 12, 10))
    inner = pygame.Rect(PANEL_X + SIDE_GAP, 38,
                        SIDE_PANEL_W - 2 * SIDE_GAP, 600 - 38 - SIDE_GAP)
    return inner
