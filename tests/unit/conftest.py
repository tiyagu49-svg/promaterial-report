import pytest

from mas_platform.llm import LLMResponse, ToolCall
from mas_platform.settings import load_settings


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    s.runtime.root_dir = str(tmp_path / "runtime")
    s.llm.provider = "mock"
    return s


def call(name, **args):
    return LLMResponse(content="", tool_calls=[ToolCall(id=f"c_{name}", name=name, arguments=args)])
