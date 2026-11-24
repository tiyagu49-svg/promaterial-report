"""Decision-intelligence data contracts and deterministic dashboard helpers.

The legacy demo brief remains available to tests and non-market prototypes.
The market dashboard never consumes it; verified feeds use the same contracts.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Literal

from pydantic import BaseModel, Field


class MarketQuote(BaseModel):
    symbol: str
    name: str
    specification: str
    price: float
    unit: str
    day_change: float
    week_change: float
    month_change: float
    year_change: float | None = None
    trend: list[float] = Field(min_length=2)
    signal: str
    source: str
    source_url: str
    raw_source_url: str = ""
    updated_at: datetime
    category: str = "其他金属"
    market_type: Literal["现货", "期货", "基准价"] = "现货"
    price_kind: str = "参考价"
    exchange: str = ""
    contract: str = ""
    high: float | None = None
    low: float | None = None
    open_price: float | None = None
    previous_settlement: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    trend_dates: list[date] = Field(default_factory=list)
    methodology_url: str = ""
    calculation_note: str = ""
    data_status: Literal["实时", "延迟", "官方收盘", "快照"] = "快照"


class FxQuote(BaseModel):
    pair: str
    value: float
    change: float
    exposure: str
    source: str
    source_url: str
    updated_at: datetime


class IntelligenceItem(BaseModel):
    category: Literal["政策", "供应", "需求", "出口", "机构"]
    title: str
    summary: str
    impact: Literal["高", "中", "低"]
    direction: Literal["利多", "利空", "中性"]
    affected: list[str]
    source: str
    source_url: str
    published_at: datetime


class DecisionBrief(BaseModel):
    edition: Literal["早报", "午报", "晚报"]
    generated_at: datetime
    headline: str
    executive_summary: str
    watchlist: list[str]
    quotes: list[MarketQuote]
    fx: list[FxQuote]
    intelligence: list[IntelligenceItem]
    demo: bool = True


def demo_brief() -> DecisionBrief:
    """Return a coherent demo payload; values are not represented as live quotes."""
    updated = datetime.fromisoformat("2026-11-23T09:30:00+08:00")
    generated = datetime.now(ZoneInfo("Asia/Shanghai"))
    return DecisionBrief(
        edition="早报",
        generated_at=generated,
        headline="重稀土延续强势，汇率波动放大出口报价风险",
        executive_summary=(
            "今日优先关注镝、铽采购窗口与出口许可进度。轻稀土价格偏弱，"
            "重稀土供应扰动仍在；美元兑人民币中间价小幅上行，海外订单应复核报价有效期。"
        ),
        watchlist=[
            "氧化镝若突破 145 万元/吨，启动二级采购复核",
            "跟踪稀土出口许可与口岸执行口径",
            "美元订单报价有效期建议缩短至 3 个工作日",
        ],
        quotes=[
            MarketQuote(symbol="Nd2O3", name="氧化镨钕", specification="TREO ≥99%", price=565000, unit="元/吨", day_change=-0.7, week_change=-1.15, month_change=-3.5, year_change=30.6, trend=[598, 590, 602, 610, 604, 599, 608, 595, 586, 578, 565], signal="价格回到近月支撑区，关注下游补库强度。", source="SMM（接入示例）", source_url="https://hq.smm.cn/rare-earth", updated_at=updated),
            MarketQuote(symbol="PrNd", name="镨钕金属", specification="Pr/TREM 25±2%", price=692500, unit="元/吨", day_change=-0.58, week_change=-0.98, month_change=-3.6, year_change=29.7, trend=[735, 720, 728, 741, 749, 743, 735, 747, 731, 708, 692.5], signal="倒挂修复仍需观察，采购以刚需为主。", source="SMM（接入示例）", source_url="https://hq.smm.cn/rare-earth", updated_at=updated),
            MarketQuote(symbol="Tb", name="金属铽", specification="Tb/TREM ≥99%", price=7850, unit="元/千克", day_change=0.0, week_change=1.2, month_change=5.6, year_change=None, trend=[7240, 7300, 7380, 7420, 7510, 7600, 7680, 7730, 7780, 7820, 7850], signal="现货偏紧，关注高位成交持续性。", source="SMM（接入示例）", source_url="https://hq.smm.cn/rare-earth", updated_at=updated),
            MarketQuote(symbol="DyFe", name="镝铁合金", specification="Dy 80%", price=1430000, unit="元/吨", day_change=0.7, week_change=2.4, month_change=6.8, year_change=-6.8, trend=[1320, 1335, 1350, 1342, 1360, 1380, 1390, 1385, 1410, 1420, 1430], signal="接近内部预警位，建议复核锁价策略。", source="SMM（接入示例）", source_url="https://hq.smm.cn/rare-earth", updated_at=updated),
            MarketQuote(symbol="Co", name="电解钴", specification="Co ≥99.8%", price=236600, unit="元/吨", day_change=2.42, week_change=11.08, month_change=-2.6, year_change=-38.7, trend=[241, 239, 242, 245, 248, 244, 238, 232, 228, 234, 236.6], signal="短线反弹，但中期供需仍需验证。", source="SMM（接入示例）", source_url="https://hq.smm.cn/cobalt", updated_at=updated),
            MarketQuote(symbol="Ga", name="金属镓", specification="Ga ≥99.999%", price=1740, unit="元/千克", day_change=0.0, week_change=0.0, month_change=-4.4, year_change=None, trend=[1860, 1850, 1840, 1830, 1820, 1810, 1780, 1760, 1748, 1740, 1740], signal="现货弹性偏弱，等待成交量确认。", source="SMM（接入示例）", source_url="https://hq.smm.cn/minor-metals", updated_at=updated),
        ],
        fx=[
            FxQuote(pair="USD/CNY", value=6.7120, change=0.0011, exposure="美元收款 / 原料进口", source="中国货币网", source_url="https://www.chinamoney.com.cn/chinese/bkccpr/", updated_at=updated),
            FxQuote(pair="EUR/CNY", value=7.3496, change=0.0050, exposure="欧洲客户报价", source="中国货币网", source_url="https://www.chinamoney.com.cn/chinese/bkccpr/", updated_at=updated),
            FxQuote(pair="JPY/CNY", value=4.2152, change=0.0191, exposure="日本设备采购（100日元）", source="中国货币网", source_url="https://www.chinamoney.com.cn/chinese/bkccpr/", updated_at=updated),
        ],
        intelligence=[
            IntelligenceItem(category="政策", title="稀土物项出口管制进入常态化执行", summary="钐、钆、铽、镝、镥、钪、钇相关物项出口需核对管制编码与许可要求。", impact="高", direction="中性", affected=["金属铽", "镝铁合金"], source="商务部 / 海关总署", source_url="https://www.mofcom.gov.cn/cms_files/filemanager/policySummary/viewcore_7ef0e7016e934fc9b1bde9c4b6e7e893.html", published_at=datetime.fromisoformat("2026-11-22T18:20:00+08:00")),
            IntelligenceItem(category="供应", title="重稀土供应弹性仍弱", summary="短期现货偏紧与成本支撑叠加，铽、镝报价韧性强于轻稀土。", impact="高", direction="利多", affected=["金属铽", "镝铁合金"], source="行业信息汇总（演示）", source_url="https://hq.smm.cn/rare-earth", published_at=datetime.fromisoformat("2026-11-23T08:40:00+08:00")),
            IntelligenceItem(category="需求", title="磁材企业采购保持刚需节奏", summary="终端订单分化，低价货源收紧但尚未形成一致补库。", impact="中", direction="中性", affected=["氧化镨钕", "镨钕金属"], source="机构观点汇总（演示）", source_url="https://hq.smm.cn/rare-earth", published_at=datetime.fromisoformat("2026-11-23T08:10:00+08:00")),
            IntelligenceItem(category="出口", title="海外报价需同步评估汇率与许可周期", summary="汇率变动与许可办理时间可能同时影响订单毛利及交付承诺。", impact="高", direction="利空", affected=["USD/CNY", "金属铽", "镝铁合金"], source="系统综合研判（演示）", source_url="https://www.chinamoney.com.cn/chinese/bkccpr/", published_at=datetime.fromisoformat("2026-11-23T09:05:00+08:00")),
        ],
    )


def search_brief(brief: DecisionBrief, query: str) -> tuple[list[MarketQuote], list[IntelligenceItem]]:
    """Search quotes and intelligence without external calls."""
    needle = query.strip().casefold()
    if not needle:
        return brief.quotes, brief.intelligence
    quotes = [
        item for item in brief.quotes
        if needle in " ".join([item.name, item.symbol, item.specification, item.signal]).casefold()
    ]
    news = [
        item for item in brief.intelligence
        if needle in " ".join([item.category, item.title, item.summary, *item.affected]).casefold()
    ]
    return quotes, news


def source_catalog() -> list[dict[str, str]]:
    """Describe recommended production sources and their integration constraints."""
    return [
        {"domain": "国内稀土/小金属现货", "source": "SMM 上海有色网", "cadence": "交易日多时点", "use": "报价、区间、快讯、方法论", "access": "商业授权/API 优先，避免未授权抓取", "url": "https://hq.smm.cn/rare-earth"},
        {"domain": "国际基础金属", "source": "LME", "cadence": "交易日", "use": "官方结算价与库存", "access": "通过 LME 授权数据服务或数据商", "url": "https://www.lme.com/en/Market-data/Reports-and-data/LME-Official-Prices"},
        {"domain": "人民币汇率", "source": "中国外汇交易中心", "cadence": "工作日 09:15", "use": "人民币汇率中间价", "access": "官方页面/合规数据接口", "url": "https://www.chinamoney.com.cn/chinese/bkccpr/"},
        {"domain": "出口管制与行业政策", "source": "商务部、海关总署", "cadence": "事件驱动", "use": "公告、清单、许可证规则", "access": "官网公告订阅 + 人工复核", "url": "https://www.mofcom.gov.cn/"},
        {"domain": "进出口量价", "source": "海关总署", "cadence": "月度", "use": "商品编码维度的量价验证", "access": "官方统计或授权数据库", "url": "http://www.customs.gov.cn/"},
    ]
