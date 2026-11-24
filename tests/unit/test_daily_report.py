import pytest

from mas_platform.llm import LLMResponse, MockLLMClient
from mas_platform.reports.daily import generate_daily_report, load_demo_data


def test_daily_report_contains_computed_comparisons():
    llm = MockLLMClient([LLMResponse(content="### 整体概览\n演示分析。")])

    report = generate_daily_report(load_demo_data(), llm)

    assert "# 经营数据日报 — 2026-11-11" in report
    assert "| 销售额 | 128,650 元 | 119,200 元 | +9,450 元 | +7.93% |" in report
    assert "| 转化率 | 3.8% | 4.1% | -0.3% | -7.32% |" in report
    assert "演示分析" in report


def test_daily_report_rejects_empty_llm_analysis():
    llm = MockLLMClient([LLMResponse(content="  ")])

    with pytest.raises(ValueError, match="empty daily report analysis"):
        generate_daily_report(load_demo_data(), llm)


def test_daily_report_handles_zero_comparison_value():
    llm = MockLLMClient([LLMResponse(content="分析")])
    data = {
        "report_date": "2026-11-11",
        "source": "test",
        "metrics": [{"name": "新增客户", "value": 4, "previous_value": 0}],
    }

    report = generate_daily_report(data, llm)

    assert "| 新增客户 | 4 | 0 | +4 | —（基期为 0） |" in report
