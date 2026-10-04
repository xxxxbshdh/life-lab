"""
字体工具
绕过 pygame 2.6.1 在 Windows 上 SysFont 枚举系统字体时的 bug,
直接加载支持中文的系统字体文件(微软雅黑等)。
"""
import pygame

# 候选字体路径,按优先级尝试
_FONT_PATHS = (
    "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",   # 黑体
    "C:/Windows/Fonts/simsun.ttc",   # 宋体
)


def make_font(size):
    """返回支持中文的字体;系统字体不存在时回退 pygame 默认字体。"""
    for p in _FONT_PATHS:
        try:
            return pygame.font.Font(p, size)
        except Exception:
            continue
    return pygame.font.Font(None, size)
