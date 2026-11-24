"""Verified market feeds for the metals dashboard.

Public exchange data is loaded from first-party endpoints. Licensed spot data
can be merged through ``MAS_MARKET_DATA_URL``. No synthetic prices are returned
when a source is missing or unavailable.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field, ValidationError

from .market_intelligence import MarketQuote


SHANGHAI = ZoneInfo("Asia/Shanghai")
SHFE_REPORT_URL = "https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/"
SHFE_DATA_URL = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{date}.dat"
SHFE_PRODUCTS = {
    "cu": ("铜", "工业基本金属", "元/吨"),
    "al": ("铝", "工业基本金属", "元/吨"),
    "zn": ("锌", "工业基本金属", "元/吨"),
    "pb": ("铅", "工业基本金属", "元/吨"),
    "ni": ("镍", "新能源与基本金属", "元/吨"),
    "sn": ("锡", "战略小金属", "元/吨"),
    "ao": ("氧化铝", "新能源与基本金属", "元/吨"),
    "au": ("黄金", "贵金属", "元/克"),
    "ag": ("白银", "贵金属", "元/千克"),
}


class MarketFeed(BaseModel):
    quotes: list[MarketQuote] = Field(default_factory=list)
    source_name: str = ""
    source_url: str = ""
    as_of: datetime
    loaded_at: datetime
    mode: Literal["live", "delayed", "snapshot"]
    message: str = ""

    @property
    def age(self) -> timedelta:
        return self.loaded_at.astimezone(SHANGHAI) - self.as_of.astimezone(SHANGHAI)

    @property
    def freshness_label(self) -> str:
        if not self.quotes:
            return "无可用数据"
        if self.mode == "snapshot":
            return "快照"
        if self.mode == "delayed":
            return "官方收盘"
        if self.age <= timedelta(minutes=30):
            return "实时"
        if self.age <= timedelta(hours=24):
            return "延迟"
        return "数据陈旧"


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _change(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline in (None, 0):
        return None
    return round((current / baseline - 1) * 100, 4)


def _validate_payload(payload: object, loaded_at: datetime) -> MarketFeed:
    if not isinstance(payload, dict):
        raise ValueError("行情 feed 必须是 JSON 对象。")
    quotes = payload.get("quotes")
    if not isinstance(quotes, list) or not quotes:
        raise ValueError("行情 feed 缺少非空 quotes 列表。")
    as_of_raw = payload.get("as_of") or max(item["updated_at"] for item in quotes)
    as_of = datetime.fromisoformat(str(as_of_raw))
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=SHANGHAI)
    return MarketFeed(
        quotes=[MarketQuote.model_validate(item) for item in quotes],
        source_name=str(payload.get("source_name", "授权现货行情接口")),
        source_url=str(payload.get("source_url", "")),
        as_of=as_of,
        loaded_at=loaded_at,
        mode=payload.get("mode", "live"),
        message=str(payload.get("message", "")),
    )


def _load_json_source(source: str, timeout: float) -> object:
    if source.startswith(("https://", "http://")):
        response = httpx.get(source, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.json()
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _shfe_payload(client: httpx.Client, trading_day: date) -> dict[str, Any] | None:
    url = SHFE_DATA_URL.format(date=trading_day.strftime("%Y%m%d"))
    response = client.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("o_curinstrument"), list):
        raise ValueError(f"上期所响应结构已变化：{url}")
    if payload.get("o_msg") not in (None, "查询成功"):
        return None
    return payload


def _session_on_or_before(
    client: httpx.Client,
    target: date,
    memo: dict[date, dict[str, Any] | None],
    max_lookback: int = 10,
) -> tuple[date, dict[str, Any]] | None:
    for offset in range(max_lookback + 1):
        candidate = target - timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        if candidate not in memo:
            memo[candidate] = _shfe_payload(client, candidate)
        payload = memo[candidate]
        if payload and payload.get("o_curinstrument"):
            return candidate, payload
    return None


def _main_contract(payload: dict[str, Any], product: str) -> dict[str, Any] | None:
    rows = []
    for row in payload.get("o_curinstrument", []):
        if str(row.get("PRODUCTGROUPID", "")).strip().lower() != product:
            continue
        if not str(row.get("DELIVERYMONTH", "")).isdigit():
            continue
        if _as_float(row.get("CLOSEPRICE")) is None:
            continue
        rows.append(row)
    return max(rows, key=lambda item: _as_float(item.get("VOLUME")) or 0, default=None)


def _payload_time(payload: dict[str, Any], fallback_day: date) -> datetime:
    raw = str(payload.get("update_date", "")).strip()
    try:
        parsed = datetime.strptime(raw, "%Y%m%d %H:%M:%S")
    except ValueError:
        parsed = datetime.combine(fallback_day, datetime.min.time()).replace(hour=16)
    return parsed.replace(tzinfo=SHANGHAI)


def _market_signal(name: str, week_change: float | None, volume: float | None) -> str:
    if week_change is None:
        direction = "周度对比数据暂不完整"
    elif week_change >= 3:
        direction = "主力合约周度涨幅显著"
    elif week_change <= -3:
        direction = "主力合约周度回落明显"
    elif week_change > 0:
        direction = "主力合约周度偏强"
    elif week_change < 0:
        direction = "主力合约周度偏弱"
    else:
        direction = "主力合约周度持平"
    volume_text = f"，当日成交 {volume:,.0f} 手" if volume is not None else ""
    return f"{name}{direction}{volume_text}；注意主力换月可能造成连续序列跳变。"


def load_shfe_feed(
    now: datetime | None = None,
    timeout: float = 12.0,
    client: httpx.Client | None = None,
) -> MarketFeed:
    """Load verified SHFE daily closes and a 13-week main-contract history."""
    loaded_at = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    own_client = client is None
    market_client = client or httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 metals-decision-dashboard/1.0"},
    )
    memo: dict[date, dict[str, Any] | None] = {}
    try:
        latest = _session_on_or_before(market_client, loaded_at.date(), memo)
        if latest is None:
            raise ValueError("最近 10 天未找到上期所交易日数据。")
        latest_day, latest_payload = latest
        reference_targets = {
            "previous": latest_day - timedelta(days=1),
            "week": latest_day - timedelta(days=7),
            "quarter": latest_day - timedelta(days=90),
            "year": latest_day - timedelta(days=365),
        }
        references = {
            name: _session_on_or_before(market_client, target, memo)
            for name, target in reference_targets.items()
        }
        weekly_sessions = []
        for weeks_ago in range(12, -1, -1):
            session = _session_on_or_before(
                market_client,
                latest_day - timedelta(days=weeks_ago * 7),
                memo,
            )
            if session and (not weekly_sessions or session[0] != weekly_sessions[-1][0]):
                weekly_sessions.append(session)

        quotes = []
        updated_at = _payload_time(latest_payload, latest_day)
        latest_url = SHFE_DATA_URL.format(date=latest_day.strftime("%Y%m%d"))
        for product, (name, category, unit) in SHFE_PRODUCTS.items():
            row = _main_contract(latest_payload, product)
            if row is None:
                continue
            price = _as_float(row.get("CLOSEPRICE"))
            if price is None:
                continue
            baseline_prices: dict[str, float | None] = {}
            for period, session in references.items():
                historical_row = _main_contract(session[1], product) if session else None
                baseline_prices[period] = _as_float(historical_row.get("CLOSEPRICE")) if historical_row else None
            trend_values: list[float] = []
            trend_dates: list[date] = []
            for session_day, payload in weekly_sessions:
                historical_row = _main_contract(payload, product)
                historical_price = _as_float(historical_row.get("CLOSEPRICE")) if historical_row else None
                if historical_price is not None:
                    trend_dates.append(session_day)
                    trend_values.append(historical_price)
            week_change = _change(price, baseline_prices["week"])
            volume = _as_float(row.get("VOLUME"))
            contract = f"{product.upper()}{str(row.get('DELIVERYMONTH', '')).strip()}"
            quotes.append(MarketQuote(
                symbol=f"SHFE:{contract}",
                name=name,
                specification=f"上期所主力合约 {contract}",
                price=price,
                unit=unit,
                day_change=_change(price, baseline_prices["previous"]) or 0.0,
                week_change=week_change or 0.0,
                month_change=_change(price, baseline_prices["quarter"]) or 0.0,
                year_change=_change(price, baseline_prices["year"]),
                trend=trend_values or [price, price],
                trend_dates=trend_dates,
                signal=_market_signal(name, week_change, volume),
                source="上海期货交易所",
                source_url=SHFE_REPORT_URL,
                raw_source_url=latest_url,
                methodology_url=SHFE_REPORT_URL,
                updated_at=updated_at,
                category=category,
                market_type="期货",
                price_kind="主力合约收盘价",
                exchange="SHFE",
                contract=contract,
                high=_as_float(row.get("HIGHESTPRICE")),
                low=_as_float(row.get("LOWESTPRICE")),
                open_price=_as_float(row.get("OPENPRICE")),
                previous_settlement=_as_float(row.get("PRESETTLEMENTPRICE")),
                volume=volume,
                open_interest=_as_float(row.get("OPENINTEREST")),
                calculation_note="日/周/三个月/同比均以对应交易日前最近交易日的主力合约收盘价计算；主力合约按当日成交量选择。",
                data_status="官方收盘",
            ))
        return MarketFeed(
            quotes=quotes,
            source_name="上海期货交易所",
            source_url=SHFE_REPORT_URL,
            as_of=updated_at,
            loaded_at=loaded_at,
            mode="delayed",
            message="上期所数据为最近交易日官方收盘数据，不是盘中逐笔行情。",
        )
    finally:
        if own_client:
            market_client.close()


def load_market_feed(
    source: str | None = None,
    timeout: float = 12.0,
    include_public: bool = True,
) -> MarketFeed:
    """Merge official public exchange data with an optional licensed spot feed."""
    loaded_at = datetime.now(SHANGHAI)
    feeds: list[MarketFeed] = []
    messages: list[str] = []
    if include_public:
        try:
            feeds.append(load_shfe_feed(now=loaded_at, timeout=timeout))
        except (ValueError, httpx.HTTPError, json.JSONDecodeError) as exc:
            messages.append(f"上期所官方数据读取失败：{exc}")

    configured = source or os.getenv("MAS_MARKET_DATA_URL", "").strip()
    if configured:
        try:
            feeds.append(_validate_payload(_load_json_source(configured, timeout), loaded_at))
        except (OSError, ValueError, KeyError, httpx.HTTPError, ValidationError) as exc:
            messages.append(f"授权现货接口读取失败：{exc}")
    else:
        messages.append("SMM 等现货行情尚未配置授权接口，因此不展示任何模拟现货价格。")

    quotes = [quote for feed in feeds for quote in feed.quotes]
    if feeds:
        as_of = max(feed.as_of for feed in feeds)
        source_name = " + ".join(feed.source_name for feed in feeds)
        source_url = next((feed.source_url for feed in feeds if feed.source_url), "")
        mode: Literal["live", "delayed", "snapshot"] = (
            "live" if any(feed.mode == "live" for feed in feeds) else "delayed"
        )
        messages.extend(feed.message for feed in feeds if feed.message)
    else:
        as_of = loaded_at
        source_name = "暂无可用数据源"
        source_url = ""
        mode = "snapshot"
    return MarketFeed(
        quotes=quotes,
        source_name=source_name,
        source_url=source_url,
        as_of=as_of,
        loaded_at=loaded_at,
        mode=mode,
        message=" ".join(messages),
    )
