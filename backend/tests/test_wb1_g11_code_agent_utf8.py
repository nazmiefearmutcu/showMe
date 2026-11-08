"""LOC-1: CodeAgent must run Unicode source regardless of the host locale.

The sandbox used to write the wrapped snippet with the locale codec (cp1254
on tr-TR Windows) while the child interpreter reads source as UTF-8 (PEP
3120). Turkish letters then produced a SyntaxError in the child, and
characters outside cp1254 made the temp-file write raise an uncaught
UnicodeEncodeError. These tests reproduce both on any machine: the snippet
is written and the child is spawned through the real ``CodeAgent.run`` path,
without network access.
"""
from __future__ import annotations

import asyncio

from showme.engine.agents.code import CodeAgent
from showme.engine.core.base_agent import AgentTask


def _run(code: str):
    agent = CodeAgent()
    task = AgentTask(role="code", instruction="", inputs={"code": code})
    return asyncio.run(agent.run(task))


def test_turkish_letters_in_string_literal_run_in_child() -> None:
    """Turkish letters (cp1254 range) must not break the child run."""
    code = 'print("Hisse fiyatı İş ğüşöç")'
    result = _run(code)
    assert result.error is None, result.error
    assert "Hisse fiyatı İş ğüşöç" in result.output["stdout"]
    assert result.output["returncode"] == 0


def test_characters_outside_cp1254_do_not_escape_run() -> None:
    """A non-cp1254 character (U+2192 arrow) must not raise out of run()."""
    code = 'print("sonuç → tamam")'
    result = _run(code)
    assert result.error is None, result.error
    assert "sonuç → tamam" in result.output["stdout"]
    assert result.output["returncode"] == 0
