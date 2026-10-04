"""
Pet v2 - 对话宠物(LLM 接入 + 持久化 + 知识增强)
  - LLM: OpenAI 兼容接口,配置在 llm_config.json;无配置/断网→离线规则降级。
  - 持久化:pet_state.json,每 10 秒或退出前保存。
  - 知识增强:对话前用 KnowledgeBase.retrieve() 注入相关学习内容。
"""
from __future__ import annotations

import json
import os
import time

import pygame

import browser_study
import font_utils
from core_types import WorldContext, advance_tick
from settings_store import get_settings
from ui_widgets import (
    PANEL_X, SIDE_PANEL_W, SIDE_GAP,
    draw_side_panel_bg, ScrollingLog, Slider, StatusItem, draw_status_card,
    INK, GOLD_DK, GREEN, BLUE, PINK, SLEEP_COL, draw_label, TextButton,
)
import llm_client

WIDTH, HEIGHT = 800, 600
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
PINK = (255, 180, 200)
BLUE = (80, 150, 230)
GRAY = (120, 120, 120)
SLEEP_COL = (170, 150, 200)  # 休眠紫
AUTO_SLEEP_SECONDS = 30
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "pet_state.json")


def _wake_words_for(pet_name: str) -> list[str]:
    return [pet_name, pet_name + pet_name, "醒醒", "起床", "起来啦", "别睡了", "小懒虫"]


class Pet:
    def __init__(self):
        self.name = "小光"
        self.mood = "neutral"
        self.hunger = 30.0
        self.affection = 50.0
        self.memory: list[str] = []
        self.user_name: str | None = None
        self.online = False  # 最近一次 respond 是否用了 LLM
        self._last_save = time.time()
        # ---- 休眠 ----
        self.sleeping = False
        self._last_activity = time.time()  # 只有"有效输入"或唤醒才重置
        self.auto_sleep_after = AUTO_SLEEP_SECONDS
        # ---- settings 订阅容器,稍后 run() 里 bind_settings 注册 ----
        self._unsubs: list = []

    def bind_settings(self, settings) -> None:
        """订阅全局设置(滑杆一改就生效)。"""
        for f in self._unsubs:
            try: f()
            except Exception: pass
        self._unsubs = []
        self._unsubs.append(settings.subscribe(
            "pet.auto_sleep_s",
            lambda v, s=self: setattr(s, "auto_sleep_after", max(1.0, float(v))))
        )
        if "pet.name" in settings.defaults:
            def _rename(v):
                n = (str(v or "").strip() or self.name)[:12]
                if n: self.name = n
            self._unsubs.append(settings.subscribe("pet.name", _rename))

    # ---------- 休眠/唤醒 ----------
    def _reset_activity(self) -> None:
        self._last_activity = time.time()

    def _is_wake_call(self, text: str) -> bool:
        t = text.strip().lower()
        if not t:
            return False
        for w in _wake_words_for(self.name):
            if w.lower() in t:
                return True
        return False

    def go_sleep(self, reason: str = "idle") -> str:
        """幂等进入休眠,返回给 UI 追加的日志消息。"""
        if self.sleeping:
            return ""
        self.sleeping = True
        self.mood = "neutral"
        return f"(系统){self.name} 睡着了(原因:{reason})。说「{self.name}」或「醒醒」可以叫起来。"

    def wake_up(self) -> str:
        """幂等唤醒。唤醒词 → 高优先级绕过任何中间状态。返回提示消息。"""
        if not self.sleeping:
            return ""
        self.sleeping = False
        self._reset_activity()
        self.mood = "happy"
        self.affection = min(100, self.affection + 1)
        return f"(系统){self.name} 被叫醒啦~ 喊名字或「醒醒」都能随时把我叫起来。"

    def _idle_seconds(self) -> float:
        return max(0.0, time.time() - self._last_activity)

    # ---------- 持久化 ----------
    def save(self, path: str = STATE_PATH) -> None:
        try:
            data = {
                "name": self.name, "mood": self.mood,
                "hunger": self.hunger, "affection": self.affection,
                "memory": self.memory[-30:], "user_name": self.user_name,
                # sleeping 不保存:重开程序默认是醒的,避免"永远睡着"
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._last_save = time.time()
        except OSError:
            pass

    @classmethod
    def load(cls, path: str = STATE_PATH) -> "Pet":
        p = cls()
        if not os.path.exists(path):
            return p
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            p.name = d.get("name", p.name)
            p.mood = d.get("mood", "neutral")
            p.hunger = float(d.get("hunger", 30))
            p.affection = float(d.get("affection", 50))
            p.memory = list(d.get("memory") or [])[-30:]
            p.user_name = d.get("user_name")
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        p.sleeping = False  # 启动时强制醒
        p._reset_activity()
        return p

    # ---------- 离线规则(用作 LLM fallback) ----------
    def rule_respond(self, text: str) -> str:
        t = text.strip()
        if not t:
            return "..."
        if "我叫" in t:
            self.user_name = t.split("我叫")[-1].strip(" 了。.")
            self.affection = min(100, self.affection + 3)
            return f"记住啦,{self.user_name}!很高兴认识你~"
        if any(k in t for k in ["你好", "hi", "hello", "嗨", "在吗"]):
            self.affection = min(100, self.affection + 2)
            self.mood = "happy"
            nm = f",{self.user_name}" if self.user_name else ""
            return f"你好{nm}!今天过得怎么样?"
        if any(k in t for k in ["饿", "吃", "食物", "喂", "feed"]):
            self.hunger = max(0, self.hunger - 30)
            self.affection = min(100, self.affection + 4)
            self.mood = "happy"
            return "谢谢!我吃饱了,好开心~"
        if any(k in t for k in ["喜欢你", "爱你", "抱抱", "摸摸"]):
            self.affection = min(100, self.affection + 8)
            self.mood = "happy"
            return "呜呜好感动!我也最最喜欢你了!"
        if any(k in t for k in ["笨", "讨厌", "丑", "坏"]):
            self.affection = max(0, self.affection - 5)
            self.mood = "sad"
            return "呜...你怎么这么说人家..."
        if any(k in t for k in ["再见", "拜拜", "bye", "走了"]):
            return "下次再来玩哦,我会想你的!"
        if any(k in t for k in ["你是谁", "你叫", "名字"]):
            return f"我是{self.name},你的数字小伙伴!好感度 {int(self.affection)}"
        short = t[:15]
        if self.mood == "happy":
            return f"嘿嘿,{self.user_name or '朋友'},听你说「{short}」我也开心!"
        if self.mood == "sad":
            return f"我有点难过...不过听你说「{short}」好一点了"
        return f"嗯嗯,「{short}」,我记住了!"

    # ---------- 对外 respond (LLM + RAG 增强 + 离线降级) ----------
    def respond(self, text: str, kb: browser_study.KnowledgeBase | None = None) -> str:
        """宠物回复入口。
        关键规则(Experience 825891 反推):
        1) 只把"非空文本"算有效输入,才 reset idle 计时;否则不会阻止休眠。
        2) 休眠态下:唤醒词高优先级,无论任何其他中间标志都能立刻唤醒;
           非唤醒词输入→给提示但**不 reset idle**,也不记忆,不执行 LLM/规则副作用。
        """
        t = text.strip()
        if not t:
            return "..."
        # ---------- 休眠态:高优先级唤醒词拦截 ----------
        if self.sleeping:
            if self._is_wake_call(t):
                note = self.wake_up()  # 已在内部 reset activity
                # 把"唤醒"视为有效输入:附加一句欢迎回复(不进 LLM 以免情绪上下文不连续)
                tail = f"(刚才不小心睡着了... 你说的是「{t}」对吧?"
                if any(k in t for k in ["你好", "hi", "hello", "嗨"]):
                    tail += f" 你好{self.user_name or '!'}我精神了~)"
                else:
                    tail += " 我现在清醒啦~)"
                return note + ("\n" if note else "") + tail
            # 非唤醒词:sleeping 提示,**不 reset idle、不记忆、不进入 LLM 副作用**
            return (f"zzZ...(我在睡觉哦,叫我「{self.name}」或「醒醒」我就起来~)")
        # ---------- 清醒:有效输入 reset 存活计时 ----------
        self._reset_activity()
        # 记忆
        self.memory.append(t)
        if len(self.memory) > 30:
            self.memory = self.memory[-30:]
        # 好感度: settings 决定每聊天 +多少
        try:
            from settings_store import get_settings
            aff = get_settings().get_float("pet.affection_per_chat")
        except Exception:
            aff = 0.5
        self.affection = min(100.0, self.affection + max(0.0, aff))

        # 检索知识库(增强上下文)
        ctx_knowledge: list[str] = []
        if kb is not None:
            ctx_knowledge = kb.retrieve(t, topk=3)

        # 处理显式关键词动作("我叫XX"、喂食等)—— 即使是 LLM 在线,
        # 先调用一次 _rule_side_effects 只做副作用,不返回回复。
        self._rule_side_effects(t)

        system_prompt = (
            f"你是一只叫{self.name}的可爱数字宠物,用简短的中文回复。"
            f"当前情绪:{self.mood},饥饿度:{int(self.hunger)},好感度:{int(self.affection)}。"
            f"主人名字:{self.user_name or '未知'}。"
            "回复要自然、可爱、符合情绪。饥饿时可以暗示想吃东西;好感高时更热情。"
            "如果回复中包含'饿了''饿死了''肚子叫'等关键词,饥饿度会继续上升;"
            "如果包含'谢谢'代表刚被喂食,饥饿度会下降。"
        )

        def fallback(user_msg: str, _ctx):
            # 离线规则时仍然用 rule_respond 生成
            return self.rule_respond(user_msg)

        reply, online = llm_client.llm_chat_or_fallback(
            system_prompt, t, ctx_knowledge or None, fallback,
            temperature=0.85,
        )
        self.online = online

        # 基于关键词更新内部状态(LLM 也能触发)
        if any(k in reply for k in ["好开心", "高兴", "嘿嘿", "喜欢"]):
            self.mood = "happy"
        if any(k in reply for k in ["难过", "伤心", "呜"]):
            self.mood = "sad"
        # 回复太长或太短,轻微调节
        return reply

    def _rule_side_effects(self, t: str) -> None:
        """只做状态变更副作用,不生成回复(LLM 在线/离线都走一遍)。"""
        if "我叫" in t:
            self.user_name = t.split("我叫")[-1].strip(" 了。.")
            self.affection = min(100, self.affection + 3)
        if any(k in t for k in ["你好", "hi", "hello", "嗨"]):
            self.affection = min(100, self.affection + 1)
            self.mood = "happy"
        if any(k in t for k in ["饿", "吃", "喂", "食物"]):
            # 如果用户说"吃什么"可能是问题,但"给你吃/喂你"等算喂食
            if any(k in t for k in ["给你", "喂你", "喂了"]):
                self.hunger = max(0, self.hunger - 30)
                self.affection = min(100, self.affection + 4)
                self.mood = "happy"
        if any(k in t for k in ["抱抱", "摸摸", "亲亲", "爱你"]):
            self.affection = min(100, self.affection + 6)
            self.mood = "happy"
        if any(k in t for k in ["笨", "讨厌", "坏", "丑"]):
            self.affection = max(0, self.affection - 5)
            self.mood = "sad"

    def tick(self) -> str:
        """每帧调用。返回若非空则是给 UI 日志追加的系统消息(例如进入休眠)。"""
        try:
            from settings_store import get_settings
            st = get_settings()
            hunger_rate = st.get_float("pet.hunger_decay")
            save_every = st.get_float("global.auto_save_every_s")
        except Exception:
            hunger_rate = 0.02
            save_every = 10.0
        if hunger_rate <= 0: hunger_rate = 0.02
        if save_every < 1: save_every = 10.0
        # 休眠期间:新陈代谢减慢(饥饿/4),不把情绪切到 sad
        if self.sleeping:
            self.hunger = min(100, self.hunger + hunger_rate * 0.25)
        else:
            self.hunger = min(100, self.hunger + hunger_rate)
            if self.hunger > 80:
                self.mood = "sad"
            # 自动休眠:只有清醒态才判断。30s 无有效输入→睡。
            if self._idle_seconds() >= self.auto_sleep_after:
                return self.go_sleep(reason=f"{int(self._idle_seconds())}s无交流")
        if time.time() - self._last_save > save_every:
            self.save()
        return ""

    def append_incoming(self, msg: str) -> None:
        """Manager 面板"告诉宠物 X"接口:直接作为一轮用户消息处理。"""
        reply = self.respond(msg)
        # Manager 会从 ctx.pet_log 读这条回复
        pass


def draw_face(screen, pet: Pet):
    if pet.sleeping:
        col = SLEEP_COL
    else:
        col = {"happy": PINK, "neutral": BLUE, "sad": GRAY}[pet.mood]
    cx, cy = WIDTH // 2, 170
    pygame.draw.circle(screen, col, (cx, cy), 50)
    # 眼睛
    if pet.sleeping:
        # 闭眼:两条弧线 / 直线 (⏾)
        pygame.draw.arc(screen, BLACK, (cx - 22, cy - 10, 14, 12), 3.14, 0, 2)
        pygame.draw.arc(screen, BLACK, (cx + 8, cy - 10, 14, 12), 3.14, 0, 2)
        # 嘴巴:直线(平静)
        pygame.draw.line(screen, BLACK, (cx - 10, cy + 18), (cx + 10, cy + 18), 2)
        # Z Z Z 浮动字
        import math as _m
        phase = (time.time() % 3) / 3.0
        zs = [("Z", cx + 42, cy - 40 + int(_m.sin(phase * 6.28) * 2), 28),
              ("z", cx + 58, cy - 56 + int(_m.cos(phase * 6.28) * 2), 22),
              ("z", cx + 72, cy - 72 + int(_m.sin(phase * 6.28 + 1.5) * 2), 18)]
        try:
            for ch, x, y, sz in zs:
                f = font_utils.make_font(sz)
                screen.blit(f.render(ch, True, SLEEP_COL), (x, y))
        except Exception:
            pass
    else:
        pygame.draw.circle(screen, BLACK, (cx - 15, cy - 5), 5)
        pygame.draw.circle(screen, BLACK, (cx + 15, cy - 5), 5)
        if pet.mood == "happy":
            pygame.draw.arc(screen, BLACK, (cx - 18, cy + 5, 36, 25), 3.14, 0, 2)
        elif pet.mood == "sad":
            pygame.draw.arc(screen, BLACK, (cx - 18, cy + 15, 36, 25), 0, 3.14, 2)
        else:
            pygame.draw.line(screen, BLACK, (cx - 12, cy + 18), (cx + 12, cy + 18), 2)


def run(screen, font, clock, ctx: WorldContext):
    import font_utils as _fu
    settings = get_settings()
    small_font = _fu.make_font(15)
    pet: Pet = Pet.load()
    pet.bind_settings(settings)
    # 挂到 ctx(用于 Manager 访问)
    ctx.pet_obj = pet
    ctx.pet_log = ctx.pet_log or [f"你好!我是{pet.name},跟我聊天吧~"]
    kb = browser_study.KnowledgeBase()
    input_text = ""

    # ---- 右侧面板(活动日志 + 滑杆 + 状态卡) ----
    sx0 = PANEL_X + SIDE_GAP
    sw0 = SIDE_PANEL_W - 2 * SIDE_GAP
    activity_log = ScrollingLog(sx0, 44, sw0, 186, title="活动日志", max_lines=120)
    sliders = [
        Slider(key="pet.auto_sleep_s", label="自动休眠(秒)",
               min_v=5, max_v=600, step=5,
               init_v=settings.get_float("pet.auto_sleep_s"),
               x=sx0, y=250, w=sw0, h=16, fmt="{label}: {v:.0f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="pet.hunger_decay", label="饥饿衰减/tick",
               min_v=0.002, max_v=0.2, step=0.002,
               init_v=settings.get_float("pet.hunger_decay"),
               x=sx0, y=308, w=sw0, h=16, fmt="{label}: {v:.3f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="pet.affection_per_chat", label="聊天+好感",
               min_v=0.0, max_v=5.0, step=0.1,
               init_v=settings.get_float("pet.affection_per_chat"),
               x=sx0, y=366, w=sw0, h=16, fmt="{label}: +{v:.1f}",
               on_change=lambda k, v: settings.set(k, v)),
    ]

    # ---- 底部快捷按钮 2 列 ----
    btn_y = HEIGHT - 14 - 28
    btn_h = 28
    btn_gap = 10
    btn_w = (sw0 - btn_gap) // 2

    def _do_feed():
        pet.energy = min(100.0, pet.energy + 35.0)
        pet.hunger = max(0.0, pet.hunger - 50.0)
        pet.mood = "happy"
        pet._reset_activity()
        activity_log.push("🔘[按钮] 宠物被喂食:能量+35 饥饿-50")

    def _do_wake():
        if pet.sleeping:
            m = pet.wake_up()
            if m:
                activity_log.push("💢🔘[按钮] " + m)
                ctx.pet_log.append("💢 " + m)
        else:
            pet._reset_activity()
            pet.mood = "happy"
            activity_log.push("🔘[按钮] 宠物清醒,陪它玩了一下 🐾")

    buttons = [
        TextButton(sx0 + 0 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "喂食", on_click=_do_feed),
        TextButton(sx0 + 1 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "唤醒/抚摸", on_click=_do_wake),
    ]

    while True:
        # ---------- 事件 ----------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pet.save()
                return "quit"
            consumed_mouse = False
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
                    pet.save()
                    return "menu"
                elif event.key == pygame.K_RETURN:
                    if input_text.strip():
                        reply = pet.respond(input_text, kb)
                        ctx.pet_log.append("你: " + input_text)
                        ctx.pet_log.append(pet.name + ": " + reply)
                        if len(ctx.pet_log) > 40:
                            ctx.pet_log = ctx.pet_log[-40:]
                        activity_log.push(f"聊天｜你→{input_text}")
                        activity_log.push(f"回复｜{reply[:36]}")
                        input_text = ""
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                else:
                    if len(input_text) < 40 and event.unicode and event.unicode.isprintable():
                        input_text += event.unicode

        sys_msg = pet.tick()
        if sys_msg:
            ctx.pet_log.append(sys_msg)
            activity_log.push(sys_msg)
            if len(ctx.pet_log) > 40:
                ctx.pet_log = ctx.pet_log[-40:]
        # Manager 发来的消息(pet_inbox 队列) → 合并进 pet_log + activity_log
        # （可能在其他模式里被写入,比如模式5的"告诉宠物 我回来了"）
        if isinstance(ctx.pet_inbox, list) and ctx.pet_inbox:
            for m in ctx.pet_inbox:
                ctx.pet_log.append(m)
                activity_log.push(m)
            ctx.pet_inbox = []
            if len(ctx.pet_log) > 40:
                ctx.pet_log = ctx.pet_log[-40:]
        show_log = ctx.pet_log[-7:]

        # ---------- 主区 0..560 ----------
        screen.fill(WHITE)
        pygame.draw.line(screen, GOLD_DK, (559, 0), (559, HEIGHT), 2)
        draw_face_on(screen, pet, cx=560 // 2, cy=168)
        if pet.sleeping:
            idle_info = f"💤 SLEEPING (唤醒词: {pet.name} / 醒醒)"
        else:
            remain = max(0, int(pet.auto_sleep_after - pet._idle_seconds()))
            idle_info = f"{remain}s 后自动休眠(超过{int(pet.auto_sleep_after)}s不说话就睡)"
        status_line = (f"情绪: {pet.mood}  饥饿: {int(pet.hunger)}  "
                       f"好感: {int(pet.affection)}  在线: {'Y' if pet.online else 'N'}")
        screen.blit(font.render(status_line, True,
                                SLEEP_COL if pet.sleeping else BLACK), (10, 10))
        screen.blit(small_font.render(idle_info, True, INK), (10, 36))
        for i, line in enumerate(show_log):
            clip = line[:50] + ("…" if len(line) > 50 else "")
            try:
                sfc = font.render(clip, True, BLACK)
            except Exception:
                continue
            screen.blit(sfc, (20, 260 + i * 24))
        pygame.draw.rect(screen, (230, 230, 230), (10, 520, 540, 30))
        screen.blit(font.render("> " + input_text + "_", True, BLACK), (15, 525))
        screen.blit(small_font.render(
            "回车发送 · ESC返回 · 主菜单按[S]设置全局 · 或拖右侧滑杆",
            True, GRAY), (10, 562))

        # ---------- 右侧 560..800 控制面板 ----------
        inner = draw_side_panel_bg(screen, "🐾 宠物 · 活动/设置", small_font)
        activity_log.x = inner.x; activity_log.y = inner.y
        activity_log.w = inner.w; activity_log.h = 190
        activity_log.draw(screen, font, small_font)
        base_y = inner.y + 190 + 14
        positions = [0, 58, 116]
        for s, g in zip(sliders, positions):
            s.x = inner.x; s.w = inner.w; s.y = base_y + g
            s.draw(screen, small_font, small_font)
        card_y = base_y + 180
        card_h = max(60, (HEIGHT - 56) - card_y)  # 给底部按钮行留 42
        on_v = 95 if pet.online else 30
        draw_status_card(
            screen, font, small_font, inner.x, card_y, inner.w, card_h,
            "状态", [
                StatusItem("饥饿", float(pet.hunger), color=BLUE),
                StatusItem("好感", float(pet.affection), color=PINK),
                StatusItem("在线", float(on_v), color=(GREEN if pet.online else GRAY)),
            ]
        )
        for b in buttons:
            b.draw(screen, small_font)

        pygame.display.flip()
        advance_tick(ctx, every=500)
        clock.tick(max(1, settings.get_int("global.fps")))


def draw_face_on(screen, pet: Pet, cx, cy):
    """在指定 (cx,cy) 画脸(避免硬编码 WIDTH//2 被右侧面板挤偏)。"""
    if pet.sleeping:
        col = SLEEP_COL
    else:
        col = {"happy": PINK, "neutral": BLUE, "sad": GRAY}[pet.mood]
    pygame.draw.circle(screen, col, (cx, cy), 50)
    if pet.sleeping:
        pygame.draw.arc(screen, BLACK, (cx - 22, cy - 10, 14, 12), 3.14, 0, 2)
        pygame.draw.arc(screen, BLACK, (cx + 8, cy - 10, 14, 12), 3.14, 0, 2)
        pygame.draw.line(screen, BLACK, (cx - 10, cy + 18), (cx + 10, cy + 18), 2)
        import math as _m
        phase = (time.time() % 3) / 3.0
        zs = [("Z", cx + 42, cy - 40 + int(_m.sin(phase * 6.28) * 2), 28),
              ("z", cx + 58, cy - 56 + int(_m.cos(phase * 6.28) * 2), 22),
              ("z", cx + 72, cy - 72 + int(_m.sin(phase * 6.28 + 1.5) * 2), 18)]
        for ch, x, y, sz in zs:
            try:
                f = font_utils.make_font(sz)
                screen.blit(f.render(ch, True, SLEEP_COL), (x, y))
            except Exception:
                pass
    else:
        pygame.draw.circle(screen, BLACK, (cx - 15, cy - 5), 5)
        pygame.draw.circle(screen, BLACK, (cx + 15, cy - 5), 5)
        if pet.mood == "happy":
            pygame.draw.arc(screen, BLACK, (cx - 18, cy + 5, 36, 25), 3.14, 0, 2)
        elif pet.mood == "sad":
            pygame.draw.arc(screen, BLACK, (cx - 18, cy + 15, 36, 25), 0, 3.14, 2)
        else:
            pygame.draw.line(screen, BLACK, (cx - 12, cy + 18), (cx + 12, cy + 18), 2)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Pet Chat v2 (LLM + RAG)")
    clock = pygame.time.Clock()
    font = font_utils.make_font(24)
    run(screen, font, clock, WorldContext())
    pygame.quit()


if __name__ == "__main__":
    main()
