"""
本地 Mock 测试:Pet/Manager 休眠与唤醒逻辑
============================================
用法(Windows PowerShell / CMD):
  python _test_sleep_mock.py                                    # 跑内置 8 个场景
  python _test_sleep_mock.py --json .\\mock_sleep_scenarios.json   # 指定 mock JSON
  python _test_sleep_mock.py --scenario Pet-C-wake-word-wake    # 只跑单个场景
  python _test_sleep_mock.py --target pet                       # 只跑 pet / manager
  python _test_sleep_mock.py --no-mock-time                     # 不 monkey patch time.time(),真实等待

原理:
  1. 默认 monkey patch time.time() / time.monotonic(),让「idle N 秒」事件 ≈ 瞬间完成
  2. 按 JSON 事件序列驱动 Pet / Manager 实例的 .tick() / .respond() / manager_chat()
  3. 断言项失败时打印实际值,并最终汇总 PASS/FAIL
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# ---------- Mock time ----------
class MockClock:
    """非线程安全,但单线程场景完全够用。"""

    def __init__(self, start: float = 1_700_000_000.0):
        self.t = start
        self._saved_time = {}
        self._installed = False

    def install(self):
        if self._installed:
            return
        # 如果某些模块已经 `from time import time` 了,它们用的是原函数,不会被 patch。
        # 但我们的 mode_pet/mode_manager 都是 `import time; time.time()` 用法,会命中。
        self._saved_time = {
            "time.time": time.time,
            "time.monotonic": time.monotonic,
            "time.sleep": time.sleep,
        }
        time.time = self._time  # type: ignore[assignment]
        time.monotonic = self._monotonic  # type: ignore[assignment]
        time.sleep = self._sleep  # type: ignore[assignment]  # 0-cost
        # 让 importlib.reload 重新执行顶层时不会污染;我们先 import 完所有目标再 patch,
        # 但为了保险:对已经 import 的 mode_pet/mode_manager,强制 time 引用是当前模块 time
        import mode_pet, mode_manager  # noqa: F401
        self._installed = True

    def uninstall(self):
        if not self._installed:
            return
        time.time = self._saved_time["time.time"]
        time.monotonic = self._saved_time["time.monotonic"]
        time.sleep = self._saved_time["time.sleep"]
        self._installed = False

    def advance(self, seconds: float) -> None:
        self.t += max(0.0, float(seconds))

    def _time(self) -> float:
        return self.t

    def _monotonic(self) -> float:
        return self.t

    def _sleep(self, seconds: float) -> None:
        self.advance(seconds)


# ---------- 结果记录 ----------
@dataclass
class AssertResult:
    label: str
    ok: bool
    expected: Any
    actual: Any
    detail: str = ""


@dataclass
class ScenarioResult:
    sid: str
    title: str
    target: str
    ok: bool
    asserts: list[AssertResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------- 场景执行 ----------
def _contains_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def _load_scenarios(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_instances(spec: dict):
    import mode_pet, mode_manager, browser_study, core_types
    pet = mode_pet.Pet()
    pet.auto_sleep_after = float(spec.get("pet_auto_sleep_s", 1))
    # Pet 初始化里 self._last_activity = time.time(),必须在 patch 后再重置
    pet._reset_activity()

    mgr = mode_manager.Manager()
    mgr.auto_sleep_after = float(spec.get("mgr_auto_sleep_s", 1))
    mgr._reset_activity()

    kb_path = spec.get("kb", {}).get("path")
    if kb_path:
        # 指定路径时清掉旧文件,保证隔离
        try:
            if os.path.exists(kb_path):
                os.remove(kb_path)
        except OSError:
            pass
    kb = browser_study.KnowledgeBase(kb_path) if kb_path else browser_study.KnowledgeBase()
    ctx = core_types.WorldContext()
    return pet, mgr, kb, ctx


def _setup_sleep(target: str, pet, mgr) -> None:
    """某些场景需要从休眠开始。用直接设置字段,避免依赖 tick/idle。"""
    if target == "pet":
        pet.sleeping = True
    elif target == "manager":
        mgr.sleeping = True


def _assert_item(ev: dict, last_reply: str, last_tick_msg: str,
                 pet, mgr, ctx, kb,
                 hunger_before: float | None) -> AssertResult:
    check = ev["check"]
    expect = ev["expect"]
    label = ev.get("label") or check
    ok = False
    actual: Any = None
    detail = ""

    try:
        if check == "sleeping":
            obj = pet if (pet is not None) else None
            # 如果 target manager 的断言,用 mgr
            if ev.get("_target") == "manager" or (obj is None):
                obj = mgr
            # 选择:根据哪一个实例 setup 过 sleeping 判断
            # 简单规则:若 Mgr-A/B/C/D target=manager 则用 mgr
            actual = bool(obj.sleeping)
            ok = (actual == bool(expect))
            detail = f"{type(obj).__name__}.sleeping = {actual}"
        elif check == "hunger_delta_le":
            assert isinstance(expect, (int, float))
            # 先推进 _then_tick 次
            ticks = int(ev.get("_then_tick", 0) or 0)
            for _ in range(ticks):
                pet.tick()
            delta = float(pet.hunger) - float(hunger_before or 0.0)
            actual = delta
            ok = delta <= float(expect) + 1e-6
            detail = f"hunger_delta={delta:.4f} ≤ {float(expect):.4f}?"
        elif check == "reply_contains":
            needles = [expect] if isinstance(expect, str) else list(expect)
            actual = last_reply
            ok = _contains_any(last_reply, needles)
            detail = f"reply[:80]={last_reply[:80]!r}  contains? {needles}"
        elif check == "reply_not_contains":
            needles = [expect] if isinstance(expect, str) else list(expect)
            actual = last_reply
            ok = not _contains_any(last_reply, needles)
            detail = f"reply[:80]={last_reply[:80]!r}  not contains? {needles}"
        elif check == "reply_len_lt":
            n = int(expect)
            actual = len(last_reply)
            ok = actual < n
            detail = f"len(reply)={actual} < {n}?"
        elif check == "instant_tick_msg_contains":
            needle = expect if isinstance(expect, str) else str(expect)
            actual = last_tick_msg
            ok = needle in last_tick_msg
            detail = f"tick_msg={last_tick_msg!r}  contains? {needle!r}"
        elif check == "no_immediate_tick_msg":
            actual = last_tick_msg
            ok = not last_tick_msg
            detail = f"tick_msg should be ''; got {last_tick_msg!r}"
        elif check == "manager_chat_inst_none":
            # 通过 ev 注入的额外信息:在 run_scenario 里会把 manager_chat 元组写入 last_inst / last_inst_rep
            actual = {"inst": str(getattr(run_state, "last_inst", None)),
                      "rep": str(getattr(run_state, "last_inst_rep", None))}
            ok = (run_state.last_inst is None) and (run_state.last_inst_rep is None)
            detail = f"manager_chat inst={actual['inst']}, rep={actual['rep']}"
        else:
            return AssertResult(label, False, expect, None,
                                detail=f"未知 check={check!r}")
    except Exception as e:
        return AssertResult(label, False, expect, None,
                            detail=f"断言异常: {type(e).__name__}: {e}")
    return AssertResult(label, ok, expect, actual, detail)


class RunState:
    """容器:给断言共享最近的 manager_chat 返回元组。"""
    last_inst = None
    last_inst_rep = None


run_state = RunState()


def run_scenario(sc: dict, spec: dict, clock: MockClock) -> ScenarioResult:
    import mode_pet, mode_manager
    target = sc.get("target", "pet")
    sid = sc["id"]
    title = sc.get("title", sid)
    result = ScenarioResult(sid=sid, title=title, target=target, ok=True)

    pet, mgr, kb, ctx = _build_instances(spec)
    # reset 一次 activity(确保从 0 开始)
    pet._reset_activity(); mgr._reset_activity()

    # 预睡眠(setup_sleep)
    if sc.get("setup_sleep"):
        _setup_sleep(target, pet, mgr)
        result.notes.append(f"[setup] sleeping=True via direct field (target={target})")

    last_reply = ""
    last_tick_msg = ""
    hunger_before: float | None = None

    for ev in sc.get("events", []):
        t = ev["type"]
        try:
            if t == "idle":
                secs = float(ev["seconds"])
                clock.advance(secs)
            elif t == "tick":
                if target == "pet":
                    last_tick_msg = pet.tick()
                else:
                    last_tick_msg = mgr.tick()
            elif t == "chat":
                text = str(ev["text"])
                if target == "pet":
                    # hunger_before 预缓存(给 hunger_delta_le 断言用)
                    hunger_before = float(pet.hunger)
                    last_reply = pet.respond(text, kb)
                    last_tick_msg = ""
                else:
                    last_reply, online, inst, rep = mode_manager.manager_chat(
                        mgr, ctx, text, kb, '', None)
                    run_state.last_inst = inst
                    run_state.last_inst_rep = rep
                    last_tick_msg = ""
            elif t == "url_study":
                url = str(ev["url"])
                if target == "pet":
                    result.notes.append("[warn] url_study 对 Pet 无意义,跳过。")
                    continue
                # 直接复用 mode_manager.run 中同样的副作用逻辑:
                #   休眠态 → 不抓,只写提示;正常态 → study_url 真抓,失败 fallback 占位
                mgr.learned_urls.append(url)
                mgr.learned_urls = list(dict.fromkeys(mgr.learned_urls))
                if mgr.sleeping:
                    last_reply = (f"(系统)管家休眠中,暂不抓取URL。"
                                  f"喊「管家」或「醒醒」唤醒后再试~ {url}")
                else:
                    try:
                        added, words, status_msg = mode_manager.browser_study.study_url(url)
                        last_reply = f"(系统)[URL学习] {url} → {status_msg}"
                        mgr._reset_activity()
                    except Exception as e:
                        last_reply = f"(系统)[URL学习] 异常: {type(e).__name__}: {e}"
            elif t == "assert":
                # 注入目标(方便 sleeping 断言选对象)
                ev2 = dict(ev)
                ev2["_target"] = target
                ar = _assert_item(ev2, last_reply, last_tick_msg,
                                  pet, mgr, ctx, kb, hunger_before)
                result.asserts.append(ar)
                if not ar.ok:
                    result.ok = False
            else:
                result.notes.append(f"[warn] 未知事件类型 {t!r},跳过。")
        except Exception as e:
            ar = AssertResult(
                label=f"EVENT_ERR_{t}", ok=False, expected=None, actual=None,
                detail=f"事件 {t} 抛异常: {type(e).__name__}: {e}"
            )
            result.asserts.append(ar)
            result.ok = False
    return result


# ---------- 打印 ----------
def _print_results(results: list[ScenarioResult]) -> None:
    W = 100
    print("=" * W)
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print(f"  Mock 休眠/唤醒测试  汇总: {passed}/{total} PASS")
    print("=" * W)
    for r in results:
        mark = "✅ PASS" if r.ok else "❌ FAIL"
        print(f"\n[{r.target:>7}] {r.sid:40s}  {mark}   {r.title}")
        for n in r.notes:
            print(f"    note: {n}")
        for a in r.asserts:
            s = "  +" if a.ok else "  X"
            print(f"{s} {a.label}")
            if not a.ok:
                print(f"       expected: {a.expected!r}")
                print(f"       actual  : {a.actual!r}")
                if a.detail:
                    print(f"       detail  : {a.detail}")
    print("\n" + "=" * W)


def main() -> int:
    ap = argparse.ArgumentParser(description="Mock 测试 Pet/Manager 休眠与唤醒")
    ap.add_argument("--json", default=os.path.join(ROOT, "mock_sleep_scenarios.json"),
                    help="mock 数据 JSON 路径 (默认:./mock_sleep_scenarios.json)")
    ap.add_argument("--scenario", default=None,
                    help="只跑指定 id 的场景(例如 Pet-A-idle-sleep)")
    ap.add_argument("--target", default=None, choices=["pet", "manager"],
                    help="只跑 pet 或 manager 的场景")
    ap.add_argument("--no-mock-time", action="store_true",
                    help="不 patch time.time(),用真实时钟(会真的等 1 秒以上)")
    args = ap.parse_args()

    spec = _load_scenarios(args.json)
    scenarios = spec.get("scenarios", [])
    if args.scenario:
        scenarios = [s for s in scenarios if s.get("id") == args.scenario]
    if args.target:
        scenarios = [s for s in scenarios if s.get("target") == args.target]
    if not scenarios:
        print("没有匹配的场景。")
        return 2

    clock = MockClock()
    if not args.no_mock_time:
        clock.install()
        print("[i] time.time() / time.sleep() 已 monkey patch,空闲事件为即时推进。")
    try:
        results: list[ScenarioResult] = []
        for sc in scenarios:
            # 每个场景独立 clock
            clock.t = 1_700_000_000.0
            results.append(run_scenario(sc, spec, clock))
    finally:
        clock.uninstall()

    _print_results(results)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
