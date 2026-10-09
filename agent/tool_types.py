from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    intent: str = ""
    needs_confirmation: str = ""  # explanation, when the model asks for it
    raw: object = field(default=None, repr=False)


@dataclass
class ToolResult:
    call: ToolCall
    output: str
    screenshot: bytes
    acknowledged: bool = False
    error: bool = False
