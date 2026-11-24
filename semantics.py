"""Validated business-metric definitions and safe aggregate formula evaluation."""
from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass
from typing import Callable, Literal

import pandas as pd

Aggregation = Literal["sum", "mean", "max", "min", "last", "last_sum"]
MetricAggregation = Aggregation | Literal["formula"]
MetricDirection = Literal["higher", "lower", "neutral"]


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    description: str = ""
    unit: str = ""
    direction: MetricDirection = "neutral"
    column: str | None = None
    formula: str | None = None
    aggregation: MetricAggregation = "sum"
    entity_columns: tuple[str, ...] = ()


_COLUMN_REFERENCE = re.compile(r"\[([^\]]+)\]")
_AGGREGATIONS = {"SUM", "MEAN", "MAX", "MIN", "LAST", "LAST_SUM"}
_AGGREGATION_METHODS: dict[str, Aggregation] = {
    "SUM": "sum",
    "MEAN": "mean",
    "MAX": "max",
    "MIN": "min",
    "LAST": "last",
    "LAST_SUM": "last_sum",
}
_BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
}


def _compile_formula(formula: str, available_columns: tuple[str, ...]) -> tuple[ast.Expression, dict[str, str]]:
    if not formula or len(formula) > 2_000:
        raise ValueError("计算公式不能为空，且不能超过 2,000 个字符。")

    column_tokens: dict[str, str] = {}

    def replace_column(match: re.Match[str]) -> str:
        column = match.group(1).strip()
        if column not in available_columns:
            raise ValueError(f"公式引用了不存在的字段：{column}")
        token = f"_field_{len(column_tokens)}"
        column_tokens[token] = column
        return token

    source = _COLUMN_REFERENCE.sub(replace_column, formula)
    if "[" in source or "]" in source:
        raise ValueError("字段名必须用方括号引用，例如 SUM([销售额])。")
    try:
        expression = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"公式语法错误：{exc.msg}") from exc

    aggregate_count = 0

    def validate_row_expression(node: ast.AST) -> None:
        if isinstance(node, ast.Name) and node.id in column_tokens:
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            validate_row_expression(node.operand)
            return
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            validate_row_expression(node.left)
            validate_row_expression(node.right)
            return
        raise ValueError("聚合函数内只允许字段引用、数字及 +、-、*、/ 运算。")

    def validate_aggregate_expression(node: ast.AST) -> None:
        nonlocal aggregate_count
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id.upper() not in _AGGREGATIONS:
                raise ValueError("公式只支持 SUM、MEAN、MAX、MIN、LAST 和 LAST_SUM 聚合函数。")
            if len(node.args) != 1 or node.keywords:
                raise ValueError("每个聚合函数只能接收一个表达式。")
            validate_row_expression(node.args[0])
            aggregate_count += 1
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            validate_aggregate_expression(node.operand)
            return
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            validate_aggregate_expression(node.left)
            validate_aggregate_expression(node.right)
            return
        raise ValueError("字段必须放在聚合函数中，例如 SUM([销售额])。")

    validate_aggregate_expression(expression.body)
    if aggregate_count == 0:
        raise ValueError("公式必须至少包含一个聚合函数。")
    return expression, column_tokens


def formula_columns(formula: str, available_columns: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Validate a formula and return its referenced source columns."""
    _, tokens = _compile_formula(formula, tuple(available_columns))
    return tuple(dict.fromkeys(tokens.values()))


def evaluate_metric_formula(
    formula: str,
    frame: pd.DataFrame,
    dates: pd.Series,
    entity_columns: tuple[str, ...],
    aggregate: Callable[[pd.Series, pd.Series, Aggregation, pd.DataFrame | None], float | None],
) -> float | None:
    """Evaluate an aggregate formula without executing arbitrary Python code."""
    expression, tokens = _compile_formula(formula, tuple(map(str, frame.columns)))

    def evaluate_row(node: ast.AST) -> pd.Series:
        if isinstance(node, ast.Name) and node.id in tokens:
            column = tokens[node.id]
            return pd.to_numeric(
                frame[column].astype("string").str.replace(",", "", regex=False).str.strip(),
                errors="coerce",
            )
        if isinstance(node, ast.Constant):
            return pd.Series(float(node.value), index=frame.index, dtype="float64")
        if isinstance(node, ast.UnaryOp):
            values = evaluate_row(node.operand)
            return values if isinstance(node.op, ast.UAdd) else -values
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate_row(node.left)
            right = evaluate_row(node.right)
            result = _BINARY_OPERATORS[type(node.op)](left, right)
            return result.replace([math.inf, -math.inf], float("nan"))
        raise ValueError("Unsupported expression in metric formula.")

    def evaluate_aggregate(node: ast.AST) -> float | None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            method = _AGGREGATION_METHODS[node.func.id.upper()]
            values = evaluate_row(node.args[0])
            keys = frame.loc[:, list(entity_columns)] if entity_columns else None
            return aggregate(values, dates, method, keys)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.UnaryOp):
            value = evaluate_aggregate(node.operand)
            if value is None:
                return None
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate_aggregate(node.left)
            right = evaluate_aggregate(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Div) and right == 0:
                return None
            return _BINARY_OPERATORS[type(node.op)](left, right)
        raise ValueError("Unsupported expression in metric formula.")

    result = evaluate_aggregate(expression.body)
    if result is None or not math.isfinite(result):
        return None
    return float(result)


def metric_definitions_to_json(definitions: list[MetricDefinition]) -> str:
    """Serialize only metric metadata; uploaded data is never included."""
    return json.dumps(
        {
            "schema_version": 1,
            "metrics": [
                {
                    "name": item.name,
                    "description": item.description,
                    "unit": item.unit,
                    "direction": item.direction,
                    "column": item.column,
                    "formula": item.formula,
                    "aggregation": item.aggregation,
                    "entity_columns": list(item.entity_columns),
                }
                for item in definitions
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def metric_definitions_from_json(payload: bytes | str) -> list[MetricDefinition]:
    """Load a versioned semantic model from a local JSON file."""
    if isinstance(payload, bytes):
        if len(payload) > 1_000_000:
            raise ValueError("业务指标模型文件不能超过 1 MB。")
        try:
            payload = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("业务指标模型必须使用 UTF-8 编码。") from exc
    if len(payload.encode("utf-8")) > 1_000_000:
        raise ValueError("业务指标模型文件不能超过 1 MB。")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"业务指标模型 JSON 无效：{exc.msg}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("不支持的业务指标模型格式版本。")
    items = data.get("metrics")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise ValueError("业务指标模型必须包含 1 到 100 个指标。")

    definitions = []
    seen_names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("业务指标模型中的每个指标都必须是 JSON 对象。")
        name = item.get("name")
        column = item.get("column")
        formula = item.get("formula")
        description = item.get("description", "")
        unit = item.get("unit", "")
        direction = item.get("direction", "neutral")
        aggregation = item.get("aggregation", "sum")
        entity_columns = item.get("entity_columns", [])
        if not isinstance(name, str) or not name.strip():
            raise ValueError("每个业务指标都必须有非空名称。")
        name = name.strip()
        if name in seen_names:
            raise ValueError(f"业务指标名称重复：{name}")
        if not isinstance(description, str) or not isinstance(unit, str):
            raise ValueError(f"指标“{name}”的定义和单位必须是文本。")
        if direction not in ("higher", "lower", "neutral"):
            raise ValueError(f"指标“{name}”的方向必须是 higher、lower 或 neutral。")
        if not isinstance(entity_columns, list) or not all(isinstance(value, str) for value in entity_columns):
            raise ValueError(f"指标“{name}”的实体粒度字段必须是文本数组。")
        if formula is not None:
            if not isinstance(formula, str) or not formula.strip() or column is not None:
                raise ValueError(f"指标“{name}”必须只设置公式，不能同时设置源字段。")
            if aggregation != "formula":
                raise ValueError(f"公式指标“{name}”的 aggregation 必须为 formula。")
        else:
            if not isinstance(column, str) or not column:
                raise ValueError(f"指标“{name}”必须指定源字段或公式。")
            if aggregation not in ("sum", "mean", "max", "min", "last", "last_sum"):
                raise ValueError(f"指标“{name}”的聚合方式无效。")
        seen_names.add(name)
        definitions.append(MetricDefinition(
            name=name,
            description=description.strip(),
            unit=unit.strip(),
            direction=direction,
            column=column,
            formula=formula.strip() if isinstance(formula, str) else None,
            aggregation=aggregation,
            entity_columns=tuple(dict.fromkeys(entity_columns)),
        ))
    return definitions
