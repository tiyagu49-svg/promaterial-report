"""Live rare-earth news discovery with strict current-month filtering.

Google News RSS is used only as a discovery index. Each card preserves the
published timestamp, publisher name and clickable article link. No old catalog
or generated replacement article is returned when discovery fails.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field


SHANGHAI = ZoneInfo("Asia/Shanghai")
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

RARE_TERMS = (
    "稀土", "镨钕", "钕铁硼", "镝", "铽", "钇", "钐", "镓", "锗", "锑", "钨", "钼", "铟",
    "rare earth", "neodymium", "praseodymium", "dysprosium", "terbium", "yttrium",
    "gallium", "germanium", "antimony", "tungsten", "molybdenum", "indium",
)
INDUSTRY_TERMS = (
    "价格", "供应", "出口", "管制", "许可", "配额", "产能", "投产", "矿", "磁材", "永磁", "项目",
    "收购", "投资", "库存", "短缺", "政策", "关税", "制裁", "冶炼", "分离", "回收", "订单",
    "price", "supply", "export", "control", "licen", "quota", "capacity", "production", "mine",
    "mining", "magnet", "project", "acquisition", "investment", "shortage", "policy", "tariff",
    "sanction", "refin", "separation", "recycl", "demand", "stockpile", "market",
)
INSTITUTION_TERMS = (
    "iea", "usgs", "eurostat", "s&p global", "fastmarkets", "argus", "benchmark mineral",
    "wood mackenzie", "adamas intelligence", "cru", "mysteel", "上海有色", "安泰科",
    "研究", "分析", "报告", "outlook", "forecast", "analysis", "report", "analyst",
)
BLOCKED_SOURCES = (
    "sohu", "搜狐", "moomoo", "富途", "klse screener", "维度网", "中华军事", "blockchain.news",
    "雪球", "nai500", "腾讯新闻",
)
NOISE_TERMS = (
    "涨停", "个股", "概念热股", "etf", "股票今日为何", "一键布局", "净利增", "目标价",
    "赚翻", "不给钱", "要黄", "无米下锅", "成定局",
)


class IntelligenceCard(BaseModel):
    kind: Literal["消息面", "机构观点"]
    category: Literal["政策", "出口", "供应", "市场", "全球布局", "风险研判", "资源数据"]
    title: str
    takeaway: str
    affected: list[str]
    source: str
    source_url: str
    published_at: datetime
    available: bool = True

    @property
    def published_label(self) -> str:
        return self.published_at.astimezone(SHANGHAI).strftime("%m-%d %H:%M")


class IntelligenceFeed(BaseModel):
    items: list[IntelligenceCard] = Field(default_factory=list)
    unavailable_sources: list[str] = Field(default_factory=list)
    discovery_note: str
    fetched_at: datetime


def _queries(now: datetime) -> list[str]:
    month_start = now.replace(day=1).date().isoformat()
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1).date().isoformat()
    else:
        next_month = now.replace(month=now.month + 1, day=1).date().isoformat()
    window = f"after:{month_start} before:{next_month}"
    return [
        f'(稀土 OR 镨钕 OR 钕铁硼 OR 镝 OR 铽 OR 镓 OR 锗 OR 锑 OR 钨 OR 钼 OR 铟) '
        f'(供应 OR 出口 OR 价格 OR 产能 OR 项目 OR 管制 OR 磁材 OR 研报) {window}',
        f'("rare earth" OR neodymium OR dysprosium OR terbium OR gallium OR germanium OR antimony OR tungsten) '
        f'(supply OR export OR price OR capacity OR project OR control OR magnet OR outlook) {window}',
    ]


def _affected(title: str) -> list[str]:
    mappings = [
        (("稀土", "rare earth"), "稀土"), (("镨钕", "neodymium", "praseodymium"), "镨钕"),
        (("钕铁硼", "magnet"), "永磁材料"), (("镝", "dysprosium"), "镝"),
        (("铽", "terbium"), "铽"), (("镓", "gallium"), "镓"), (("锗", "germanium"), "锗"),
        (("锑", "antimony"), "锑"), (("钨", "tungsten"), "钨"), (("钼", "molybdenum"), "钼"),
        (("铟", "indium"), "铟"), (("钇", "yttrium"), "钇"),
    ]
    lower = title.casefold()
    result = [label for terms, label in mappings if any(term in lower for term in terms)]
    return result[:5] or ["战略小金属"]


def _category(title: str) -> str:
    lower = title.casefold()
    if any(word in lower for word in ("出口", "管制", "许可", "关税", "export", "control", "licen", "tariff")):
        return "出口"
    if any(word in lower for word in ("政策", "法规", "法案", "政府", "policy", "regulation", "government")):
        return "政策"
    if any(word in lower for word in ("供应", "短缺", "产能", "投产", "矿", "supply", "shortage", "capacity", "mine", "production")):
        return "供应"
    if any(word in lower for word in ("报告", "分析", "预测", "outlook", "forecast", "analysis", "report")):
        return "风险研判"
    if any(word in lower for word in ("价格", "市场", "股票", "price", "market", "stock")):
        return "市场"
    return "全球布局"


def _clean_title(title: str, source: str) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip()
    for separator in (" - ", " — ", " | "):
        suffix = f"{separator}{source}"
        if source and cleaned.casefold().endswith(suffix.casefold()):
            return cleaned[:-len(suffix)].strip()
    return cleaned


def _relevant(title: str) -> bool:
    lower = title.casefold()
    return (
        any(term in lower for term in RARE_TERMS)
        and any(term in lower for term in INDUSTRY_TERMS)
        and not any(term in lower for term in NOISE_TERMS)
    )


def _near_duplicate(title: str, existing_titles: list[str]) -> bool:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", title.casefold())
    return any(
        SequenceMatcher(None, normalized, re.sub(r"[^\w\u4e00-\u9fff]+", "", other.casefold())).ratio() >= 0.72
        for other in existing_titles
    )


def _parse_rss(payload: bytes, now: datetime) -> list[IntelligenceCard]:
    root = ET.fromstring(payload)
    items: list[IntelligenceCard] = []
    for node in root.findall(".//item"):
        raw_title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        published_raw = (node.findtext("pubDate") or "").strip()
        source_node = node.find("source")
        source = (source_node.text or "").strip() if source_node is not None else "Google News 收录来源"
        if not raw_title or not link or not published_raw:
            continue
        try:
            published = parsedate_to_datetime(published_raw).astimezone(SHANGHAI)
        except (TypeError, ValueError):
            continue
        if published.year != now.year or published.month != now.month:
            continue
        title = _clean_title(raw_title, source)
        if not _relevant(title) or any(blocked in source.casefold() for blocked in BLOCKED_SOURCES):
            continue
        lower = f"{source} {title}".casefold()
        kind: Literal["消息面", "机构观点"] = (
            "机构观点" if any(term in lower for term in INSTITUTION_TERMS) else "消息面"
        )
        affected = _affected(title)
        items.append(IntelligenceCard(
            kind=kind,
            category=_category(title),
            title=title,
            takeaway=f"标题信号涉及{'、'.join(affected)}；点击标题阅读原文，当前未启用正文级AI摘要。",
            affected=affected,
            source=source,
            source_url=link,
            published_at=published,
        ))
    return items


def load_intelligence_feed(
    now: datetime | None = None,
    timeout: float = 15.0,
    client: httpx.Client | None = None,
    max_items: int = 30,
) -> IntelligenceFeed:
    """Discover current-month rare-metal articles and sort newest first."""
    fetched_at = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    own_client = client is None
    news_client = client or httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 metals-dashboard/1.0"},
    )
    found: list[IntelligenceCard] = []
    failures: list[str] = []
    try:
        for index, query in enumerate(_queries(fetched_at), start=1):
            try:
                response = news_client.get(
                    GOOGLE_NEWS_RSS,
                    params={"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
                )
                response.raise_for_status()
                found.extend(_parse_rss(response.content, fetched_at))
            except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                failures.append(f"实时检索组 {index}：{type(exc).__name__}")
    finally:
        if own_client:
            news_client.close()

    deduplicated: dict[str, IntelligenceCard] = {}
    retained_titles: list[str] = []
    for item in sorted(found, key=lambda entry: entry.published_at, reverse=True):
        key = re.sub(r"\W+", "", item.title.casefold())
        if key and key not in deduplicated and not _near_duplicate(item.title, retained_titles):
            deduplicated[key] = item
            retained_titles.append(item.title)
    items = list(deduplicated.values())[:max_items]
    return IntelligenceFeed(
        items=items,
        unavailable_sources=failures,
        fetched_at=fetched_at,
        discovery_note=(
            "每次缓存失效后重新检索 Google News RSS，仅保留当前自然月、稀土或战略小金属且包含产业事件关键词的文章；"
            "按发布时间倒序并去重。链接由 Google News 跳转至收录媒体。未启用正文级摘要时只展示标题信号，不推断文章结论。"
        ),
    )
