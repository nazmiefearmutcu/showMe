"""Code Agent — sandbox-isolated Python evaluation.

Phase 7: subprocess + timeout (Pyodide alternatif). Bu sürüm subprocess.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from src.core.base_agent import AgentResult, AgentTask, BaseAgent


class CodeAgent(BaseAgent):
    name = "code"
    description = "Runs short Python snippets in a subprocess with timeout."

    def __init__(self, deps: Any | None = None) -> None:
        super().__init__(deps)
        self.timeout = 10  # seconds

    async def run(self, task: AgentTask) -> AgentResult:
        code = task.inputs.get("code") or task.instruction
        if not code:
            return AgentResult(agent=self.name, task=task, error="no code")
        wrapped = textwrap.dedent("""
            import json, sys
            try:
        """) + textwrap.indent(textwrap.dedent(code), "    ") + textwrap.dedent("""
            except Exception as e:
                print(json.dumps({"error": str(e)}))
        """)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".py") as f:
            f.write(wrapped)
            f.flush()
            path = f.name
        try:
            r = subprocess.run(
                [sys.executable, path], capture_output=True, text=True, timeout=self.timeout
            )
            return AgentResult(agent=self.name, task=task,
                                output={"stdout": r.stdout, "stderr": r.stderr,
                                        "returncode": r.returncode})
        except subprocess.TimeoutExpired:
            return AgentResult(agent=self.name, task=task, error="timeout")
        finally:
            Path(path).unlink(missing_ok=True)
