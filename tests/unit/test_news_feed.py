from datetime import datetime

from mas_platform.reports.news_feed import GOOGLE_NEWS_RSS, load_intelligence_feed


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>Rare earth supply project expands - Reuters</title><link>https://news.google.com/a</link><pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate><source>Reuters</source></item>
<item><title>IEA rare earth outlook warns about supply - IEA</title><link>https://news.google.com/b</link><pubDate>Sun, 22 Nov 2026 08:00:00 GMT</pubDate><source>IEA</source></item>
<item><title>Rare earth supply project expands - Reuters</title><link>https://news.google.com/a2</link><pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate><source>Reuters</source></item>
<item><title>Rare earth mine opened last month - Example</title><link>https://news.google.com/old</link><pubDate>Sat, 31 Oct 2026 08:00:00 GMT</pubDate><source>Example</source></item>
<item><title>Unrelated sports story</title><link>https://news.google.com/no</link><pubDate>Mon, 23 Nov 2026 09:00:00 GMT</pubDate><source>Example</source></item>
<item><title>稀土ETF一键布局 - 搜狐</title><link>https://news.google.com/spam</link><pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate><source>搜狐</source></item>
</channel></rss>""".encode("utf-8")


class FakeResponse:
    content = RSS

    def raise_for_status(self):
        return None


class FakeClient:
    def get(self, url, params):
        assert url == GOOGLE_NEWS_RSS
        assert "after:2026-11-01" in params["q"]
        return FakeResponse()


def test_feed_keeps_only_current_month_relevant_unique_items_newest_first():
    feed = load_intelligence_feed(
        now=datetime.fromisoformat("2026-11-24T12:00:00+08:00"),
        client=FakeClient(),
    )
    assert [item.title for item in feed.items] == [
        "Rare earth supply project expands",
        "IEA rare earth outlook warns about supply",
    ]
    assert feed.items[0].kind == "消息面"
    assert feed.items[1].kind == "机构观点"
    assert all(item.published_at.month == 11 for item in feed.items)
