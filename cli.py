"""Minimal CLI.

    mas chat                       # group chat with all agents (type a goal, or "@coder ...")
    mas chat --dm coder            # private 1-on-1 chat with one agent
    mas run "goal text"            # run one goal non-interactively and print the report
    mas agents                     # list agents
    mas eval evaluation/dev_tasks/dev.jsonl [--limit 3] [--no-memory]   # run the evaluation harness
    mas trace [run_id|last]        # Markdown timeline of a run (for reports)

Inside chat: /dm <agent>, /group, /agents, /quit
"""
from __future__ import annotations

import argparse
import json
import sys

from .app import build_platform
from .core.schemas import Message, MessageKind

COLORS = {"human": "\033[96m", "system": "\033[90m"}
RESET = "\033[0m"


def _printer(msg: Message) -> None:
    if msg.sender == "human":
        return
    dim = msg.kind in (MessageKind.SYSTEM, MessageKind.TASK_ASSIGN)
    color = "\033[90m" if dim else "\033[93m"
    text = msg.content if len(msg.content) < 1500 else msg.content[:1500] + " ..."
    print(f"{color}[{msg.channel}] {msg.sender}: {text}{RESET}")


def cmd_chat(args) -> None:
    p = build_platform(human_mode=args.human)
    p.bus.subscribe("*", _printer)
    dm = args.dm
    print(f"Agents: {', '.join(p.registry.ids())}.  Commands: /dm <agent>, /group, /agents, /quit")
    while True:
        try:
            line = input(f"\n{'dm:' + dm if dm else 'group'}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/quit", "/exit"):
            break
        if line == "/agents":
            print(p.registry.roster_text())
            continue
        if line == "/group":
            dm = None
            continue
        if line.startswith("/dm"):
            parts = line.split()
            if len(parts) == 2 and p.registry.has(parts[1]):
                dm = parts[1]
            else:
                print("usage: /dm <agent_id>")
            continue
        if dm:
            p.registry.get(dm).chat(line)
        else:
            result = p.handle_group_message(line)
            if hasattr(result, "subtasks_total"):
                print(f"\n✔ run {result.run_id}: success={result.success} "
                      f"({result.subtasks_succeeded}/{result.subtasks_total} sub-tasks) in {result.duration_s:.1f}s")


def cmd_run(args) -> None:
    p = build_platform(human_mode=args.human)
    if not args.quiet:
        p.bus.subscribe("*", _printer)
    report = p.controller.run_goal(args.goal)
    print(json.dumps(report.model_dump(exclude={"tasks"}), indent=2, ensure_ascii=False))


def cmd_agents(args) -> None:
    p = build_platform(human_mode="auto_approve")
    print(p.registry.roster_text())


def cmd_eval(args) -> None:
    from .evaluation.runner import run_suite
    summary = run_suite(args.tasks_file, limit=args.limit, memory=not args.no_memory,
                        only=args.only, verbose=not args.quiet)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


def cmd_trace(args) -> None:
    from .core.trace import export_trace
    from .settings import load_settings
    md = export_trace(load_settings().runtime_path, args.run_id)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(md)
        print(f"wrote {args.out}")
    else:
        print(md)


def cmd_daily_report(args) -> None:
    from pathlib import Path

    from .llm import LLMResponse, MockLLMClient, make_llm_client
    from .reports.daily import generate_daily_report, load_demo_data
    from .settings import load_settings

    settings = load_settings()
    data = load_demo_data(args.data)
    llm = (
        MockLLMClient([LLMResponse(content=(
            "### 整体概览\n"
            "本报告使用内置合成样例数据，仅用于演示日报生成流程。\n\n"
            "### 重点变化\n"
            "请查看上方指标表中的当日值及与前一日的程序计算结果。\n\n"
            "### 建议关注\n"
            "结合业务背景核实变化原因；样例数据不代表真实经营结论。"
        ))])
        if args.offline else make_llm_client(settings.llm)
    )
    markdown = generate_daily_report(
        data,
        llm,
        analysis_title="演示分析（离线）" if args.offline else "AI 分析",
    )
    output = Path(args.out) if args.out else (
        settings.runtime_path / "reports" / f"daily-report-{data.report_date.isoformat()}.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"日报已生成：{output}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="mas", description="Multi-agent collaboration platform")
    ap.add_argument("--human", choices=["cli", "auto_approve"], default=None,
                    help="How HITL questions/approvals are answered (default from configs/system.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chat")
    c.add_argument("--dm", default=None, help="agent id for a private chat")
    c.set_defaults(fn=cmd_chat)

    r = sub.add_parser("run")
    r.add_argument("goal")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(fn=cmd_run)

    a = sub.add_parser("agents")
    a.set_defaults(fn=cmd_agents)

    e = sub.add_parser("eval", help="run an evaluation task file (JSONL)")
    e.add_argument("tasks_file")
    e.add_argument("--limit", type=int, default=None, help="only run the first N tasks")
    e.add_argument("--only", default=None, help="comma-separated task ids to run")
    e.add_argument("--no-memory", action="store_true", help="disable agent memory (ablation)")
    e.add_argument("--quiet", action="store_true")
    e.set_defaults(fn=cmd_eval)

    t = sub.add_parser("trace", help="export a run as a Markdown timeline")
    t.add_argument("run_id", nargs="?", default="last")
    t.add_argument("--out", default=None)
    t.set_defaults(fn=cmd_trace)

    d = sub.add_parser("daily-report", help="generate a daily report from the synthetic demo dataset")
    d.add_argument("--data", default=None, help="JSON input data (defaults to the checked-in demo fixture)")
    d.add_argument("--out", default=None, help="output Markdown path (defaults to runtime/reports/)")
    d.add_argument("--offline", action="store_true", help="generate without calling an LLM API")
    d.set_defaults(fn=cmd_daily_report)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main(sys.argv[1:])
