import re

import pandas as pd
import pytest

from mas_platform.reports.uploaded import (
    answer_period_question,
    generate_period_analysis,
    generate_period_html,
    generate_period_report,
    recommend_analysis_setup,
    summarize_period,
)
from mas_platform.reports.semantics import (
    MetricDefinition,
    formula_columns,
    metric_definitions_from_json,
    metric_definitions_to_json,
)
from mas_platform.web_app import _date_columns


def test_daily_report_sums_latest_day_and_compares_previous_day():
    frame = pd.DataFrame({
        "date": ["2026-11-16", "2026-11-17", "2026-11-17"],
        "sales": ["1,200", "500", "700"],
    })

    summary = summarize_period(frame, "date", ["sales"], "daily", "sum", "sales.csv")
    report = generate_period_report(summary)

    assert summary.period_start.isoformat() == "2026-11-17"
    assert summary.metrics[0].value == 1200
    assert summary.metrics[0].previous_value == 1200
    assert "| sales | 1,200 | 1,200 | +0 | +0.00% |" in report


def test_weekly_report_compares_calendar_weeks_and_uses_last_value():
    frame = pd.DataFrame({
        "date": ["2026-11-08", "2026-11-03", "2026-11-02", "2026-11-01"],
        "inventory": [14, 12, 10, 9],
    })

    summary = summarize_period(frame, "date", ["inventory"], "weekly", "last", "inventory.csv")
    report = generate_period_report(summary)

    assert summary.period_start.isoformat() == "2026-11-02"
    assert summary.period_end.isoformat() == "2026-11-08"
    assert summary.metrics[0].value == 14
    assert summary.metrics[0].previous_value == 9
    assert "经营数据周报" in report


def test_report_without_previous_period_does_not_invent_a_comparison():
    frame = pd.DataFrame({"date": ["2026-11-17"], "production": [42]})

    summary = summarize_period(frame, "date", ["production"], "daily", "sum", "production.csv")
    report = generate_period_report(summary)

    assert summary.metrics[0].previous_value is None
    assert "无对比数据" in report


def test_last_aggregation_uses_latest_date_not_last_csv_row():
    frame = pd.DataFrame({
        "date": ["2026-11-17", "2026-11-16"],
        "inventory": [25, 20],
    })

    summary = summarize_period(frame, "date", ["inventory"], "daily", "last", "inventory.csv")

    assert summary.metrics[0].value == 25


def test_numeric_identifier_is_not_mistaken_for_a_date():
    frame = pd.DataFrame({
        "Table": ["Line productivity"] * 2,
        "Field": ["Date", "Product"],
        "Description": ["Batch production details", "Product ID"],
        "numbers totally": [422111, 422112],
    })

    assert _date_columns(frame) == []
    with pytest.raises(ValueError, match="No valid calendar dates"):
        summarize_period(frame, "numbers totally", ["numbers totally"], "daily", "sum", "dictionary.csv")


def test_visual_report_contains_trends_and_escapes_uploaded_labels():
    frame = pd.DataFrame({
        "date": ["2026-11-16", "2026-11-17"],
        "sales <script>": [10, 15],
    })
    summary = summarize_period(frame, "date", ["sales <script>"], "daily", "sum", "<unsafe>.csv")

    dashboard = generate_period_html(summary)

    assert "<!doctype html>" in dashboard
    assert 'class="trend-plot"' in dashboard
    assert "指标趋势" in dashboard
    assert "&lt;script&gt;" in dashboard
    assert "<script>" not in dashboard


def test_metrics_can_use_different_aggregation_rules():
    frame = pd.DataFrame({
        "date": ["2026-11-16", "2026-11-17", "2026-11-17"],
        "sales": [100, 50, 80],
        "inventory": [30, 32, 31],
        "operator": ["A", "B", "C"],
    })

    summary = summarize_period(
        frame,
        "date",
        ["sales", "inventory"],
        "daily",
        {"sales": "sum", "inventory": "last"},
        "sales-and-stock.csv",
        dimension_columns=["operator"],
    )
    dashboard = generate_period_html(summary)

    assert summary.metrics[0].value == 130
    assert summary.metrics[1].value == 31
    assert "sales · sum" in dashboard
    assert "inventory · last" in dashboard
    assert "operator" in dashboard
    assert "分类分布" in dashboard


def test_recommendations_select_sales_metrics_dimensions_and_aggregation():
    frame = pd.DataFrame({
        "Order ID": [101, 102, 103, 104],
        "Order Date": ["2026-11-16", "2026-11-16", "2026-11-17", "2026-11-17"],
        "Net Sales": [100, 150, 200, 125],
        "Units Sold": [2, 3, 4, 2],
        "Gross Margin %": [0.2, 0.25, 0.22, 0.21],
        "Product Category": ["A", "B", "A", "B"],
        "Channel": ["web", "store", "web", "store"],
        "Customer Name": ["Lee", "Kim", "Pat", "Sam"],
    })

    recommendation = recommend_analysis_setup(frame)
    aggregations = dict(recommendation.metric_aggregations)

    assert recommendation.date_column == "Order Date"
    assert recommendation.period_type == "daily"
    assert set(recommendation.metric_columns) == {"Net Sales", "Units Sold", "Gross Margin %"}
    assert aggregations == {"Net Sales": "sum", "Units Sold": "sum", "Gross Margin %": "mean"}
    assert set(recommendation.dimension_columns) == {"Product Category", "Channel"}
    assert "分类分布" in recommendation.presentation


def test_recommendations_use_latest_date_total_for_stock_snapshots():
    frame = pd.DataFrame({
        "Date": ["2026-11-16", "2026-11-16", "2026-11-17", "2026-11-17"],
        "SKU": ["A", "B", "A", "B"],
        "Stock Quantity": [9, 11, 10, 12],
    })

    recommendation = recommend_analysis_setup(frame)
    summary = summarize_period(
        frame,
        recommendation.date_column,
        list(recommendation.metric_columns),
        "daily",
        dict(recommendation.metric_aggregations),
        "inventory.csv",
    )

    assert dict(recommendation.metric_aggregations)["Stock Quantity"] == "last_sum"
    assert summary.metrics[0].value == 22
    assert summary.metrics[0].previous_value == 20


def test_recommendations_ignore_sparse_factor_columns_and_batch_ids():
    frame = pd.DataFrame({
        "Date": ["2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17"],
        "Batch": [422111, 422112, 422113, 422114],
        "Batch duration (min)": [60, 75, 90, 50],
        "Downtime factor 1": [None, 12, None, None],
        "Total downtime (min)": [5, 12, 0, 4],
        "Operator": ["A", "B", "A", "B"],
    })

    recommendation = recommend_analysis_setup(frame)

    assert recommendation.metric_columns == ("Batch duration (min)", "Total downtime (min)")
    assert dict(recommendation.metric_aggregations) == {
        "Batch duration (min)": "sum",
        "Total downtime (min)": "sum",
    }
    assert recommendation.dimension_columns == ("Operator",)


def test_year_column_generates_annual_report_and_trend():
    frame = pd.DataFrame({
        "Year": [2022, 2022, 2023, 2023],
        "Revenue": [100, 120, 150, 175],
        "Product": ["A", "B", "A", "B"],
    })

    recommendation = recommend_analysis_setup(frame)
    summary = summarize_period(
        frame,
        recommendation.date_column,
        list(recommendation.metric_columns),
        recommendation.period_type,
        dict(recommendation.metric_aggregations),
        "annual.csv",
        list(recommendation.dimension_columns),
    )
    dashboard = generate_period_html(summary)

    assert _date_columns(frame) == ["Year"]
    assert recommendation.period_type == "yearly"
    assert summary.period_start.isoformat() == "2023-01-01"
    assert summary.metrics[0].value == 325
    assert "经营数据年报" in dashboard
    assert "周期对比图" in dashboard


def test_data_without_dates_generates_overall_summary_without_fake_trend():
    frame = pd.DataFrame({
        "Revenue": [100, 200, 300],
        "Product Category": ["A", "B", "A"],
    })

    recommendation = recommend_analysis_setup(frame)
    summary = summarize_period(
        frame,
        date_column=None,
        metric_columns=list(recommendation.metric_columns),
        period_type="overall",
        aggregation=dict(recommendation.metric_aggregations),
        source="without-date.csv",
        dimension_columns=list(recommendation.dimension_columns),
    )
    dashboard = generate_period_html(summary)

    assert recommendation.date_column is None
    assert recommendation.period_type == "overall"
    assert summary.period_start is None
    assert summary.metrics[0].value == 600
    assert "全数据范围" in dashboard
    assert "分类分布" in dashboard
    assert "指标趋势" not in dashboard


def test_dashboard_uses_readable_contrast_for_small_muted_text():
    frame = pd.DataFrame({"date": ["2026-11-16"], "sales": [10]})
    dashboard = generate_period_html(
        summarize_period(frame, "date", ["sales"], "daily", "sum", "sales.csv")
    )
    muted = re.search(r"--muted:(#[0-9a-fA-F]{6})", dashboard)
    axis = re.search(r"\.axis\{[^}]*fill:(#[0-9a-fA-F]{6})", dashboard)

    def contrast_ratio(foreground: str, background: str) -> float:
        def luminance(color: str) -> float:
            channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [
                channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    assert muted is not None
    assert axis is not None
    assert ".kpi-value" in dashboard
    assert "color:#17263d!important" in dashboard
    assert contrast_ratio(muted.group(1), "#ffffff") >= 4.5
    assert contrast_ratio(axis.group(1), "#ffffff") >= 4.5


def test_dashboard_contains_line_donut_and_period_comparison_charts():
    frame = pd.DataFrame({
        "date": ["2026-11-16", "2026-11-17", "2026-11-17"],
        "sales": [100, 50, 80],
        "product": ["A", "B", "A"],
    })
    summary = summarize_period(
        frame, "date", ["sales"], "daily", "sum", "sales.csv", dimension_columns=["product"],
    )

    dashboard = generate_period_html(summary)

    assert 'class="trend-segment"' in dashboard
    assert 'class="donut"' in dashboard
    assert 'class="compare-fill current"' in dashboard
    assert 'class="compare-fill previous"' in dashboard


def test_aggregate_formula_computes_margin_from_period_sums():
    frame = pd.DataFrame({
        "date": ["2026-11-16", "2026-11-16", "2026-11-17"],
        "Revenue": [100, 900, 200],
        "Cost": [50, 900, 160],
    })
    definition = MetricDefinition(
        name="毛利率",
        formula="(SUM([Revenue]) - SUM([Cost])) / SUM([Revenue]) * 100",
        aggregation="formula",
        description="毛利除以收入",
        unit="%",
        direction="higher",
    )

    report = summarize_period(
        frame,
        "date",
        ["毛利率"],
        "daily",
        {"毛利率": "formula"},
        "finance.csv",
        metric_definitions={"毛利率": definition},
    )
    markdown = generate_period_report(report)

    assert report.metrics[0].value == 20
    assert report.metrics[0].previous_value == 5
    assert "毛利除以收入" in markdown
    assert "SUM(\\[Revenue\\]) - SUM(\\[Cost\\])" in markdown


def test_metric_formulas_reject_unknown_fields_and_arbitrary_code():
    with pytest.raises(ValueError, match="不存在的字段"):
        formula_columns("SUM([Missing])", ["Revenue"])
    with pytest.raises(ValueError, match="只支持"):
        formula_columns("__import__('os').system('echo unsafe')", ["Revenue"])
    with pytest.raises(ValueError, match="聚合函数"):
        formula_columns("[Revenue] / SUM([Revenue])", ["Revenue"])


def test_snapshot_sum_uses_latest_value_per_entity():
    frame = pd.DataFrame({
        "Date": [
            "2026-11-16 09:00", "2026-11-16 09:00",
            "2026-11-17 09:00", "2026-11-17 09:00", "2026-11-17 15:00",
        ],
        "Account": ["A", "B", "A", "B", "A"],
        "Balance": [90, 210, 100, 200, 120],
    })
    definition = MetricDefinition(
        name="期末账号余额",
        column="Balance",
        aggregation="last_sum",
        description="各账号最新余额之和",
        unit="元",
        entity_columns=("Account",),
    )

    report = summarize_period(
        frame,
        "Date",
        ["期末账号余额"],
        "daily",
        {"期末账号余额": "last_sum"},
        "balances.csv",
        metric_definitions={"期末账号余额": definition},
    )

    assert report.metrics[0].value == 320
    assert report.metrics[0].previous_value == 300


def test_snapshot_sum_rejects_duplicate_latest_rows_at_the_selected_grain():
    frame = pd.DataFrame({
        "Date": ["2026-11-17 15:00", "2026-11-17 15:00"],
        "Account": ["A", "A"],
        "Balance": [100, 120],
    })
    definition = MetricDefinition(
        name="期末账号余额",
        column="Balance",
        aggregation="last_sum",
        entity_columns=("Account",),
    )

    with pytest.raises(ValueError, match="相同实体粒度"):
        summarize_period(
            frame,
            "Date",
            ["期末账号余额"],
            "daily",
            {"期末账号余额": "last_sum"},
            "balances.csv",
            metric_definitions={"期末账号余额": definition},
        )


def test_anomaly_detection_requires_history_and_flags_robust_outlier():
    dates = pd.date_range("2026-11-10", periods=8).astype(str).tolist()
    frame = pd.DataFrame({"date": dates, "sales": [10, 11, 9, 10, 11, 9, 10, 100]})
    report = summarize_period(frame, "date", ["sales"], "daily", "sum", "sales.csv")
    analysis, _ = generate_period_analysis(report)

    assert len(report.anomalies) == 1
    assert report.anomalies[0].metric_name == "sales"
    assert report.anomalies[0].baseline_periods == 7
    assert "统计异常信号，不代表已找到原因" in analysis

    short_report = summarize_period(
        frame.iloc[-4:], "date", ["sales"], "daily", "sum", "short.csv",
    )
    short_analysis, _ = generate_period_analysis(short_report)
    assert not short_report.anomalies
    assert "历史周期不足 6 个" in short_analysis


def test_sum_driver_breakdown_is_exact_but_does_not_claim_causality():
    frame = pd.DataFrame({
        "date": ["2026-11-16"] * 2 + ["2026-11-17"] * 2,
        "sales": [10, 90, 50, 60],
        "product": ["A", "B", "A", "B"],
    })
    report = summarize_period(
        frame, "date", ["sales"], "daily", "sum", "sales.csv", ["product"],
    )
    analysis, _ = generate_period_analysis(report)
    by_member = {item.member: item for item in report.drivers}

    assert report.metrics[0].value - report.metrics[0].previous_value == 10
    assert by_member["A"].change == 40
    assert by_member["A"].share_of_total_change == 400
    assert by_member["A"].exact_attribution
    assert by_member["B"].change == -30
    assert "非因果证明" in analysis


def test_mean_driver_is_labeled_as_reference_not_exact_attribution():
    frame = pd.DataFrame({
        "date": ["2026-11-16"] * 2 + ["2026-11-17"] * 2,
        "defect_rate": [0.1, 0.3, 0.2, 0.4],
        "line": ["A", "B", "A", "B"],
    })
    report = summarize_period(
        frame,
        "date",
        ["defect_rate"],
        "daily",
        "mean",
        "quality.csv",
        ["line"],
    )

    assert report.drivers
    assert not any(item.exact_attribution for item in report.drivers)
    assert "分类变化参考（不代表精确贡献或因果）" in generate_period_analysis(report)[0]


def test_semantic_model_round_trips_and_offline_followup_uses_defined_metric():
    definition = MetricDefinition(
        name="毛利率",
        formula="(SUM([Revenue]) - SUM([Cost])) / SUM([Revenue]) * 100",
        aggregation="formula",
        description="毛利占收入的比例",
        unit="%",
        direction="higher",
    )
    loaded = metric_definitions_from_json(metric_definitions_to_json([definition]))
    frame = pd.DataFrame({
        "date": ["2026-11-16", "2026-11-17"],
        "Revenue": [100, 200],
        "Cost": [60, 140],
    })
    report = summarize_period(
        frame,
        "date",
        ["毛利率"],
        "daily",
        {"毛利率": "formula"},
        "finance.csv",
        metric_definitions={"毛利率": loaded[0]},
    )

    answer = answer_period_question(report, "毛利率的口径和本期是多少？")

    assert loaded == [definition]
    assert "毛利占收入的比例" in answer
    assert "计算公式为 (SUM([Revenue]) - SUM([Cost])) / SUM([Revenue]) * 100" in answer
    assert "单位为 %" in answer
    assert "当前值为 30" in answer
