"""
llm_client.py - OpenAI 兼容 LLM 客户端 + 离线降级
零配置可用:无 llm_config.json 或网络失败时,调用 fallback 函数。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "llm_config.json")


@dataclass
class LLMConfig:
    base_url: str            # e.g. "https://api.openai.com/v1"
    api_key: str
    model: str               # e.g. "gpt-4o-mini" or "qwen2.5-7b"

    @classmethod
    def from_dict(cls, d: dict) -> "LLMConfig":
        base = d.get("base_url", "").rstrip("/")
        return cls(
            base_url=base,
            api_key=d.get("api_key", "") or "",
            model=d.get("model", "gpt-4o-mini"),
        )


def load_config(path: str | None = None) -> LLMConfig | None:
    p = path or CONFIG_PATH
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    # 缺关键字段直接 None(避免请求必然失败)
    if not d.get("base_url") or not d.get("model"):
        return None
    cfg = LLMConfig.from_dict(d)
    # api_key 允许为空(本地 Ollama 通常无需 key)
    return cfg


class LLMClient:
    """OpenAI 兼容 /chat/completions 客户端。"""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def chat(self, system_prompt: str, user_message: str,
             context: list[str] | None = None,
             temperature: float = 0.7, timeout: int = 10) -> str:
        """发起请求,失败返回 "__OFFLINE__"。(不抛异常)"""
        try:
            import requests  # 延迟 import,离线环境不报错
        except Exception:
            return "__OFFLINE__"

        msgs = [{"role": "system", "content": system_prompt}]
        if context:
            for c in context:
                msgs.append({"role": "system",
                             "content": f"[相关知识] {c}"})
        msgs.append({"role": "user", "content": user_message})

        payload = {
            "model": self.cfg.model,
            "messages": msgs,
            "temperature": temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
        except Exception:
            return "__OFFLINE__"


def llm_chat_or_fallback(
    system_prompt: str,
    user_message: str,
    context: list[str] | None,
    fallback_fn: Callable[[str, list[str] | None], str],
    temperature: float = 0.7,
    cfg: LLMConfig | None = None,
) -> tuple[str, bool]:
    """优先走 LLM,否则 fallback。
    返回 (回复, 是否使用了在线 LLM)。
    """
    if cfg is None:
        cfg = load_config()
    if cfg is None:
        return fallback_fn(user_message, context), False
    client = LLMClient(cfg)
    reply = client.chat(system_prompt, user_message, context=context,
                        temperature=temperature)
    if reply == "__OFFLINE__" or reply == "":
        return fallback_fn(user_message, context), False
    return reply, True


# ---------- 示例配置模板 ----------
EXAMPLE_CONFIG = """{
  "_comment": "复制本文件为 llm_config.json 并填入实际值。base_url 需以 /v1 结尾或类似格式。",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-XXXXXXXXXXXXXXXX",
  "model": "gpt-4o-mini"
}
"""
