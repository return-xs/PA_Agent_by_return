"""Cursor SDK-backed client for PA Agent.

Implements the same interface as :class:`pa_agent.ai.deepseek_client.DeepSeekClient`
for orchestrators: ``stream_chat()`` and ``update_provider()``.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from typing import Any, Callable

from pa_agent.ai.cursor_connector import resolve_cursor_sdk_model_id
from pa_agent.ai.deepseek_client import AIReply, AIUsage
from pa_agent.config.settings import AIProviderSettings

logger = logging.getLogger(__name__)

_PATCHED_CURSOR_SDK_BRIDGE = False


def _patch_cursor_sdk_bridge_windows() -> None:
    """Patch cursor_sdk bridge discovery on Windows.

    cursor-sdk v0.1.x uses selectors.DefaultSelector() to wait on the bridge
    subprocess stderr fd. On Windows, select() only supports sockets, so waiting
    on a pipe fd can raise WinError 10038.

    We replace the discovery reader with a thread + queue approach.
    """
    global _PATCHED_CURSOR_SDK_BRIDGE  # noqa: PLW0603
    if _PATCHED_CURSOR_SDK_BRIDGE:
        return
    if sys.platform != "win32":
        _PATCHED_CURSOR_SDK_BRIDGE = True
        return

    try:
        import cursor_sdk._bridge as bridge_mod  # type: ignore
        from cursor_sdk.errors import CursorSDKError  # type: ignore
    except Exception:
        # If cursor_sdk can't import, we'll fail later with a clearer message.
        return

    ready_prefix = getattr(bridge_mod, "READY_LINE_PREFIX", "cursor-sdk-bridge ready ")
    parse_line = getattr(bridge_mod, "parse_discovery_line", None)
    if parse_line is None:
        return

    def _read_discovery_threaded(process: Any, timeout: float) -> Any:
        if process.stderr is None:
            raise CursorSDKError("Bridge process stderr is unavailable")

        q: "queue.Queue[str | None]" = queue.Queue()

        def _reader() -> None:
            try:
                # readline() blocks, which is fine in a dedicated thread
                while True:
                    line = process.stderr.readline()
                    if not line:
                        q.put(None)
                        return
                    q.put(line)
            except Exception:
                q.put(None)

        t = threading.Thread(target=_reader, name="cursor_sdk_bridge_stderr", daemon=True)
        t.start()

        deadline = time.monotonic() + timeout
        stderr_lines: list[str] = []
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                line = q.get(timeout=min(0.2, remaining))
            except queue.Empty:
                exit_code = process.poll()
                if exit_code is not None:
                    raise CursorSDKError(
                        f"Bridge exited before discovery with status {exit_code}: "
                        + "".join(stderr_lines)
                    )
                continue

            if line is None:
                exit_code = process.poll()
                if exit_code is not None:
                    raise CursorSDKError(
                        f"Bridge exited before discovery with status {exit_code}: "
                        + "".join(stderr_lines)
                    )
                continue

            stderr_lines.append(line)
            if line.startswith(ready_prefix):
                discovery = parse_line(line)
                if discovery is not None:
                    return discovery

        raise CursorSDKError("Timed out waiting for bridge discovery")

    bridge_mod._read_discovery = _read_discovery_threaded  # type: ignore[attr-defined]
    _PATCHED_CURSOR_SDK_BRIDGE = True


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten OpenAI-style messages into a single prompt string for Cursor Agent."""
    parts: list[str] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = m.get("content", "")
        if isinstance(content, list):
            # Keep minimal compatibility (text blocks).
            text_chunks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_chunks.append(str(block.get("text", "")))
            content = "\n".join(text_chunks)
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts).strip()


class CursorSdkClient:
    """Cursor SDK wrapper (one-shot prompt per call)."""

    def __init__(self, settings: AIProviderSettings, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._log = logger_ or logger

    def update_provider(self, settings: AIProviderSettings) -> None:
        self._settings = settings

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        on_reasoning_token: Callable[[str], None] | None = None,
        on_content_token: Callable[[str], None] | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        cancel_token: Any | None = None,
        timeout_s: float = 600.0,
    ) -> AIReply:
        """Send a one-shot prompt to Cursor and return an AIReply.

        Cursor SDK doesn't expose DeepSeek-style reasoning/content token splits in
        a stable way; we stream only final text (single chunk) for now.
        """
        del on_reasoning_token, thinking, reasoning_effort, cancel_token

        try:
            _patch_cursor_sdk_bridge_windows()
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "cursor-sdk 未安装或导入失败。请先安装依赖：pip install cursor-sdk"
            ) from exc

        prompt = _messages_to_prompt(messages)
        model_id = resolve_cursor_sdk_model_id(self._settings.model)

        self._log.info("CursorSdkClient.stream_chat: model_id=%s chars=%d", model_id, len(prompt))

        t0 = time.monotonic()
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=self._settings.api_key,
                model=model_id,
                # Use repo root; Cursor SDK local runtime reads from cwd.
                local=LocalAgentOptions(cwd=os.getcwd()),
            ),
        )
        latency_ms = (time.monotonic() - t0) * 1000

        text = getattr(result, "result", None)
        if text is None:
            text = str(result)

        if on_content_token is not None:
            on_content_token(str(text))

        # Cursor SDK doesn't currently provide OpenAI-usage fields compatible with AIUsage.
        usage = AIUsage(prompt_tokens=0, cached_prompt_tokens=0, completion_tokens=0, total_tokens=0)

        return AIReply(
            content=str(text),
            reasoning_content="",
            raw={"status": getattr(result, "status", None), "model": model_id, "latency_ms": latency_ms},
            usage=usage,
            request_id=getattr(result, "id", "") or "",
            latency_ms=latency_ms,
        )

