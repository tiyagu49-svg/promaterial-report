"""Verified metals market dashboard for decision makers."""
from __future__ import annotations

import json
from base64 import b64encode
from datetime import timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from mas_platform.reports.market_feed import MarketFeed, load_market_feed
from mas_platform.reports.market_intelligence import MarketQuote
from mas_platform.reports.news_feed import IntelligenceCard, IntelligenceFeed, load_intelligence_feed
from mas_platform.reports.uploaded import parse_date_values


SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_WATCHLIST = ["铜", "铝", "镍", "锡", "黄金", "白银"]
CATEGORY_ORDER = ["工业基本金属", "新能源与基本金属", "战略小金属", "贵金属", "稀土磁材", "其他金属"]
ELEMENT_SYMBOLS = {
    "铜": "Cu", "铝": "Al", "锌": "Zn", "铅": "Pb", "镍": "Ni", "锡": "Sn",
    "黄金": "Au", "白银": "Ag", "氧化铝": "Al₂O₃",
}


def _date_columns(frame: pd.DataFrame) -> list[str]:
    """Compatibility helper retained for internal-data report tests."""
    candidates = []
    for column in frame.columns:
        parsed = parse_date_values(frame[column], str(column))
        if parsed.notna().any() and parsed.notna().mean() >= 0.8:
            candidates.append(column)
    return candidates


@st.cache_data(ttl=300, show_spinner="正在读取官方行情并计算历史变化……")
def _cached_feed() -> MarketFeed:
    return load_market_feed()


@st.cache_data(ttl=60, show_spinner="正在检索本月稀土行业最新消息……")
def _cached_intelligence() -> IntelligenceFeed:
    return load_intelligence_feed()


def _theme() -> None:
    st.markdown(
        """
        <style>
        :root { --navy:#092a42; --blue:#174d6c; --ink:#0a2030; --muted:#6c8396; --line:#dbe5ec; --up:#c8372d; --down:#087d63; }
        .stApp { background:#f6f8fa; color:var(--ink); }
        .block-container { max-width:1500px; padding:0 1.7rem 3rem; }
        [data-testid="stHeader"] { background:transparent; }
        .hero { margin:0 -1.7rem; padding:28px max(2rem,calc((100vw - 1440px)/2)) 23px; background:linear-gradient(118deg,#08283f,#1b5776); color:white; }
        .hero-main { display:flex; justify-content:space-between; gap:30px; align-items:flex-start; }
        .eyebrow { color:#86c9ee; font-size:.78rem; letter-spacing:.19em; font-weight:800; }
        .hero h1 { color:white; margin:.28rem 0 .28rem; font-size:2.25rem; letter-spacing:-.04em; }
        .hero-copy { color:#c5e1ef; font-size:.98rem; }
        .hero-date { text-align:right; padding-left:30px; border-left:1px solid rgba(255,255,255,.24); min-width:190px; }
        .hero-date b { display:block; font-size:3.2rem; line-height:1; letter-spacing:-.06em; }
        .hero-date span { color:#8bc5e5; letter-spacing:.1em; }
        .meta { margin-top:18px; padding-top:14px; border-top:1px solid rgba(255,255,255,.2); display:flex; gap:26px; flex-wrap:wrap; color:#8bc5e5; font-size:.84rem; }
        .meta strong { color:white; }
        .status { display:inline-block; padding:2px 9px; border-radius:999px; background:rgba(64,184,139,.2); color:#c6f5e4; }
        .summary-strip { margin:17px 0 13px; background:white; border:1px solid var(--line); border-left:5px solid #174d6c; border-radius:10px; padding:14px 18px; color:#40596d; }
        .summary-strip strong { color:#0a2030; }
        .source-warning { margin-bottom:14px; padding:10px 14px; border:1px solid #ecd39c; border-radius:10px; background:#fff7e8; color:#765019; font-size:.86rem; }
        .section-title { display:flex; justify-content:space-between; align-items:flex-end; margin-top:18px; margin-bottom:7px; }
        .section-title h3 { margin:0; font-size:1.08rem; }
        .section-title span { color:#7890a3; font-size:.78rem; }
        .pending { padding:13px 16px; border:1px dashed #b9c9d4; border-radius:10px; background:#f8fafb; color:#637b8e; font-size:.85rem; }
        div[data-testid="stMetric"] { background:white; border:1px solid var(--line); border-radius:12px; padding:12px 14px; box-shadow:0 5px 16px rgba(15,52,78,.035); }
        div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; background:white; }
        .source-card { padding:12px 14px; background:#f3f7fa; border:1px solid #dce6ed; border-radius:10px; line-height:1.65; }
        .formula { padding:10px 12px; background:#fff8eb; border-radius:8px; color:#6f5128; font-size:.84rem; }
        .market-cards { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:18px 0 14px; }
        .market-card { position:relative; min-height:128px; overflow:hidden; padding:16px 17px; border:1px solid var(--line); border-radius:14px; background:linear-gradient(145deg,#fff,#f8fbfd); box-shadow:0 8px 24px rgba(15,52,78,.045); }
        .market-card .label { color:#70889a; font-size:.78rem; font-weight:700; letter-spacing:.05em; }
        .market-card .metal { display:flex; align-items:baseline; gap:8px; margin-top:8px; }
        .market-card .metal strong { color:#102b3e; font-size:1.35rem; }
        .market-card .symbol { color:#7892a5; font:700 1rem ui-monospace,SFMono-Regular,monospace; }
        .market-card .delta { margin-top:5px; font-size:.88rem; font-weight:750; }
        .market-card.up .delta { color:var(--up); } .market-card.down .delta { color:var(--down); }
        .market-card svg { position:absolute; right:10px; bottom:8px; width:44%; height:46px; opacity:.85; }
        .market-card path { fill:none; stroke-width:2.2; stroke-linecap:round; stroke-linejoin:round; stroke-dasharray:240; stroke-dashoffset:240; animation:draw-line 1.15s cubic-bezier(.2,.7,.2,1) forwards; }
        .market-card.up path { stroke:var(--up); } .market-card.down path { stroke:var(--down); } .market-card.neutral path { stroke:#1d6688; }
        .change-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:8px 0 16px; }
        .change-card { padding:14px 16px; border:1px solid var(--line); border-radius:12px; background:white; }
        .change-card .period { color:#405667; font-size:.84rem; font-weight:650; }
        .change-card .value { margin-top:6px; font-size:1.65rem; line-height:1.15; font-weight:750; letter-spacing:-.035em; }
        .change-card.up .value { color:var(--up); } .change-card.down .value { color:var(--down); } .change-card.neutral .value { color:#607d90; }
        .intel-head { display:flex; align-items:flex-end; justify-content:space-between; gap:18px; margin:30px 0 12px; padding-top:20px; border-top:1px solid var(--line); }
        .intel-head h2 { margin:0; color:#102b3e; font-size:1.38rem; letter-spacing:-.025em; }
        .intel-head p { margin:5px 0 0; color:#70889a; font-size:.86rem; }
        .intel-count { color:#315d77; font-size:.8rem; white-space:nowrap; }
        .intel-card { margin-bottom:10px; padding:15px 16px 14px; border:1px solid var(--line); border-left:4px solid #587b90; border-radius:12px; background:white; box-shadow:0 5px 16px rgba(15,52,78,.03); transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease; }
        .intel-card:hover { transform:translateY(-1px); box-shadow:0 9px 24px rgba(15,52,78,.07); border-color:#b8cbd7; }
        .intel-card.policy { border-left-color:#9a603c; } .intel-card.export { border-left-color:#be4537; }
        .intel-card.supply { border-left-color:#16816e; } .intel-card.standard { border-left-color:#3a7091; }
        .intel-card.market-news { border-left-color:#b56b2a; }
        .intel-card.global { border-left-color:#486aaf; } .intel-card.risk { border-left-color:#7656a9; }
        .intel-card.resource { border-left-color:#3f7488; }
        .intel-meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px; color:#7890a3; font-size:.76rem; }
        .intel-tag { padding:2px 8px; border-radius:999px; background:#edf3f6; color:#31566e; font-weight:750; }
        .source-state { display:inline-flex; align-items:center; gap:5px; }
        .source-state::before { content:""; width:6px; height:6px; border-radius:50%; background:#1e9474; }
        .source-state.offline::before { background:#c54438; }
        .intel-title { color:#102b3e !important; font-size:1rem; font-weight:800; line-height:1.45; text-decoration:none !important; }
        .intel-title:hover { color:#17628b !important; }
        .intel-takeaway { margin:7px 0 10px; color:#496274; font-size:.88rem; line-height:1.65; }
        .intel-affected { color:#7890a3; font-size:.76rem; }
        @keyframes draw-line { to { stroke-dashoffset:0; } }
        @media (prefers-reduced-motion:reduce) { .market-card path { animation:none; stroke-dashoffset:0; } }
        .up-text { color:var(--up); } .down-text { color:var(--down); }
        @media (max-width:760px) {
          .block-container { padding:0 .75rem 2rem; }
          .hero { margin:0 -.75rem; padding:23px 16px; }
          .hero-main { display:block; }
          .hero-date { border:0; padding:14px 0 0; text-align:left; }
          .hero-date b { font-size:2rem; }
          .market-cards { grid-template-columns:repeat(2,minmax(0,1fr)); }
          .change-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%" if value else "0.00%"


def _movement_tone(value: float | None) -> str:
    if value is None or value == 0:
        return "neutral"
    return "up" if value > 0 else "down"


def _sparkline_uri(values: list[float], change: float | None) -> str:
    tone = _movement_tone(change)
    color = {"up": "#c8372d", "down": "#087d63", "neutral": "#607d90"}[tone]
    points = _sparkline(values)
    path = " L ".join(points.split())
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="190" height="42" viewBox="0 0 100 44" '
        'preserveAspectRatio="none">'
        f'<path d="M {path}" fill="none" stroke="{color}" stroke-width="2.4" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="100" cy="{points.split()[-1].split(",")[1]}" r="2.7" fill="white" '
        f'stroke="{color}" stroke-width="2"/></svg>'
    )
    return "data:image/svg+xml;base64," + b64encode(svg.encode()).decode()


def _quote_frame(quotes: list[MarketQuote]) -> pd.DataFrame:
    return pd.DataFrame([{
        "品种": quote.name,
        "规格 / 合约": quote.contract or quote.specification,
        "最新价": quote.price,
        "单位": quote.unit,
        "日": quote.day_change,
        "周": quote.week_change,
        "3个月": quote.month_change,
        "同比": quote.year_change,
        "近三个月周度走势": _sparkline_uri(quote.trend, quote.day_change),
        "一句话要点": quote.signal,
        "状态": quote.data_status,
    } for quote in quotes])


def _change_cards(quote: MarketQuote) -> str:
    periods = [
        ("日", quote.day_change),
        ("周", quote.week_change),
        ("3个月", quote.month_change),
        ("同比", quote.year_change),
    ]
    cards = []
    for label, value in periods:
        cards.append(
            f'<div class="change-card {_movement_tone(value)}">'
            f'<div class="period">{label}</div>'
            f'<div class="value">{escape(_percent(value))}</div></div>'
        )
    return '<div class="change-grid">' + "".join(cards) + "</div>"


def _source_dialog(quote: MarketQuote) -> None:
    @st.dialog(f"{quote.name} · 数据来源与口径", width="large")
    def dialog() -> None:
        st.markdown(
            f"<div class='source-card'><strong>{escape(quote.source)}</strong><br>"
            f"{escape(quote.market_type)} · {escape(quote.price_kind)} · "
            f"{escape(quote.contract or quote.specification)}<br>"
            f"行情时间：{quote.updated_at.astimezone(SHANGHAI):%Y-%m-%d %H:%M:%S} · "
            f"状态：{escape(quote.data_status)}</div>",
            unsafe_allow_html=True,
        )
        left, middle, right = st.columns(3)
        left.metric("最新价", f"{quote.price:,.2f} {quote.unit}", _percent(quote.day_change), delta_color="inverse")
        middle.metric("当日最高 / 最低", f"{quote.high:,.2f}" if quote.high is not None else "—", f"最低 {quote.low:,.2f}" if quote.low is not None else "—", delta_color="off")
        right.metric("成交量 / 持仓量", f"{quote.volume:,.0f} 手" if quote.volume is not None else "—", f"持仓 {quote.open_interest:,.0f}" if quote.open_interest is not None else "—", delta_color="off")

        if quote.trend:
            index = quote.trend_dates if len(quote.trend_dates) == len(quote.trend) else range(len(quote.trend))
            chart = pd.DataFrame({quote.name: quote.trend}, index=index)
            chart_color = {"up": "#c8372d", "down": "#087d63", "neutral": "#607d90"}[_movement_tone(quote.day_change)]
            st.line_chart(chart, color=chart_color, height=260)

        st.markdown("#### 变化率")
        st.markdown(_change_cards(quote), unsafe_allow_html=True)
        st.markdown(f"<div class='formula'><strong>计算口径：</strong>{escape(quote.calculation_note or '以数据源公布口径为准。')}</div>", unsafe_allow_html=True)
        link_a, link_b = st.columns(2)
        if quote.source_url:
            link_a.link_button("打开官方行情页面", quote.source_url, use_container_width=True)
        if quote.methodology_url:
            link_b.link_button("查看来源说明", quote.methodology_url, use_container_width=True)
        raw_record = {
            "品种": quote.name, "元素符号": ELEMENT_SYMBOLS.get(quote.name, ""),
            "合约": quote.contract, "最新价": quote.price, "单位": quote.unit,
            "最高价": quote.high, "最低价": quote.low, "成交量": quote.volume,
            "持仓量": quote.open_interest, "更新时间": quote.updated_at.isoformat(),
            # Stay compatible with an already-running process that imported the
            # pre-migration MarketQuote model before raw_source_url was added.
            "来源": quote.source, "机器接口": getattr(quote, "raw_source_url", ""),
        }
        with st.expander("查看本品种结构化原始字段"):
            st.json(raw_record)
            st.download_button(
                "下载本品种 JSON",
                json.dumps(raw_record, ensure_ascii=False, indent=2),
                file_name=f"{quote.name}-{quote.contract}.json",
                mime="application/json",
                use_container_width=True,
            )
        st.caption("原始链接用于交叉核验。交易所数据可能在结算完成后更新，页面以来源时间戳为准。")
    dialog()


def _render_group(category: str, quotes: list[MarketQuote]) -> MarketQuote | None:
    st.markdown(
        f"<div class='section-title'><h3>{escape(category)}</h3><span>{len(quotes)} 个品种 · 点击任意一行查看来源</span></div>",
        unsafe_allow_html=True,
    )
    frame = _quote_frame(quotes)
    def movement_style(value: object) -> str:
        if not isinstance(value, (int, float)) or pd.isna(value) or value == 0:
            return "color:#607d90;font-weight:650"
        return "color:#c8372d;font-weight:700" if value > 0 else "color:#087d63;font-weight:700"

    styled_frame = frame.style.map(
        movement_style,
        subset=["日", "周", "3个月", "同比"],
    )
    event = st.dataframe(
        styled_frame,
        key=f"market-{category}",
        width="stretch",
        height=min(72 + len(frame) * 42, 330),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "品种": st.column_config.TextColumn(width="small"),
            "规格 / 合约": st.column_config.TextColumn(width="medium"),
            "最新价": st.column_config.NumberColumn(format="localized", width="small"),
            "单位": st.column_config.TextColumn(width="small"),
            "日": st.column_config.NumberColumn(format="%+.2f%%", width="small"),
            "周": st.column_config.NumberColumn(format="%+.2f%%", width="small"),
            "3个月": st.column_config.NumberColumn(format="%+.2f%%", width="small"),
            "同比": st.column_config.NumberColumn(format="%+.2f%%", width="small"),
            "近三个月周度走势": st.column_config.ImageColumn(width="medium", help="红色为上涨，绿色为下跌，蓝灰为持平"),
            "一句话要点": st.column_config.TextColumn(width="large"),
            "状态": st.column_config.TextColumn(width="small"),
        },
    )
    selected_rows = event.selection.rows
    if selected_rows:
        return quotes[selected_rows[0]]
    return None


def _sparkline(values: list[float]) -> str:
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = high - low or 1
    points = []
    for index, value in enumerate(values):
        x = index * 100 / (len(values) - 1)
        y = 38 - (value - low) * 32 / span
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def _summary_card(label: str, quote: MarketQuote, detail: str, tone: str) -> str:
    symbol = escape(ELEMENT_SYMBOLS.get(quote.name, quote.symbol.split(":")[-1][:2]))
    return (
        f'<article class="market-card {tone}"><div class="label">{escape(label)}</div>'
        f'<div class="metal"><strong>{escape(quote.name)}</strong><span class="symbol">{symbol}</span></div>'
        f'<div class="delta">{escape(detail)}</div>'
        f'<svg viewBox="0 0 100 44" preserveAspectRatio="none" aria-hidden="true"><path d="M '
        + " L ".join(_sparkline(quote.trend).split()) + '"/></svg></article>'
    )


def _market_summary(quotes: list[MarketQuote]) -> None:
    if not quotes:
        return
    strongest = max(quotes, key=lambda quote: quote.day_change)
    weakest = min(quotes, key=lambda quote: quote.day_change)
    active = max(quotes, key=lambda quote: quote.volume or 0)
    cards = [
        _summary_card("今日领涨", strongest, _percent(strongest.day_change), _movement_tone(strongest.day_change)),
        _summary_card("今日领跌", weakest, _percent(weakest.day_change), _movement_tone(weakest.day_change)),
        _summary_card("成交最活跃", active, f"{active.volume:,.0f} 手" if active.volume is not None else "—", _movement_tone(active.day_change)),
        _summary_card("行情覆盖", quotes[0], f"{len(quotes)} 个品种 · 全部可追溯", "neutral"),
    ]
    st.markdown('<section class="market-cards">' + "".join(cards) + "</section>", unsafe_allow_html=True)


def _intelligence_card(item: IntelligenceCard) -> str:
    category_class = {
        "政策": "policy", "出口": "export", "供应": "supply", "标准": "standard",
        "市场": "market-news", "全球布局": "global", "风险研判": "risk", "资源数据": "resource",
    }[item.category]
    state_class = "" if item.available else " offline"
    state_text = "本月实时收录" if item.available else "暂时无法连接"
    affected = " · ".join(item.affected)
    return (
        f'<article class="intel-card {category_class}">'
        f'<div class="intel-meta"><span class="intel-tag">{escape(item.category)}</span>'
        f'<span>{escape(item.published_label)}</span><span>·</span><span>{escape(item.source)}</span>'
        f'<span class="source-state{state_class}">{state_text}</span></div>'
        f'<a class="intel-title" href="{escape(item.source_url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer">{escape(item.title)}</a>'
        f'<div class="intel-takeaway">{escape(item.takeaway)}</div>'
        f'<div class="intel-affected">关联：{escape(affected)}</div></article>'
    )


def _render_intelligence(feed: IntelligenceFeed) -> None:
    online_count = sum(item.available for item in feed.items)
    st.markdown(
        f'<div class="intel-head"><div><h2>稀土消息与机构判断</h2>'
        f'<p>仅显示本月内容，按发布时间由新到旧；点击加粗标题阅读原文。</p></div>'
        f'<div class="intel-count">本月 {online_count} 条 · 更新于 {feed.fetched_at.astimezone(SHANGHAI):%H:%M}</div></div>',
        unsafe_allow_html=True,
    )
    if not feed.items:
        st.warning("实时检索当前没有返回符合条件的本月文章，系统没有用历史消息填充。")
        return
    news_column, view_column = st.columns(2, gap="medium")
    groups = [(news_column, "消息面"), (view_column, "机构观点")]
    for column, kind in groups:
        with column:
            st.markdown(f"### {kind}")
            for item in feed.items:
                if item.kind == kind:
                    st.markdown(_intelligence_card(item), unsafe_allow_html=True)
    if feed.unavailable_sources:
        st.warning("以下来源当前无法连接：" + "、".join(feed.unavailable_sources) + "。系统没有使用替代内容填充。")
    with st.expander("数据覆盖与连接说明"):
        st.write(feed.discovery_note)
        st.write("未接入正文摘要：SMM、安泰科、Fastmarkets、Argus等来源存在授权或访问限制；当前不会抓取或转述其付费正文。")


def main() -> None:
    st.set_page_config(
        page_title="金属行情决策台",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _theme()
    feed = _cached_feed()
    now = feed.loaded_at.astimezone(SHANGHAI)
    as_of = feed.as_of.astimezone(SHANGHAI)
    weekday = "一二三四五六日"[now.weekday()]
    date_window = as_of - timedelta(days=90)

    st.markdown(
        f"""
        <section class="hero">
          <div class="hero-main">
            <div><div class="eyebrow">VERIFIED METALS MARKET · DAILY</div><h1>金属行情决策台</h1><div class="hero-copy">国内现货 · 国内期货 · 国际基准 ｜ 每个价格都可追溯到原始来源</div></div>
            <div class="hero-date"><b>{now:%m.%d}</b><span>{now:%Y} / 星期{weekday}</span></div>
          </div>
          <div class="meta">
            <span>数据时点 <strong>{as_of:%m.%d %H:%M}</strong></span>
            <span>趋势区间 <strong>{date_window:%m.%d} — {as_of:%m.%d}</strong></span>
            <span>来源 <strong>{escape(feed.source_name)}</strong></span>
            <span>状态 <strong class="status">{escape(feed.freshness_label)}</strong></span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if feed.message:
        st.markdown(f"<div class='source-warning'>{escape(feed.message)}</div>", unsafe_allow_html=True)
    if not feed.quotes:
        st.error("当前没有可验证的行情数据。系统不会用演示数字填充空缺，请检查网络或授权接口。")
        return

    _market_summary(feed.quotes)
    st.markdown(
        "<div class='summary-strip'><strong>阅读方式：</strong>先看领涨、领跌和成交活跃度，再按金属类别查看日/周/三个月/同比。点击任意行情行，可核验来源、时间戳、原始数据和计算口径。</div>",
        unsafe_allow_html=True,
    )

    control_a, control_b, control_c = st.columns([1, 2, 2])
    view = control_a.segmented_control("视图", ["我的关注", "全部品种"], default="我的关注")
    available_names = [quote.name for quote in feed.quotes]
    default_watchlist = [name for name in DEFAULT_WATCHLIST if name in available_names]
    watchlist = control_b.multiselect("关注品种", available_names, default=default_watchlist)
    search = control_c.text_input("搜索品种或合约", placeholder="例如：铜、镍、AU……")

    visible = feed.quotes
    if view == "我的关注":
        visible = [quote for quote in visible if quote.name in watchlist]
    needle = search.strip().casefold()
    if needle:
        visible = [quote for quote in visible if needle in " ".join([quote.name, quote.symbol, quote.contract, quote.specification]).casefold()]

    selected_quote = None
    for category in CATEGORY_ORDER:
        category_quotes = [quote for quote in visible if quote.category == category]
        if category_quotes:
            group_selection = _render_group(category, category_quotes)
            if group_selection is not None and selected_quote is None:
                selected_quote = group_selection

    # Streamlit only permits one dialog per script run. Multiple dataframes may
    # retain selections across reruns, so resolve them first and open once here.
    if selected_quote is not None:
        _source_dialog(selected_quote)

    if not visible:
        st.info("当前筛选条件没有匹配的品种。")

    _render_intelligence(_cached_intelligence())

    with st.expander("待接入的授权现货品种", expanded=False):
        st.markdown(
            "<div class='pending'><strong>稀土磁材：</strong>氧化镨钕、镨钕金属、氧化镝、镝铁、氧化铽、金属铽。<br>"
            "<strong>新能源与战略小金属：</strong>碳酸锂、氢氧化锂、电解钴、硫酸镍、工业硅、多晶硅、镓、锗、锑、钨、钼、铟、铂、钯。<br>"
            "这些品种只有在 SMM 或其他授权接口返回真实价格和历史序列后才会进入主表。</div>",
            unsafe_allow_html=True,
        )

    footer_a, footer_b = st.columns([3, 1])
    footer_a.caption("数据不会使用参考图中的静态数值。上期所品种来自官方 JSON；现货和国际价格须通过对应授权接口接入。")
    if footer_b.button("立即刷新", use_container_width=True):
        _cached_feed.clear()
        _cached_intelligence.clear()
        st.rerun()


if __name__ == "__main__":
    main()
