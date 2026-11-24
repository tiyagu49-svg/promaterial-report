import json
from datetime import date, datetime

from mas_platform.reports.market_feed import load_market_feed, load_shfe_feed


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeShfeClient:
    def get(self, url):
        day_text = url.rsplit("kx", 1)[1].split(".dat", 1)[0]
        day = date.fromisoformat(f"{day_text[:4]}-{day_text[4:6]}-{day_text[6:]}")
        distance = (date(2026, 11, 24) - day).days
        price = 80_000 - distance * 10
        return FakeResponse({
            "o_msg": "查询成功",
            "update_date": f"{day_text} 15:55:49",
            "o_curinstrument": [
                {"PRODUCTGROUPID": "cu", "DELIVERYMONTH": "2701", "OPENPRICE": price - 100,
                 "HIGHESTPRICE": price + 200, "LOWESTPRICE": price - 200, "CLOSEPRICE": price,
                 "PRESETTLEMENTPRICE": price - 50, "VOLUME": 1000, "OPENINTEREST": 2000},
                {"PRODUCTGROUPID": "cu", "DELIVERYMONTH": "2702", "CLOSEPRICE": price + 500,
                 "VOLUME": 10},
            ],
        })


def test_unconfigured_market_feed_never_falls_back_to_demo(monkeypatch):
    monkeypatch.delenv("MAS_MARKET_DATA_URL", raising=False)
    feed = load_market_feed(include_public=False)
    assert feed.quotes == []
    assert feed.freshness_label == "无可用数据"
    assert "不展示任何模拟现货价格" in feed.message


def test_shfe_feed_uses_most_active_contract_and_verified_history():
    now = datetime.fromisoformat("2026-11-24T16:30:00+08:00")
    feed = load_shfe_feed(now=now, client=FakeShfeClient())
    copper = feed.quotes[0]
    assert feed.mode == "delayed"
    assert feed.as_of.isoformat() == "2026-11-24T15:55:49+08:00"
    assert copper.name == "铜"
    assert copper.contract == "CU2701"
    assert copper.price == 80_000
    assert copper.source == "上海期货交易所"
    assert copper.source_url.endswith("/dailyandweeklydata/")
    assert copper.raw_source_url.endswith("kx20261124.dat")
    assert copper.data_status == "官方收盘"
    assert copper.day_change > 0
    assert copper.week_change > 0
    assert len(copper.trend) == 13
    assert len(copper.trend_dates) == 13


def test_market_feed_reads_authorised_json_export(tmp_path):
    path = tmp_path / "market.json"
    path.write_text(json.dumps({
        "source_name": "测试授权源",
        "source_url": "https://example.com/feed",
        "mode": "live",
        "as_of": datetime.now().astimezone().isoformat(),
        "quotes": [{
            "symbol": "Nd2O3",
            "name": "氧化镨钕",
            "specification": "TREO ≥99%",
            "price": 560000,
            "unit": "元/吨",
            "day_change": 1.2,
            "week_change": 2.4,
            "month_change": 3.1,
            "year_change": 8.6,
            "trend": [530, 535, 540, 545, 550, 560],
            "signal": "价格延续上行。",
            "source": "测试授权源",
            "source_url": "https://example.com/feed",
            "updated_at": datetime.now().astimezone().isoformat(),
        }],
    }, ensure_ascii=False), encoding="utf-8")

    feed = load_market_feed(str(path), include_public=False)
    assert feed.mode == "live"
    assert feed.source_name == "测试授权源"
    assert feed.quotes[0].price == 560000
