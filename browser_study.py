"""
browser_study.py - 知识库 RAG + 浏览器学习
  KnowledgeBase: 本地 JSONL 存储,TF-IDF 关键词索引,Jaccard 检索
  study_text / study_file: 离线入口(无需 browser_use)
  study_url: 需要 Trae 环境内 browser_use 工具配合

不依赖 numpy/jieba:分词 fallback = 正则按中英文标点与空格切。
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "knowledge.jsonl")

# 基础停用词(中英文)
_STOP = set("的了是在和就也都而与或及但如果那么此因为所对于") | set(
    "a an the and or but if to of in on at for with by "
    "is are was were be been being have has had do does did "
    "this that these those i you he she it we they them "
    "my your our their as so not no can will would from "
    "me us him her its what when where why which who whom how "
    "there here then than just s t re ve ll d m o".split())

# 切片参数
_CHUNK = 200
_OVERLAP = 50


def _tokenize(text: str) -> list[str]:
    """简易中英文分词:按非字母数字汉字切分,再按 n-gram 拆中文单字。
    中文以单字作为 token,足以满足 Jaccard 检索。
    """
    toks = []
    parts = re.split(r"[\s\u3000\.\,\!\?\:\;\"\'\(\)\[\]\{\}，。！？：；“”‘’（）【】《》、/\\\-—…·\n\r\t]+",
                     text or "")
    for p in parts:
        if not p:
            continue
        # 英文/数字整块小写
        if re.fullmatch(r"[A-Za-z0-9_]+", p):
            if len(p) >= 2 and p.lower() not in _STOP:
                toks.append(p.lower())
        else:
            # 中文/混合:单字
            for ch in p:
                if not ch.strip():
                    continue
                if ch in _STOP:
                    continue
                toks.append(ch)
    return toks


@dataclass
class Chunk:
    url: str
    offset: int
    text: str
    tokens: set[str] = field(default_factory=set)
    top_terms: list[str] = field(default_factory=list)


class KnowledgeBase:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self.chunks: list[Chunk] = []
        self._load()

    # ---------- I/O ----------
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    c = Chunk(
                        url=d.get("url", ""),
                        offset=int(d.get("offset", 0)),
                        text=d.get("text", ""),
                        tokens=set(d.get("tokens") or []),
                        top_terms=list(d.get("top_terms") or []),
                    )
                    self.chunks.append(c)
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                for c in self.chunks:
                    f.write(json.dumps({
                        "url": c.url, "offset": c.offset, "text": c.text,
                        "tokens": sorted(c.tokens),
                        "top_terms": c.top_terms,
                    }, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------- 写入 ----------
    def add(self, text: str, url: str = "manual") -> int:
        """切片并追加,返回新增切片数。"""
        if not text:
            return 0
        n_before = len(self.chunks)
        i = 0
        while i < len(text):
            end = min(i + _CHUNK, len(text))
            piece = text[i:end]
            toks = _tokenize(piece)
            top = self._select_top_terms(toks, 10)
            self.chunks.append(Chunk(url=url, offset=i, text=piece,
                                     tokens=set(toks), top_terms=top))
            if end == len(text):
                break
            i = end - _OVERLAP if end - _OVERLAP > i else i + 1
        self._save()
        return len(self.chunks) - n_before

    def count(self) -> int:
        return len(self.chunks)

    # ---------- 检索 ----------
    def retrieve(self, query: str, topk: int = 3) -> list[str]:
        if not self.chunks or not query:
            return []
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return [c.text for c in self.chunks[:topk]]
        scored = []
        for c in self.chunks:
            if not c.tokens:
                scored.append((0.0, c))
                continue
            inter = len(q_tokens & c.tokens)
            union = len(q_tokens | c.tokens) or 1
            jaccard = inter / union
            scored.append((jaccard, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c.text for _, c in scored[:topk] if _ > 0] or \
            [scored[0][1].text]

    # ---------- 工具 ----------
    @staticmethod
    def _select_top_terms(tokens: list[str], k: int) -> list[str]:
        if not tokens:
            return []
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        return [t for t, _ in sorted(freq.items(),
                                     key=lambda kv: kv[1], reverse=True)[:k]]


# ============================================================
# 浏览器学习主入口(需在 Trae 环境中调用 browser_use 工具)
# ============================================================
def study_text(url: str, text: str,
               kb_path: str | None = None) -> tuple[int, int]:
    """离线入口:直接给文本(用户可粘贴)。返回 (新增切片数,总字数)"""
    kb = KnowledgeBase(kb_path or DEFAULT_PATH)
    words = len(_tokenize(text))
    added = kb.add(text, url=url)
    return added, words


def study_file(file_path: str, kb_path: str | None = None) -> tuple[int, int]:
    """读取本地 txt/md 加入知识库"""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return study_text(url="file:" + file_path, text=text, kb_path=kb_path)


# ---------- HTML -> 纯文本简易清洗 ----------
_HTML_STRIP_RE = None  # lazy init


def _strip_html(html: str) -> str:
    """尽量把 HTML 变成可读纯文本。
    - 先删 <script>/<style>/<noscript> 整块
    - 再 <.*?> 去标签
    - 再还原常见实体
    """
    global _HTML_STRIP_RE
    import re as _re
    if _HTML_STRIP_RE is None:
        _HTML_STRIP_RE = {
            "head": _re.compile(r"<head[\s>].*?</head>", _re.S | _re.I),
            "script": _re.compile(r"<script[\s>].*?</script>", _re.S | _re.I),
            "style": _re.compile(r"<style[\s>].*?</style>", _re.S | _re.I),
            "noscript": _re.compile(r"<noscript[\s>].*?</noscript>", _re.S | _re.I),
            "tag": _re.compile(r"<[^>]+>"),
            "br": _re.compile(r"<br\s*/?>", _re.I),
            "p": _re.compile(r"</p\s*>", _re.I),
            "multispace": _re.compile(r"[ \t\r\f\v]+"),
            "multinewline": _re.compile(r"\n{3,}"),
        }
    s = html or ""
    for k in ("head", "script", "style", "noscript"):
        s = _HTML_STRIP_RE[k].sub("", s)
    s = _HTML_STRIP_RE["br"].sub("\n", s)
    s = _HTML_STRIP_RE["p"].sub("\n\n", s)
    s = _HTML_STRIP_RE["tag"].sub("", s)
    # 常见 HTML entity
    s = (s
         .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
         .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
         .replace("&copy;", "(C)").replace("&reg;", "(R)"))
    # 剩余 &#NNN;
    def _ent(m):
        try:
            return chr(int(m.group(1)))
        except Exception:
            return m.group(0)
    s = _re.sub(r"&#(\d+);", _ent, s)
    s = _HTML_STRIP_RE["multispace"].sub(" ", s)
    lines = [ln.strip() for ln in s.split("\n")]
    s = "\n".join(ln for ln in lines if ln)
    s = _HTML_STRIP_RE["multinewline"].sub("\n\n", s)
    return s.strip()


def study_url(url: str, kb_path: str | None = None,
              timeout: float = 10.0,
              max_bytes: int = 2 * 1024 * 1024
              ) -> tuple[int, int, str]:
    """真正的 URL 学习入口。
    流程:
      1. 尝试用 requests.get 拉 HTML
      2. _strip_html() 提取正文
      3. study_text() 写入 KB
    返回 (切片数, 字数, 状态消息)
    """
    try:
        import requests  # noqa: F401
    except Exception as e:
        # requests 缺失:占位
        added, words = study_text(
            url=url, text=f"[URL记录-无requests] {url}\n(requests 缺失: {e})",
            kb_path=kb_path,
        )
        return added, words, f"失败:requests 未安装({e}),已占位记录"

    try:
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0 Safari/537.36 LifeLab/2.0"),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        })
        resp.raise_for_status()
        # 按编码修正
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        raw = resp.content[:max_bytes]
        try:
            html = raw.decode(resp.encoding or "utf-8", errors="ignore")
        except Exception:
            html = raw.decode("utf-8", errors="ignore")
        text = _strip_html(html)
        # 正文过短(比如纯 JSON、图片、下载页):占位记录
        if len(text.strip()) < 40:
            added, words = study_text(
                url=url, text=f"[URL记录-正文过短] {url}\n{text}", kb_path=kb_path,
            )
            return added, words, f"抓取成功但正文过短,已占位({len(text.strip())}字)"
        added, words = study_text(url=url, text=text, kb_path=kb_path)
        return added, words, f"抓取成功→新增{added}片约{words}词(status={resp.status_code})"
    except Exception as e:
        # requests 层失败(超时/网络/DNS 等):至少登记 URL 占位(不要丢用户输入)
        added, words = study_text(
            url=url, text=f"[URL记录-抓取失败] {url}\n错误:{type(e).__name__}: {e}",
            kb_path=kb_path,
        )
        return added, words, f"抓取失败({type(e).__name__}),已占位登记URL"


# 在 Trae 环境运行时的入口:
# 由 Manager 面板触发,其调用方式见 mode_manager.py 的 intent 调度器:
#   1. 用 browser_navigate 打开 URL
#   2. 用 browser_evaluate 提取 document.body.innerText
#   3. 调用 study_text(url, extracted_text)
# 为了 Manager 能导入,这里提供一个包装:

def process_scraped_content(url: str, scraped_text: str) -> str:
    """将 browser scrape 结果写入 KB。返回摘要字符串。"""
    added, words = study_text(url=url, text=scraped_text)
    return f"[已学习] {url} -> 新增 {added} 片,约 {words} 词"
