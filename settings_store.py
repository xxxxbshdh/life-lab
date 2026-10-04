"""
全局游戏设置（持久化 settings.json）—— 所有"游戏界面设置"的唯一真源
=================================================================
所有模式（包括主菜单 S 键设置页）的滑杆都改这个对象：
  * 模式内部通过 s = settings.get('key') 读取
  * UI 滑杆通过 settings.set('key', value) 写入 → 自动持久化 → 触发订阅回调通知字段变更
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# ---------- 默认值（统一写在这里，避免 5 个模式各写一套默认值导致不一致） ----------
DEFAULT: dict[str, Any] = {
    # 全局
    "global.fps": 60,
    "global.auto_save_every_s": 10,
    # Pet
    "pet.name": "小光",
    "pet.auto_sleep_s": 30,
    "pet.hunger_decay": 0.02,           # 每 tick 饥饿增量 (清醒时)
    "pet.affection_per_chat": 0.5,      # 每次有效聊天 +好感
    # Manager
    "mgr.name": "管家 · 小爱马",
    "mgr.auto_sleep_s": 45,
    "mgr.vision_refresh_ticks": 120,    # 视觉摘要刷新频率 (ticks)
    # Agent (模式1)
    "agent.tunnel_prob_floor": 0.005,   # 量子隧穿基础保底
    "agent.hunger_decay": 0.08,
    "agent.food_spawn_every": 80,
    # Eco (模式2)
    "eco.crossover_rate": 0.85,
    "eco.mutation_rate": 0.06,
    "eco.birth_rate_herb": 0.004,
    "eco.birth_rate_pred": 0.0022,
    "eco.crayfish_sensitivity": 0.9,    # 小龙虾触须灵敏度倍率
    "eco.plant_cap": 60,                # 植物数量上限
    "eco.metabolism_gain": 1.0,         # 代谢消耗倍率(越大竞争越激烈)
    # Boids (模式3) - 与 mode_boids 中的滑杆一一对应
    "boids.sep_w": 2.0,
    "boids.ali_w": 1.0,
    "boids.coh_w": 0.8,
    "boids.max_speed": 4.0,
}


class SettingsStore:
    def __init__(self, path: str = PATH, defaults: dict[str, Any] | None = None):
        self.path = path
        self.defaults = dict(defaults if defaults is not None else DEFAULT)
        self.data: dict[str, Any] = dict(self.defaults)
        self._subs: dict[str, list[Callable[[Any], None]]] = {}
        self._global_subs: list[Callable[[str, Any], None]] = []
        self._last_save = 0.0
        self.load()

    # ---------- 持久化 ----------
    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                for k, v in d.items():
                    self.data[k] = self._coerce(k, v)
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    def save(self, force: bool = False) -> None:
        import time as _t
        now = _t.monotonic()
        if not force and (now - self._last_save) < 2.0:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._last_save = now
        except OSError:
            pass

    def reset(self) -> None:
        self.data = dict(self.defaults)
        self.save(force=True)
        for key, cb in list(self._subs.items()):
            for f in cb:
                try: f(self.data.get(key, self.defaults[key]))
                except Exception: pass
        for f in self._global_subs:
            try:
                for key in self.data: f(key, self.data[key])
            except Exception: pass

    # ---------- 订阅 ----------
    def subscribe(self, key: str, cb: Callable[[Any], None]) -> Callable[[], None]:
        """订阅某个 key 的变更（包括初始化立即回调一次）。
        返回取消订阅的函数。"""
        self._subs.setdefault(key, [])
        self._subs[key].append(cb)
        try: cb(self.data.get(key, self.defaults[key]))
        except Exception: pass
        def _unsub():
            if key in self._subs and cb in self._subs[key]:
                self._subs[key].remove(cb)
        return _unsub

    def on_any_change(self, cb: Callable[[str, Any], None]) -> Callable[[], None]:
        self._global_subs.append(cb)
        def _u():
            if cb in self._global_subs: self._global_subs.remove(cb)
        return _u

    # ---------- 访问 ----------
    def get(self, key: str, default_sentinel=None) -> Any:
        if key in self.data:
            return self.data[key]
        if default_sentinel is not None:
            return default_sentinel
        return self.defaults.get(key)

    def get_int(self, key: str) -> int:
        return int(round(float(self.get(key))))

    def get_float(self, key: str) -> float:
        return float(self.get(key))

    def get_str(self, key: str) -> str:
        v = self.get(key)
        return "" if v is None else str(v)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        value = self._coerce(key, value)
        self.data[key] = value
        # notify subs
        for cb in list(self._subs.get(key, [])):
            try: cb(value)
            except Exception: pass
        for cb in list(self._global_subs):
            try: cb(key, value)
            except Exception: pass
        if save:
            self.save()

    def keys(self) -> list[str]:
        return sorted(self.data.keys())

    def items(self):
        return self.data.items()

    def _coerce(self, key: str, v: Any) -> Any:
        d = self.defaults.get(key)
        if d is None:
            return v
        if isinstance(d, bool):
            return bool(v)
        if isinstance(d, int):
            try: return int(round(float(v)))
            except (TypeError, ValueError): return d
        if isinstance(d, float):
            try: return float(v)
            except (TypeError, ValueError): return d
        if isinstance(d, str):
            return "" if v is None else str(v)
        return v


# 单例
_settings_singleton: SettingsStore | None = None


def get_settings() -> SettingsStore:
    global _settings_singleton
    if _settings_singleton is None:
        _settings_singleton = SettingsStore()
    return _settings_singleton
