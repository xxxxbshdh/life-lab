"""GUI smoke test (headless-friendly).

Run life_lab and every mode's main loop for a few ticks each, simulate
ESC to back to menu, quit cleanly. Use SDL dummy video driver so no window
needed on headless CI.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

import font_utils  # noqa: E402
import life_agent  # noqa: E402
import life_lab  # noqa: E402
import mode_pet  # noqa: E402
import mode_manager  # noqa: E402
import mode_ecosystem  # noqa: E402
import mode_boids  # noqa: E402
from core_types import WorldContext  # noqa: E402


class DummyClock:
    def tick(self, fps):
        return 16

    def get_fps(self):
        return 60.0


def _auto_quit(stop_after_s: float = 1.2, esc_to_menu_at_s: float = 0.6,
               inject_keys=(), click_at_s: list[float] | None = None,
               click_pos=(574, 562)):
    """Yield events: keys + optional left-clicks on the bottom-right button row
    (默认位置 PANEL_X+SIDE_GAP+4=574, y=600-14-28+4=562) + ESC on time.
    """
    start = time.time()
    posted_esc = False
    posted_injects = [False] * len(inject_keys)
    click_list = sorted(click_at_s or [])
    posted_clicks = [False] * len(click_list)
    while True:
        now = time.time() - start
        if now > stop_after_s:
            yield pygame.event.Event(pygame.QUIT)
            return
        for i, (at_s, key) in enumerate(inject_keys):
            if not posted_injects[i] and now >= at_s:
                yield pygame.event.Event(pygame.KEYDOWN, key=key, unicode="")
                yield pygame.event.Event(pygame.KEYUP, key=key)
                posted_injects[i] = True
        for i, at_s in enumerate(click_list):
            if not posted_clicks[i] and now >= at_s:
                yield pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                         pos=click_pos, button=1)
                yield pygame.event.Event(pygame.MOUSEBUTTONUP,
                                         pos=click_pos, button=1)
                posted_clicks[i] = True
        if not posted_esc and now >= esc_to_menu_at_s:
            yield pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="")
            yield pygame.event.Event(pygame.KEYUP, key=pygame.K_ESCAPE)
            posted_esc = True
        yield pygame.event.Event(pygame.NOEVENT)


def patch_event_queue(gen):
    """Monkey-patch pygame.event.get to return synthetic events in order."""
    _orig = pygame.event.get
    pending: list = []

    def get(*args, **kwargs):
        # Try: if any pending, return up to 4; else draw from gen until we have
        # something
        out = []
        try:
            while len(out) < 6:
                ev = next(gen)
                if ev.type == pygame.NOEVENT:
                    if out:
                        break
                    continue
                out.append(ev)
        except StopIteration:
            pass
        return out

    pygame.event.get = get
    return lambda: setattr(pygame.event, "get", _orig)


def run_once(label, fn, *, click_at_s=(0.3,), click_pos=(574, 562), **opts):
    print(f"[smoke] {label}  start")
    pygame.quit()
    pygame.init()
    pygame.display.set_mode((800, 600))
    font = font_utils.make_font(18)
    clock = DummyClock()
    gen = _auto_quit(click_at_s=list(click_at_s), click_pos=click_pos, **opts)
    restore = patch_event_queue(gen)
    try:
        result = fn(pygame.display.get_surface(), font, clock, WorldContext())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[smoke] {label}  ERROR: {e}")
        restore()
        return False
    finally:
        restore()
    print(f"[smoke] {label}  done -> {result!r}")
    return True


def main():
    ok = True
    # Mode 1 Agent (3 个按钮列,点击中间列 E 进化按钮: x=654, y=562)
    ok &= run_once("life_agent.run", life_agent.run,
                   click_at_s=(0.25, 0.35), click_pos=[(654, 562), (730, 562)][0])
    # Mode 2 Ecosystem
    ok &= run_once("mode_ecosystem.run", mode_ecosystem.run, click_pos=(574, 562))
    # Mode 3 Boids
    ok &= run_once("mode_boids.run", mode_boids.run, click_pos=(694, 562))
    # Mode 4 Pet
    ok &= run_once("mode_pet.run", mode_pet.run, click_pos=(574, 562))
    # Mode 5 Manager
    ok &= run_once("mode_manager.run", mode_manager.run, click_pos=(694, 562))

    # Life lab main menu: press 's' for settings at 0.3s, ESC to close at 0.8s, quit at 1.5s
    print("[smoke] life_lab.main (with S settings page test)")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.quit()
    pygame.init()
    pygame.display.set_mode((800, 600))
    start = time.time()
    stop_after = 1.8
    opened_settings_at = 0.25
    close_settings_at = 1.0
    gen2 = _auto_quit(stop_after_s=stop_after, esc_to_menu_at_s=99, inject_keys=[
        (opened_settings_at, pygame.K_s),
    ])
    # Need to also push a final ESC to leave menu (after close settings)
    # Append a closer ESC after close_settings_at by extending synthetic stream
    def merged():
        t0 = time.time()
        added_close = False
        added_quit_esc = False
        for ev in gen2:
            now = time.time() - t0
            if not added_close and now >= close_settings_at:
                added_close = True
                yield pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="")
                yield pygame.event.Event(pygame.KEYUP, key=pygame.K_s)
            if not added_quit_esc and now >= close_settings_at + 0.3:
                added_quit_esc = True
                yield pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="")
                yield pygame.event.Event(pygame.KEYUP, key=pygame.K_ESCAPE)
            yield ev
    restore2 = patch_event_queue(merged())
    try:
        life_lab.main()
    except SystemExit:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[smoke] life_lab.main ERROR: {e}")
        ok = False
    finally:
        restore2()
    print("[smoke] life_lab.main done")

    print(f"[smoke] ALL_OK={ok}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
