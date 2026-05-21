"""Integration test: stage 1 raises a network timeout error.

Task 11.9
"""
from __future__ import annotations

from unittest.mock import MagicMock

import openai

from pa_agent.ai.json_validator import JsonValidator
from pa_agent.ai.router import route_strategy_files
from pa_agent.orchestrator.two_stage import TwoStageOrchestrator
from pa_agent.util.threading import CancelToken, OrchestratorEvent


def test_network_timeout_stage1(frame, pending_writer, assembler, exp_reader):
    """APITimeoutError on stage1 → Stage1Failed emitted."""
    client = MagicMock()
    # openai.APITimeoutError requires a `request` parameter
    client.stream_chat.side_effect = openai.APITimeoutError(request=MagicMock())

    validator = JsonValidator()
    orchestrator = TwoStageOrchestrator(
        client=client,
        assembler=assembler,
        router=route_strategy_files,
        validator=validator,
        pending_writer=pending_writer,
        exp_reader=exp_reader,
    )

    events: list[OrchestratorEvent] = []
    cancel_token = CancelToken()

    orchestrator.submit(
        frame=frame,
        cancel_token=cancel_token,
        on_event=events.append,
    )

    # Stage1Failed event must appear
    assert OrchestratorEvent.Stage1Failed in events

    # Stage2 must never start
    assert OrchestratorEvent.Stage2Started not in events

    # save_partial called with reason "network_error"
    pending_writer.save_partial.assert_called_once()
    call_args = pending_writer.save_partial.call_args
    reason = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("reason", "")
    assert reason == "network_error"
