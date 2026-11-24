from mas_platform.reports.market_intelligence import demo_brief, search_brief, source_catalog


def test_demo_brief_is_explicitly_demo_and_has_required_sections():
    brief = demo_brief()
    assert brief.demo is True
    assert brief.quotes
    assert brief.fx
    assert brief.intelligence
    assert brief.watchlist


def test_search_finds_quote_and_related_intelligence():
    brief = demo_brief()
    quotes, news = search_brief(brief, "镝")
    assert [quote.name for quote in quotes] == ["镝铁合金"]
    assert any("镝铁合金" in item.affected for item in news)


def test_source_catalog_documents_access_constraints():
    sources = source_catalog()
    assert len(sources) >= 4
    assert all(source["url"].startswith("http") for source in sources)
    assert any("授权" in source["access"] for source in sources)
