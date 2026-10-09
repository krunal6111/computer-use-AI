import os
import sys

from agent.config import (
    GEMINI_DEFAULT_THINKING,
    GEMINI_THINKING,
    KEEP_SCREENSHOTS,
    REQUEST_TIMEOUT,
    RETRYABLE_STATUS,
)
from agent.prompts import SYSTEM_PROMPT
from agent.retry import RetryNow, _is_network_error, _status
from agent.tool_types import ToolCall

OPEN_URL_SCHEMA = {"type": "object", "properties": {"url": {"type": "string"}},
                   "required": ["url"]}


class GeminiBackend:
    """Gemini with the built-in Computer Use tool (desktop environment)."""

    def __init__(self, model, screen_w, screen_h, fallbacks=(), thinking=None):
        from google import genai
        from google.genai import types

        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            sys.exit("Set GEMINI_API_KEY in .env first.")
        self.t = types
        self.models = [model] + [m for m in fallbacks if m != model]
        self.current = 0
        self.thinking = thinking
        # The SDK otherwise retries 5x with up to 60s waits on its own, on top of
        # with_retries(); one retry layer that can switch models is much faster.
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT * 1000,
            retry_options=types.HttpRetryOptions(attempts=1)))
        self.system = SYSTEM_PROMPT.format(width=screen_w, height=screen_h)
        self.contents = []

    @property
    def model(self):
        return self.models[self.current]

    def _config(self, model):
        t = self.t
        level = self.thinking or GEMINI_THINKING.get(model, GEMINI_DEFAULT_THINKING)
        return t.GenerateContentConfig(
            system_instruction=self.system,
            tools=[
                t.Tool(computer_use=t.ComputerUse(
                    environment=t.Environment.ENVIRONMENT_DESKTOP)),
                # Desktop mode has no `navigate` action (only browser mode does),
                # so without this the model launches Chrome by hand: 4+ slow steps.
                t.Tool(function_declarations=[t.FunctionDeclaration(
                    name="open_url",
                    description="Open a URL in the default web browser (Google Chrome). "
                                "Fastest way to open any website or search results page.",
                    parameters_json_schema=OPEN_URL_SCHEMA,
                )]),
            ],
            thinking_config=t.ThinkingConfig(thinking_level=level.upper()),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )

    def begin(self, task, screenshot):
        t = self.t
        self.contents = [t.Content(role="user", parts=[
            t.Part(text=task),
            t.Part.from_bytes(data=screenshot, mime_type="image/jpeg"),
        ])]

    def _generate(self):
        model = self.model
        try:
            return self.client.models.generate_content(
                model=model, contents=self.contents, config=self._config(model))
        except Exception as e:
            status = _status(e)
            if status == 400 and self.current != 0:
                # A fallback model that can't take over this conversation (or this
                # config). Drop it and go back to the main model.
                print(f"   ... {model} can't continue this task, going back to {self.models[0]}")
                self.models.pop(self.current)
                self.current = 0
                raise RetryNow(str(e)) from e
            if len(self.models) > 1 and (status in RETRYABLE_STATUS or _is_network_error(e)):
                self.current = (self.current + 1) % len(self.models)
                print(f"   ... {model} is busy ({status or type(e).__name__}), "
                      f"switching to {self.model}")
                if self.current != 0:
                    raise RetryNow(str(e)) from e  # a different model: no need to wait
            raise  # every model tried: back off before starting over

    def next_actions(self):
        resp = self._generate()
        if not resp.candidates or not resp.candidates[0].content:
            return "(the model returned an empty response)", []
        content = resp.candidates[0].content
        self.contents.append(content)  # keep as-is: carries thought signatures

        text = " ".join(p.text for p in content.parts or [] if p.text).strip()
        calls = []
        for p in content.parts or []:
            fc = p.function_call
            if not fc:
                continue
            args = dict(fc.args or {})
            safety = args.pop("safety_decision", None) or {}
            calls.append(ToolCall(
                id=fc.id, name=fc.name, args=args,
                intent=args.pop("intent", ""),
                needs_confirmation=(safety.get("explanation") or "yes")
                if safety.get("decision") == "require_confirmation" else "",
            ))
        return text, calls

    def add_results(self, results):
        t = self.t
        parts = []
        for r in results:
            response = {"error": r.output} if r.error else {"output": r.output}
            if r.acknowledged:
                response["safety_acknowledgement"] = "true"
            parts.append(t.Part(function_response=t.FunctionResponse(
                id=r.call.id, name=r.call.name, response=response,
                parts=[t.FunctionResponsePart(inline_data=t.FunctionResponseBlob(
                    mime_type="image/jpeg", data=r.screenshot))],
            )))
        self.contents.append(t.Content(role="user", parts=parts))
        self._trim()

    def _trim(self):
        """Drop all but the newest KEEP_SCREENSHOTS images from history."""
        seen = 0
        for content in reversed(self.contents):
            if content.role != "user":
                continue
            for p in content.parts:
                fr = p.function_response
                if fr and fr.parts:
                    seen += 1
                    if seen > KEEP_SCREENSHOTS:
                        fr.parts = None
                elif p.inline_data:
                    seen += 1
                    if seen > KEEP_SCREENSHOTS:
                        p.inline_data = None
                        p.text = "[older screenshot removed]"
