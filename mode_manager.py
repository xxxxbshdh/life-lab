"""
Manager Pet v2 - 统一管理面板
  - 左:4 个子系统实时卡片 + 视觉皮层文字摘要
  - 右:与 Manager 对话(LLM + 规则关键词解析为 ParsedInstruction 并执行)
  - 底:"学习网页 URL" / "学习粘贴文本"入口(浏览器 RAG 知识库)
  - Manager 状态持久化 manager_state.json
"""
from __future__ import annotations

import json
import os
import random
import re
import time

import pygame

import browser_study
import font_utils
from core_types import InstructionIntent, ParsedInstruction, WorldContext, advance_tick
from settings_store import get_settings
from ui_widgets import (
    PANEL_X, SIDE_PANEL_W, SIDE_GAP,
    draw_side_panel_bg, ScrollingLog, Slider, StatusItem, draw_status_card,
    GOLD_DK, GREEN, BLUE, INK, INK_SOFT, draw_label, TextButton,
)
import gene_ops
import llm_client
from vision_cortex import VisionCortex

WIDTH, HEIGHT = 800, 600
FPS = 60
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GOLD = (240, 180, 30)
GRAY = (120, 120, 120)
DARK = (40, 40, 40)
LIGHT = (240, 240, 240)
LINE = (200, 200, 200)
SLEEP_COL = (150, 120, 190)
MANAGER_AUTO_SLEEP = 45  # 45s 无指令自动休眠(管家中度容忍)

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "manager_state.json")


def _mgr_wake_words(mgr_name: str) -> list[str]:
    """Manager 唤醒词:全名、别名、通用唤醒词。"""
    words = ["管家", "醒醒", "起床", "起来啦", "别睡了", "小爱马", "管家小爱马"]
    cleaned = mgr_name.replace("·", "").replace(" ", "")
    words.append(cleaned)
    words.append(mgr_name)
    return [w for w in words if w]


class Manager:
    def __init__(self):
        self.name = "管家 · 小爱马"
        self.affection = 50.0
        self.memory: list[str] = []
        self.learned_urls: list[str] = []
        self.conversation_log: list[str] = []
        self.online = False
        self._last_save = time.time()
        # ---- 休眠 ----
        self.sleeping = False
        self._last_activity = time.time()
        self.auto_sleep_after = MANAGER_AUTO_SLEEP
        # ---- settings 订阅容器(稍后 bind_settings) ----
        self._unsubs: list = []
        self.vision_refresh_ticks = 120

    def bind_settings(self, settings) -> None:
        for f in self._unsubs:
            try: f()
            except Exception: pass
        self._unsubs = []
        self._unsubs.append(settings.subscribe(
            "mgr.auto_sleep_s",
            lambda v, s=self: setattr(s, "auto_sleep_after", max(1.0, float(v)))))
        self._unsubs.append(settings.subscribe(
            "mgr.vision_refresh_ticks",
            lambda v, s=self: setattr(s, "vision_refresh_ticks", max(5, int(round(float(v)))))))
        if "mgr.name" in settings.defaults:
            def _rename(v):
                n = (str(v or "").strip() or self.name)[:16]
                if n: self.name = n
            self._unsubs.append(settings.subscribe("mgr.name", _rename))

    # ---------- 休眠/唤醒(幂等;唤醒词高优先级) ----------
    def _reset_activity(self) -> None:
        self._last_activity = time.time()

    def _idle_seconds(self) -> float:
        return max(0.0, time.time() - self._last_activity)

    def _is_wake_call(self, text: str) -> bool:
        t = text.strip().lower()
        if not t:
            return False
        for w in _mgr_wake_words(self.name):
            if not w:
                continue
            if w.lower() in t:
                return True
        return False

    def go_sleep(self, reason: str = "idle") -> str:
        if self.sleeping:
            return ""
        self.sleeping = True
        return (f"(系统){self.name} 进入休眠(原因:{reason})。"
                f"喊「管家」「小爱马」或「醒醒」可立即唤醒。")

    def wake_up(self) -> str:
        if not self.sleeping:
            return ""
        self.sleeping = False
        self._reset_activity()
        self.affection = min(100, self.affection + 1)
        return f"(系统){self.name} 已被唤醒,在线待命。"

    def save(self, path=STATE_PATH):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "name": self.name, "affection": self.affection,
                    "memory": self.memory[-50:],
                    "learned_urls": list(dict.fromkeys(self.learned_urls)),
                    # sleeping 不持久化:重启自动醒
                }, f, ensure_ascii=False, indent=2)
            self._last_save = time.time()
        except OSError:
            pass

    @classmethod
    def load(cls, path=STATE_PATH):
        m = cls()
        if not os.path.exists(path):
            return m
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            m.name = d.get("name", m.name)
            m.affection = float(d.get("affection", 50))
            m.memory = list(d.get("memory") or [])[-50:]
            m.learned_urls = list(d.get("learned_urls") or [])
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        m.sleeping = False
        m._reset_activity()
        return m

    def tick(self) -> str:
        """主循环每帧调用;若非空则为 UI 日志要追加的系统消息。"""
        try:
            from settings_store import get_settings
            save_every = max(1.0, get_settings().get_float("global.auto_save_every_s"))
        except Exception:
            save_every = 12.0
        if not self.sleeping and self._idle_seconds() >= self.auto_sleep_after:
            return self.go_sleep(reason=f"{int(self._idle_seconds())}s无指令")
        if time.time() - self._last_save > save_every:
            self.save()
        return ""


# ============================================================
# 意图解析器(先规则关键词,规则识别不到走 LLM)
# ============================================================
def _parse_instruction_rule(text: str) -> ParsedInstruction | None:
    t = text.strip()
    tl = t.lower()
    # 1. 投放植物: "在生态系统投放 N 株植物" / "加植物 N"
    m = re.search(r"(?:生态(?:系统)?(?:里|中)?)(?:投放|加|增加|生成|生成).*?(\d+).*?(?:株|个|颗|棵)?植物", t)
    if m:
        return ParsedInstruction(InstructionIntent.SPAWN_PLANTS, {"n": int(m.group(1))})
    # 简式"加 N 植物"
    m = re.search(r"(?:投放|加|生成).*?(\d+).*?植物", t)
    if m:
        return ParsedInstruction(InstructionIntent.SPAWN_PLANTS, {"n": int(m.group(1))})
    if "投放植物" in t or "多放一点植物" in t:
        return ParsedInstruction(InstructionIntent.SPAWN_PLANTS, {"n": 10})

    # 2. 让 Agent 重生 / 重置 Agent
    if any(k in t for k in ["重生 agent", "重生Agent", "重置 agent", "重置Agent", "Agent 重生", "agent重生"]):
        return ParsedInstruction(InstructionIntent.RESET_AGENT, {})
    if any(k in t for k in ["让agent重生", "让 Agent 重生"]):
        return ParsedInstruction(InstructionIntent.RESET_AGENT, {})

    # 3. 告诉宠物 X
    m = re.search(r"告诉(?:对话)?宠物(.+)", t)
    if m:
        payload = m.group(1).strip(" :：-")
        return ParsedInstruction(InstructionIntent.PET_SEND_MSG, {"msg": payload})

    # 4. 学习 URL
    m = re.search(r"(?:学习|浏览|爬取|抓取).*?(https?://\S+)", tl)
    if m:
        return ParsedInstruction(InstructionIntent.STUDY_URL, {"url": m.group(1)})
    m = re.search(r"(https?://\S+)", t)
    if m and (any(k in t for k in ["学习", "读", "看", "浏览"]) or len(t) < 50):
        return ParsedInstruction(InstructionIntent.STUDY_URL, {"url": m.group(1)})

    # 5. 学习文本(用户输入文本而非 URL)
    if any(k in t for k in ["学习文本", "记住:", "记住：", "记一下", "帮我记"]) or t.startswith("learn:"):
        return ParsedInstruction(InstructionIntent.LEARN_TEXT, {"text": t[5:] if t.startswith("learn:") else t})

    # 6. 生态调节:食草 ×2、捕食 -1
    m = re.search(r"(?:生态(?:系统)?(?:里|中)?)(?:调|调一下|改|变化).*?(食草|捕食|植物|小龙虾).*?(\d+)", t)
    if m:
        return ParsedInstruction(InstructionIntent.ECO_ADJUST,
                                 {"kind": m.group(1), "delta": int(m.group(2))})
    return None


def _parse_instruction_llm(text: str) -> ParsedInstruction | None:
    """用 LLM 解析意图,失败返回 None。"""
    cfg = llm_client.load_config()
    if cfg is None:
        return None
    opts = ", ".join([f"{i.name}={i.value}" for i in InstructionIntent])
    sys = ("你是一个意图解析器,只返回一个 JSON: {\"intent\": \"INTENT\",\"payload\": {KEY:VAL}}。"
           f"可选 INTENT 有: {opts}。 payload 字段可选: n(数字), msg(字符串), url(字符串), "
           "kind(字符串: 食草/捕食/植物/小龙虾), delta(数字)。"
           "无法判断就返回 {} 空对象。 只返回 JSON,不要 Markdown 代码块。")
    client = llm_client.LLMClient(cfg)
    try:
        raw = client.chat(sys, text, temperature=0.1, timeout=8)
    except Exception:
        return None
    if not raw:
        return None
    # 剥离 ```json``` 包裹
    s = raw.strip().strip("`")
    if s.startswith("json"):
        s = s[4:].strip()
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return None
    intent_v = d.get("intent")
    if not intent_v:
        return None
    try:
        intent = InstructionIntent(intent_v)
    except ValueError:
        # 可能是 key 名
        try:
            intent = InstructionIntent[str(intent_v).upper()]
        except (KeyError, ValueError):
            return None
    return ParsedInstruction(intent, payload=d.get("payload") or {})


def parse_instruction(text: str) -> ParsedInstruction | None:
    inst = _parse_instruction_rule(text)
    if inst is not None:
        return inst
    return _parse_instruction_llm(text)


# ============================================================
# 指令执行:修改 WorldContext(某些修改是"挂起",等下一次进入子模式时应用)
# ============================================================
def execute_instruction(inst: ParsedInstruction, ctx: WorldContext,
                        kb: browser_study.KnowledgeBase,
                        manager: Manager) -> str:
    """执行指令并返回用户可读的结果描述。"""
    try:
        if inst.intent == InstructionIntent.SPAWN_PLANTS:
            n = max(1, min(100, int(inst.payload.get("n") or 5)))
            ctx.pending_spawn_plants += n
            # 如果生态列表已经存在(用户当前在同一次会话访问过),直接现场创建一些
            if ctx.ecosystem_plants is not None:
                import mode_ecosystem as eco_mod
                for _ in range(n):
                    ctx.ecosystem_plants.append(eco_mod.Plant(
                        random.uniform(20, 800 - 20), random.uniform(20, 600 - 20)))
            return f"[执行] 挂起+即时投放 {n} 株植物。下次进入生态模式会再补足。"

        if inst.intent == InstructionIntent.RESET_AGENT:
            ctx.agent_obj = None
            ctx.agent_best_brain_flat = ctx.agent_second_brain_flat = None
            ctx.agent_reset_pending = True
            return "[执行] Agent 已标记为重置,进入模式1时会创建全新随机个体。"

        if inst.intent == InstructionIntent.PET_SEND_MSG:
            msg = inst.payload.get("msg") or ""
            if not msg:
                return "[无效] 消息为空"
            if ctx.pet_obj is None:
                # 初始化一次 Pet(不启动模式也能推消息)
                import mode_pet
                ctx.pet_obj = mode_pet.Pet.load()
            pet = ctx.pet_obj
            ctx.pet_log = ctx.pet_log or []
            ctx.pet_inbox = ctx.pet_inbox if isinstance(ctx.pet_inbox, list) else []
            # 休眠态+唤醒词 → 真的唤醒
            if getattr(pet, "sleeping", False):
                # 复用 Pet._is_wake_call 或直接按规则判断
                waked = False
                t = msg.strip().lower()
                if t and any(w.lower() in t for w in [getattr(pet, "name", ""), "小光", "醒醒", "你好", "起床"]):
                    try:
                        w_msg = pet.wake_up()
                        if w_msg:
                            ctx.pet_inbox.append("💢 " + w_msg)
                            ctx.pet_log.append("💢 " + w_msg)
                        waked = True
                    except Exception:
                        pass
                if not waked:
                    # 休眠态下送到信箱(不进pet_log,避免"睡着还聊天")
                    ctx.pet_inbox.append("💤 [休眠中转达] " + msg)
                    return f"[执行] 宠物休眠中,已代为送达(等它醒会看到):{msg[:30]}"
            reply = pet.respond(msg, kb)
            try:
                pet._reset_activity()
            except Exception:
                pass
            ctx.pet_log.append("🧭管家 → 宠物: " + msg)
            ctx.pet_log.append(f"{pet.name}: " + reply)
            ctx.pet_inbox.append("🧭管家 → 宠物: " + msg)
            ctx.pet_inbox.append(f"{pet.name}: " + reply)
            return f"[执行] 送达宠物 → 宠物回复: {reply}"

        if inst.intent == InstructionIntent.STUDY_URL:
            url = (inst.payload.get("url") or "").strip()
            if not url:
                return "[无效] URL 空"
            manager.learned_urls.append(url)
            manager.learned_urls = list(dict.fromkeys(manager.learned_urls))
            # 真正抓网页:requests 取 HTML → 剥标签 → 入 KB;失败自动 fallback 占位
            added, words, status_msg = browser_study.study_url(url)
            return (f"[执行] 学习 URL: {url}\n → {status_msg}"
                    f"({added}片 / {words}词)。你可以用'查一下 XX'指令让宠物引用这些知识。")

        if inst.intent == InstructionIntent.LEARN_TEXT:
            text = inst.payload.get("text") or ""
            if len(text.strip()) < 4:
                return "[无效] 文本太短"
            added, words = browser_study.study_text(url="manual", text=text)
            manager.memory.append(text[:80])
            return f"[执行] 学完了!新增 {added} 片,约 {words} 词。"

        if inst.intent == InstructionIntent.ECO_ADJUST:
            kind = inst.payload.get("kind") or ""
            delta = int(inst.payload.get("delta") or 0)
            return f"[提示] 指令已识别:生态调节 kind={kind}, delta={delta}。(当前版本仅支持投放植物 + 文本学习,其余后续实现)"
    except Exception as e:
        return f"[执行异常] {type(e).__name__}: {e}"
    return f"[未处理] {inst.intent.value}"


# ============================================================
# Manager 回复(LLM + 增强上下文:视觉摘要 + 执行结果 + RAG 知识)
# ============================================================
def build_system_prompt(mgr: Manager, ctx: WorldContext, vision_summary: str) -> str:
    # 收集子系统指标
    def _safe_attr(o, k, default):
        try:
            return getattr(o, k, default)
        except Exception:
            return default
    parts = []
    parts.append(f"你是{mgr.name},Life Lab v2 的管家管理者,性格热情负责、中文简短回复。")
    parts.append(f"好感度:{int(mgr.affection)}。已学习过的 URL:{len(mgr.learned_urls)}")
    if ctx.agent_obj is not None:
        a = ctx.agent_obj
        parts.append(f"自主Agent:age={_safe_attr(a,'age',0)}, alive={_safe_attr(a,'alive',True)},"
                     f"energy={_safe_attr(a,'energy',0):.0f},hunger={_safe_attr(a,'hunger',0):.0f},"
                     f"进化次数={ctx.agent_evolution_count}")
    else:
        parts.append("自主Agent:未启动。")
    plants = len(ctx.ecosystem_plants) if ctx.ecosystem_plants else 0
    herbs = len(ctx.ecosystem_herbs) if ctx.ecosystem_herbs else 0
    preds = len(ctx.ecosystem_preds) if ctx.ecosystem_preds else 0
    cray = len(ctx.ecosystem_crayfish) if ctx.ecosystem_crayfish else 0
    parts.append(f"生态:植物{plants} 食草{herbs} 捕食{preds} 小龙虾{cray};"
                 f"挂起投放:{ctx.pending_spawn_plants}")
    bo = len(ctx.boids_list) if ctx.boids_list else 0
    parts.append(f"Boids: {bo}")
    p = ctx.pet_obj
    if p is not None:
        parts.append(f"宠物:情绪={_safe_attr(p,'mood','?')},饥饿={int(_safe_attr(p,'hunger',0))},"
                     f"好感={int(_safe_attr(p,'affection',0))},在线={_safe_attr(p,'online',False)}")
    else:
        parts.append("宠物:未启动。")
    parts.append(f"[视觉皮层最新摘要] {vision_summary}")
    parts.append("回复要求:简短中文,主动关心世界动态;能给用户提建议(例如'植物数量不多,要不要投放10株?'。)"
                 "如果要执行指令,直接回复内容即可,系统会自动识别关键词再执行一次。")
    return "\n".join(parts)


def manager_chat(mgr: Manager, ctx: WorldContext, user_text: str,
                 kb: browser_study.KnowledgeBase, vision_summary: str,
                 exec_report: str | None):
    """与 Manager 对话:LLM 优先,带上下文。返回 (reply, online, instruction_or_None, inst_exec_report)。"""
    t = user_text.strip()
    if not t:
        return "(空输入...)", False, None, None
    # ---------- 休眠态:高优先级唤醒词拦截 ----------
    if mgr.sleeping:
        if mgr._is_wake_call(t):
            note = mgr.wake_up()
            tail = f"(我是管家·小爱马,你说的是「{t}」对吧?恢复在线了~)"
            return (note + ("\n" if note else "") + tail, False, None, None)
        # 非唤醒词:不 reset、不进解析器、不进 LLM、不记忆
        return (f"zzZ...(管家在休眠哦,喊「管家」「小爱马」或「醒醒」就能立即唤醒~)"
                ), False, None, None
    # ---------- 清醒:有效输入 reset activity 存活计时 ----------
    mgr._reset_activity()
    # 1. 先解析指令
    inst = parse_instruction(user_text)
    inst_exec_report = None
    if inst is not None:
        inst_exec_report = execute_instruction(inst, ctx, kb, mgr)
    # 2. LLM / fallback
    sys_prompt = build_system_prompt(mgr, ctx, vision_summary)
    extra_context_lines = []
    if exec_report:
        extra_context_lines.append(f"[上一步执行结果] {exec_report}")
    if inst_exec_report:
        extra_context_lines.append(f"[本次指令执行结果] {inst_exec_report}")
    # RAG 增强
    kb_hits = kb.retrieve(user_text, topk=3)
    for h in kb_hits:
        extra_context_lines.append(f"[知识库相关片段] {h[:200]}")

    def fallback(u, c):
        # 离线: 给简单模板
        replies = [
            f"收到~ 世界现在:植物{len(ctx.ecosystem_plants) or 0}只,Agent 进化过{ctx.agent_evolution_count}次。你想调整什么?",
            f"我是{mgr.name}。(离线模式)指令可以直接说:'在生态系统投放 10 株植物'、'告诉宠物你好'、'学习 https://...'",
            f"嗯~{u}。(离线)要不试试投放植物?按 1-5 主菜单能看到详细数据卡片。",
        ]
        if inst_exec_report:
            return f"(离线){inst_exec_report}"
        return random.choice(replies)

    reply, online = llm_client.llm_chat_or_fallback(
        sys_prompt, user_text, extra_context_lines or None, fallback,
        temperature=0.8,
    )
    mgr.online = online
    # 好感轻度调节
    if "谢谢" in user_text or "辛苦了" in user_text:
        mgr.affection = min(100, mgr.affection + 2)
    mgr.memory.append(user_text[:120])
    if len(mgr.memory) > 50:
        mgr.memory = mgr.memory[-50:]
    return reply, online, inst, inst_exec_report


# ============================================================
# UI
# ============================================================
def _card(screen, x, y, w, h, title, lines, color=DARK):
    pygame.draw.rect(screen, LIGHT, (x, y, w, h))
    pygame.draw.rect(screen, LINE, (x, y, w, h), 1)
    small = pygame.font.Font(None, 18)  # 英文不渲染中文(保险:pygame 默认)
    small = None  # placeholder
    # 我们统一用外部传入的 font 绘制,这里不绘制标题


def draw_ui(screen, font, small_font, mgr: Manager, ctx: WorldContext,
            vision_summary: str, chat_log: list[str],
            input_box: str, url_box: str):
    screen.fill(WHITE)
    # ===== 头部 =====
    pygame.draw.rect(screen, (250, 245, 220), (0, 0, WIDTH, 50))
    if mgr.sleeping:
        status_note = "💤 SLEEPING (喊「管家」「小爱马」「醒醒」)"
        head_col = SLEEP_COL
    else:
        remain = max(0, mgr.auto_sleep_after - int(mgr._idle_seconds()))
        status_note = f"{remain}s 后自动休眠(>{mgr.auto_sleep_after}s无指令)"
        head_col = DARK
    screen.blit(font.render(f"【{mgr.name}】统一管理面板    好感度:{int(mgr.affection)}   "
                            f"在线:{'Y' if mgr.online else 'N'}   tick={ctx.tick_count}   {status_note}",
                            True, head_col), (10, 12))

    # ===== 左列:四张系统卡 (x 10~400, y 60~380) =====
    card_w, card_h = 370, 78
    cards = [
        _agent_card_lines(ctx),
        _eco_card_lines(ctx),
        _boids_card_lines(ctx),
        _pet_card_lines(ctx),
    ]
    titles = ["① 自主Agent", "② 生态系统", "③ Boids鸟群", "④ 对话宠物"]
    for i, (tt, lines) in enumerate(zip(titles, cards)):
        x, y = 10, 60 + i * (card_h + 6)
        pygame.draw.rect(screen, LIGHT, (x, y, card_w, card_h))
        pygame.draw.rect(screen, LINE, (x, y, card_w, card_h), 1)
        screen.blit(font.render(tt, True, DARK), (x + 6, y + 4))
        for j, line in enumerate(lines):
            screen.blit(small_font.render(line, True, (60, 60, 60)),
                        (x + 8, y + 28 + j * 17))

    # ===== 右列:聊天 (x 400~790, y 60~440) =====
    x, y = 395, 60
    w, h = 395, 380
    pygame.draw.rect(screen, LIGHT, (x, y, w, h))
    pygame.draw.rect(screen, LINE, (x, y, w, h), 1)
    screen.blit(font.render("与管家对话 (回车发送)", True, DARK), (x + 6, y + 4))
    chat_lines = chat_log[-10:]
    for j, line in enumerate(chat_lines):
        # 过长截断
        show = line if len(line) <= 42 else line[:40] + "…"
        screen.blit(small_font.render(show, True, DARK), (x + 8, y + 28 + j * 20))

    # 输入框(聊天)
    pygame.draw.rect(screen, WHITE, (x, y + h - 32, w - 120, 30))
    pygame.draw.rect(screen, LINE, (x, y + h - 32, w - 120, 30), 1)
    screen.blit(small_font.render(">> " + input_box + "_", True, DARK),
                (x + 6, y + h - 28))
    screen.blit(small_font.render("回车发", True, GRAY),
                (x + w - 110, y + h - 26))

    # ===== 底部分两栏:视觉摘要 (左 10~400) + URL学习 (右 400~790) =====
    by = 450
    # 视觉摘要
    screen.blit(font.render("【爱马仕视觉皮层】世界感知摘要", True, DARK), (10, by))
    pygame.draw.rect(screen, (250, 248, 230), (10, by + 26, 370, 120))
    pygame.draw.rect(screen, LINE, (10, by + 26, 370, 120), 1)
    # 按宽度自动换行
    wrapped = _wrap_cn(vision_summary, 22)
    for j, line in enumerate(wrapped[:5]):
        screen.blit(small_font.render(line, True, (60, 50, 30)),
                    (14, by + 30 + j * 18))

    # URL学习 + 隧穿统计
    screen.blit(font.render("【浏览器学习 / 量子隧穿统计】", True, DARK), (400, by))
    pygame.draw.rect(screen, (240, 248, 255), (400, by + 26, 390, 120))
    pygame.draw.rect(screen, LINE, (400, by + 26, 390, 120), 1)
    # URL 输入框
    pygame.draw.rect(screen, WHITE, (404, by + 30, 310, 26))
    pygame.draw.rect(screen, LINE, (404, by + 30, 310, 26), 1)
    screen.blit(small_font.render("URL: " + url_box + "_", True, DARK),
                (408, by + 33))
    screen.blit(small_font.render("[URL-回车学习]", True, (30, 70, 160)),
                (716, by + 33))
    # 隧穿统计
    stats = quantum_ops.tunnel_stats()
    line1 = (f"隧穿统计:累计触发 {stats['tunnel_triggers']} 次  "
             f"(进化/繁殖总数 {stats['evolution_total']},"
             f" 触发率≈{stats['tunnel_rate']*100:.3f}%)")
    line2 = f"已登记学习 URL 共 {len(mgr.learned_urls)} 个(最近:{(mgr.learned_urls[-1] if mgr.learned_urls else '无')})"
    screen.blit(small_font.render(line1, True, DARK), (404, by + 64))
    screen.blit(small_font.render(line2, True, DARK), (404, by + 86))
    line3 = ("使用方法: '学习 https://X.com/...' 或 '记住:我最喜欢的颜色是蓝色'   "
             "ESC 返回菜单")
    screen.blit(small_font.render(line3, True, GRAY), (404, by + 108))


def _agent_card_lines(ctx: WorldContext):
    a = ctx.agent_obj
    if a is None:
        return ["未启动,进入模式 1 会创建。",
                f"保留Top脑: {'Y' if ctx.agent_best_brain_flat else 'N'}  进化次数:{ctx.agent_evolution_count}"]
    return [
        f"Age={getattr(a,'age','?')}  alive={getattr(a,'alive','?')}",
        f"能量{getattr(a,'energy',0):.0f} 饥饿{getattr(a,'hunger',0):.0f} 情绪{getattr(a,'mood','?')}",
        f"动作{getattr(a,'last_action','?')} 速度{getattr(a,'speed',0):.2f} 进化{ctx.agent_evolution_count}",
    ]


def _eco_card_lines(ctx: WorldContext):
    return [
        f"植物{len(ctx.ecosystem_plants) if ctx.ecosystem_plants else 0}  "
        f"食草{len(ctx.ecosystem_herbs) if ctx.ecosystem_herbs else 0}",
        f"捕食{len(ctx.ecosystem_preds) if ctx.ecosystem_preds else 0}  "
        f"小龙虾{len(ctx.ecosystem_crayfish) if ctx.ecosystem_crayfish else 0}",
        f"挂起投放:{ctx.pending_spawn_plants} (下次进入模式2生效)",
    ]


def _boids_card_lines(ctx: WorldContext):
    if ctx.boids_list is None:
        return ["未启动,进入模式 3。", "预期 Boids ≈ 80 只"]
    return [f"当前 {len(ctx.boids_list)} 只",
            "规则: 分离/对齐/聚合"]


def _pet_card_lines(ctx: WorldContext):
    p = ctx.pet_obj
    if p is None:
        return ["未启动,进入模式 4。", "Manager 也可发指令'告诉宠物 X'"]
    return [
        f"情绪{p.mood} 饥饿{int(p.hunger)} 好感{int(p.affection)}",
        f"在线:{'Y' if getattr(p,'online',False) else 'N'}  "
        f"主人:{p.user_name or '未设定'}",
        f"对话日志条数:{len(ctx.pet_log) if ctx.pet_log else 0}",
    ]


def _wrap_cn(s: str, width: int):
    """简单中文/英文混合按字符宽度换行。"""
    lines, cur, acc = [], "", 0
    for ch in s:
        w = 2 if ord(ch) > 127 else 1
        if acc + w > width:
            lines.append(cur)
            cur, acc = ch, w
        else:
            cur += ch
            acc += w
    if cur:
        lines.append(cur)
    return lines or [""]


# ============================================================
# 主循环
# ============================================================
def run(screen, font, clock, ctx: WorldContext):
    import font_utils as _fu
    settings = get_settings()
    small_font = _fu.make_font(15)
    mgr = Manager.load()
    mgr.bind_settings(settings)
    ctx.manager_memory = mgr.memory
    ctx.manager_learned_urls = mgr.learned_urls
    kb = browser_study.KnowledgeBase()
    vision = VisionCortex(grid_size=12)
    vision_summary = "尚未生成,按 V 刷新。"
    chat_log: list[str] = list(mgr.conversation_log[-10:]) if mgr.conversation_log else \
        [f"{mgr.name}: 你好呀,我是 Life Lab 管家。我能观察世界、投放植物、告诉宠物话、学习网页~",
         "试试说:'在生态系统投放 5 株植物' 或 '告诉宠物 我回来了'"]
    input_box = ""
    url_box = ""
    vision_refresh_in = 0
    last_exec_report = None

    # ---- 右侧面板 ----
    sx0 = PANEL_X + SIDE_GAP
    sw0 = SIDE_PANEL_W - 2 * SIDE_GAP
    activity_log = ScrollingLog(sx0, 44, sw0, 190, title="活动日志", max_lines=200)
    sliders = [
        Slider(key="mgr.auto_sleep_s", label="自动休眠(秒)",
               min_v=5, max_v=600, step=5,
               init_v=settings.get_float("mgr.auto_sleep_s"),
               x=sx0, y=252, w=sw0, h=16, fmt="{label}: {v:.0f}",
               on_change=lambda k, v: settings.set(k, v)),
        Slider(key="mgr.vision_refresh_ticks", label="视觉刷新(tick)",
               min_v=10, max_v=600, step=10,
               init_v=settings.get_float("mgr.vision_refresh_ticks"),
               x=sx0, y=310, w=sw0, h=16, fmt="{label}: {v:.0f}",
               on_change=lambda k, v: settings.set(k, v)),
    ]

    # ---- 底部快捷按钮:2 列 ----
    btn_y = HEIGHT - 14 - 28
    btn_h = 28
    btn_gap = 10
    btn_w = (sw0 - btn_gap) // 2

    def _do_spawn10():
        nonlocal last_exec_report, vision_refresh_in
        ctx.pending_spawn_plants += 10
        if ctx.ecosystem_plants is not None:
            import mode_ecosystem as _em
            for _ in range(10):
                ctx.ecosystem_plants.append(_em.Plant(
                    random.uniform(20, 560 - 20), random.uniform(20, HEIGHT - 20)))
        note = "🔘[按钮] 挂起+即时投放 10 株植物"
        activity_log.push(note)
        last_exec_report = note

    def _do_vision_refresh():
        nonlocal vision_summary, vision_refresh_in
        ents = ctx.as_world_entities()
        try:
            frame = vision.render(ents, manager_pos=(560/2, HEIGHT/2))
            vision_summary = vision.summarize(frame, topk=5)
        except Exception as e:
            vision_summary = f"视觉刷新出错: {e}"
        vision_refresh_in = max(5, int(mgr.vision_refresh_ticks))
        activity_log.push(f"🔘[按钮] 视觉手动刷新:{vision_summary[:36]}")

    buttons = [
        TextButton(sx0 + 0 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "+10 植物", on_click=_do_spawn10),
        TextButton(sx0 + 1 * (btn_w + btn_gap), btn_y, btn_w, btn_h,
                   "刷新视觉", on_click=_do_vision_refresh),
    ]

    while True:
        consumed_mouse = False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                mgr.save()
                return "quit"
            # 滑杆消费鼠标
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
                    mgr.save()
                    return "menu"
                if event.key == pygame.K_RETURN:
                    if input_box.strip():
                        ut = input_box
                        reply, online, inst, inst_rep = manager_chat(
                            mgr, ctx, ut, kb, vision_summary, last_exec_report)
                        chat_log.append("你: " + ut)
                        chat_log.append(f"{mgr.name}: " + reply)
                        if inst_rep:
                            chat_log.append("(系统) " + inst_rep)
                        activity_log.push(f"指令｜{ut[:40]}")
                        if inst:
                            activity_log.push(f"执行｜{inst.intent.value}: {(inst_rep or '')[:36]}")
                        last_exec_report = inst_rep
                        input_box = ""
                    elif url_box.strip():
                        url = url_box.strip()
                        mgr.learned_urls.append(url)
                        mgr.learned_urls = list(dict.fromkeys(mgr.learned_urls))
                        if mgr.sleeping:
                            chat_log.append(
                                f"(系统)管家休眠中,暂不抓取URL。喊「管家」或「醒醒」唤醒后再试~ {url}")
                            last_exec_report = "休眠,URL抓取跳过"
                            activity_log.push(f"URL跳过(休眠)｜{url[:40]}")
                        else:
                            added, words, status_msg = browser_study.study_url(url)
                            chat_log.append(f"(系统)[URL学习] {url} → {status_msg}")
                            last_exec_report = f"URL 学习完成:{status_msg}"
                            mgr._reset_activity()
                            activity_log.push(f"URL学习｜{status_msg[:40]}")
                        url_box = ""
                elif event.key == pygame.K_BACKSPACE:
                    if input_box:
                        input_box = input_box[:-1]
                    elif url_box:
                        url_box = url_box[:-1]
                elif event.key == pygame.K_TAB:
                    tmp = input_box; input_box = url_box; url_box = tmp
                elif event.key == pygame.K_v:
                    ents = ctx.as_world_entities()
                    frame = vision.render(ents, manager_pos=(560/2, HEIGHT/2))
                    vision_summary = vision.summarize(frame, topk=5)
                    activity_log.push(f"视觉｜手动V刷新:{vision_summary[:40]}")
                else:
                    if event.unicode and event.unicode.isprintable():
                        if len(input_box) < 120:
                            input_box += event.unicode

        # 按 settings 频率刷新视觉
        vision_refresh_in -= 1
        if vision_refresh_in <= 0:
            ents = ctx.as_world_entities()
            try:
                frame = vision.render(ents, manager_pos=(560/2, HEIGHT/2))
                vision_summary = vision.summarize(frame, topk=5)
            except Exception as e:
                vision_summary = f"视觉刷新出错: {e}"
            vision_refresh_in = max(5, int(mgr.vision_refresh_ticks))

        # ---- 每帧 tick,接收休眠等系统消息追加到聊天 ----
        sys_msg = mgr.tick()
        if sys_msg:
            chat_log.append(sys_msg)
            activity_log.push(sys_msg)
            if len(chat_log) > 40:
                chat_log = chat_log[-40:]

        draw_ui_with_panel(screen, font, small_font, mgr, ctx, vision_summary,
                           chat_log, input_box, url_box,
                           activity_log, sliders)
        # 按钮行（必须最后画，避免被 UI 任何东西覆盖）
        for b in buttons:
            b.draw(screen, small_font)
        pygame.display.flip()
        advance_tick(ctx, every=500)
        clock.tick(max(1, settings.get_int("global.fps")))


def draw_ui_with_panel(screen, font, small_font, mgr, ctx, vision_summary,
                       chat_log, input_box, url_box,
                       activity_log, sliders):
    """主区 0..560 + 右侧 560..800 面板。"""
    import quantum_ops as _qo
    screen.fill(WHITE)
    pygame.draw.line(screen, GOLD_DK, (559, 0), (559, HEIGHT), 2)
    MAIN_W = 560
    # ===== 头部（主区内） =====
    head = pygame.Rect(0, 0, MAIN_W, 50)
    pygame.draw.rect(screen, (250, 245, 220), head)
    if mgr.sleeping:
        status_note = f"💤 SLEEPING (喊「管家」「小爱马」「醒醒」)"
        head_col = SLEEP_COL
    else:
        remain = max(0, int(mgr.auto_sleep_after - mgr._idle_seconds()))
        status_note = f"{remain}s 后自动休眠(>{int(mgr.auto_sleep_after)}s无指令)"
        head_col = DARK
    try:
        screen.blit(font.render(f"【{mgr.name}】 好感:{int(mgr.affection)} "
                                f"在线:{'Y' if mgr.online else 'N'} tick={ctx.tick_count} {status_note}",
                                True, head_col), (10, 12))
    except Exception:
        pass

    # ===== 世界卡 54..178 =====
    world_x, world_y, world_w, world_h = 8, 58, MAIN_W - 16, 124
    _draw_world_card(screen, font, small_font, world_x, world_y, world_w, world_h,
                     ctx, vision_summary, _qo)

    # ===== 对话聊天 =====
    chat_top = 192
    chat_h = 314
    pygame.draw.rect(screen, (252, 252, 250), (6, chat_top, MAIN_W - 12, chat_h),
                     border_radius=6)
    pygame.draw.rect(screen, LINE, (6, chat_top, MAIN_W - 12, chat_h), 1, border_radius=6)
    draw_label(screen, small_font, "对话 / 指令日志（回车发送 / Tab 切换 URL 框 / V 刷新视觉）",
               12, chat_top + 4, INK_SOFT)
    lines = chat_log[-11:]
    for i, ln in enumerate(lines):
        wrapped = _wrap_cn(str(ln), 54)  # 主区中文每行约 54 半角宽
        for j, sub in enumerate(wrapped):
            y = chat_top + 22 + (i * 2 + j) * 14
            if y + 14 > chat_top + chat_h - 6: break
            draw_label(screen, small_font, sub, 12, y, INK)

    # ===== 双输入框 =====
    input_y = chat_top + chat_h + 6
    box1 = pygame.Rect(6, input_y, MAIN_W - 12, 28)
    pygame.draw.rect(screen, (240, 242, 246), box1, border_radius=5)
    pygame.draw.rect(screen, LINE, box1, 1, border_radius=5)
    draw_label(screen, small_font, "[指令] > " + input_box + "_", 12, input_y + 7, INK)
    url_y = input_y + 32
    box2 = pygame.Rect(6, url_y, MAIN_W - 12, 28)
    pygame.draw.rect(screen, (240, 242, 246), box2, border_radius=5)
    pygame.draw.rect(screen, LINE, box2, 1, border_radius=5)
    draw_label(screen, small_font, "[学习URL] > " + url_box + "_  (回车抓取)",
               12, url_y + 7, INK)
    hint_y = url_y + 32
    draw_label(screen, small_font,
               "TAB 切换焦点 · ESC 返回菜单 · 右侧拖滑杆即时生效 · S=主菜单全局设置",
               8, hint_y, INK_SOFT)

    # ===== 右侧 560..800 =====
    inner = draw_side_panel_bg(screen, "🧭 管家 · 活动/设置", small_font)
    activity_log.x = inner.x; activity_log.y = inner.y
    activity_log.w = inner.w; activity_log.h = 196
    activity_log.draw(screen, font, small_font)
    base_y = inner.y + 196 + 12
    positions = [0, 58]
    for s, g in zip(sliders, positions):
        s.x = inner.x; s.w = inner.w; s.y = base_y + g
        s.draw(screen, small_font, small_font)
    card_y = base_y + 150
    card_h = max(60, (HEIGHT - 56) - card_y)
    urls_n = len(mgr.learned_urls)
    url_bar = min(100.0, 100.0 * urls_n / max(1, 20))
    on_v = 95 if mgr.online else 30
    ts = _qo.tunnel_stats()
    rate_pct = min(100.0, 100.0 * ts['tunnel_rate'])
    draw_status_card(
        screen, font, small_font, inner.x, card_y, inner.w, card_h,
        "运行状态", [
            StatusItem("学习URL", float(urls_n), color=(BLUE if urls_n else GRAY)),
            StatusItem("URL饱和度", url_bar, color=BLUE, fmt="{label}: {v:.0f}%"),
            StatusItem("好感度", float(mgr.affection), color=GREEN),
            StatusItem("在线", float(on_v), color=(GREEN if mgr.online else GRAY)),
            StatusItem("隧穿%", float(rate_pct), color=VIOLET),
        ]
    )


def _draw_world_card(screen, font, small_font, x, y, w, h, ctx, vision_summary, _qo):
    # 世界小卡片
    from ui_widgets import Card, StatusItem, draw_status_card
    card = Card(x, y, w, h, "🌏 世界快照 (爱马仕视觉皮层)")
    inner = card.draw(screen, font)
    # 左 3 小状态卡 / 右 vision_summary 文本
    left_w = 200
    a = ctx.agent_obj
    plants = len(ctx.ecosystem_plants) if ctx.ecosystem_plants else 0
    herbs = len(ctx.ecosystem_herbs) if ctx.ecosystem_herbs else 0
    preds = len(ctx.ecosystem_preds) if ctx.ecosystem_preds else 0
    cray = len(ctx.ecosystem_crayfish) if ctx.ecosystem_crayfish else 0
    bo = len(ctx.boids_list) if ctx.boids_list else 0
    e_energy = float(getattr(a, "energy", 0) or 0)
    e_age = int(getattr(a, "age", 0) or 0)
    draw_status_card(
        screen, font, small_font, inner.x, inner.y, left_w, inner.h, "", [
            StatusItem("Agent能", e_energy, color=BLUE, fmt="{label}:{v:.0f}"),
            StatusItem("AgentAge", float(min(100, e_age)), color=GREEN),
            StatusItem("植物", float(min(100, plants)), color=(90, 160, 90)),
            StatusItem("食草", float(min(100, herbs)), color=(160, 140, 70)),
            StatusItem("捕食", float(min(100, preds)), color=(200, 100, 90)),
            StatusItem("🦞", float(min(100, cray)), color=(180, 60, 80)),
            StatusItem("Boids", float(min(100, bo)), color=(90, 140, 220)),
        ]
    )
    # 右 vision_summary 换行
    right_x = inner.x + left_w + 10
    right_w = inner.w - left_w - 10
    draw_label(screen, small_font, "视觉摘要:", right_x, inner.y, INK)
    top = inner.y + 18
    lines_out = []
    for raw in vision_summary.splitlines() or [vision_summary]:
        lines_out.extend(_wrap_cn(raw, 42))
    for i, ln in enumerate(lines_out[:12]):
        draw_label(screen, small_font, ln, right_x, top + i * 14, INK)


VIOLET = (120, 100, 180)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Manager Pet v2 - Life Lab 统一管理面板")
    clock = pygame.time.Clock()
    font = font_utils.make_font(22)
    run(screen, font, clock, WorldContext())
    pygame.quit()


if __name__ == "__main__":
    main()
