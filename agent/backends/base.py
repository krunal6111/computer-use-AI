from typing import Protocol

from agent.tool_types import ToolCall, ToolResult


class Backend(Protocol):
    model: str

    def begin(self, task: str, screenshot: bytes) -> None: ...
    def next_actions(self) -> tuple[str, list[ToolCall]]: ...
    def add_results(self, results: list[ToolResult]) -> None: ...
