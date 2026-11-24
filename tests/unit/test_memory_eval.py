"""Memory/evolution + evaluation tests (GU Tianyang). Offline, MockLLMClient."""
import json

from conftest import call
from mas_platform.evaluation.metrics import compute_metrics
from mas_platform.evaluation.runner import run_suite
from mas_platform.llm import LLMResponse, MockLLMClient
from mas_platform.memory import JsonMemoryStore, MemoryRecord, retrieve


def _rec(goal, lesson, success=True):
    return MemoryRecord(agent_id="a", task_goal=goal, success=success, summary="", lesson=lesson, tags=[])


def test_dedupe_and_mark_used(tmp_path):
    s = JsonMemoryStore("a", tmp_path / "m.jsonl")
    s.add(_rec("write python script", "run the script after writing it to verify output"))
    s.add(_rec("write python code", "run the script after writing it to verify the output"))
    assert len(s.all()) == 1 and s.all()[0].seen == 2
    rid = s.all()[0].id
    s.mark_used([rid], success=True)
    r = s.all()[0]
    assert r.uses == 1 and r.helped == 1 and r.usefulness > 0.5


def test_retrieval_prefers_relevant(tmp_path):
    s = JsonMemoryStore("a", tmp_path / "m.jsonl")
    s.add(_rec("search the web for facts", "use fetch_url on the top search result"))
    s.add(_rec("write pytest tests", "name test files test_*.py so pytest collects them"))
    top = retrieve(s, "write unit tests with pytest", k=1)
    assert top and "pytest" in top[0].lesson


def test_playbook(tmp_path):
    s = JsonMemoryStore("a", tmp_path / "m.jsonl")
    s.add(_rec("x", "always verify files", True))
    s.add(_rec("y", "do not guess file names", False))
    text = s.consolidate().read_text()
    assert "What works" in text and "Pitfalls" in text


def test_metrics():
    m = compute_metrics([
        {"id": "a", "passed": True, "duration_s": 2, "subtasks_total": 2, "subtasks_succeeded": 2, "checks": []},
        {"id": "b", "passed": False, "crashed": True, "duration_s": 4, "subtasks_total": 1, "subtasks_succeeded": 0, "checks": []},
    ])
    assert m["goal_completion_rate"] == 50.0 and m["crash_rate"] == 50.0 and m["time_mean_s"] == 3.0


def test_run_suite_end_to_end(settings, tmp_path):
    tasks = tmp_path / "t.jsonl"
    tasks.write_text(json.dumps({"id": "t1", "mode": "@writer", "goal": "make a.md",
                                 "checks": [{"type": "file_contains", "path": "a.md", "text": "hi"}]}) + "\n")

    def script(messages, tools):
        if tools is None:
            return LLMResponse(content='{"summary":"s","lesson":"write then verify","tags":["file"]}')
        if not any(m["role"] == "tool" for m in messages):
            return call("write_file", path="a.md", content="hi")
        return call("finish", answer="done", success=True)

    out = run_suite(tasks, settings=settings, llm=MockLLMClient(script), out_dir=tmp_path / "res", verbose=False)
    assert out["metrics"]["goal_completion_rate"] == 100.0
    assert "Goal completion rate" in (tmp_path / "res" / "report.md").read_text()
