"""Code Agent — sandbox-isolated Python evaluation.

Phase 7: subprocess + timeout (Pyodide alternatif). Bu surum subprocess.

QA-fix (RCE-as-feature): this agent runs user-supplied Python in a child
process. Pre-flight static analysis rejects scripts that import or call
dangerous modules/functions BEFORE we spawn the interpreter:

* AST-walk refuses dangerous imports and calls (filesystem, network,
  process-control) and dotted-access escape patterns.
* Per-call CWD is a fresh tempfile.mkdtemp directory we delete on
  return so file artifacts produced by the script cannot leak out.

This is NOT a full sandbox. seccomp / namespaces / Pyodide would
provide stronger isolation; documented as a residual risk so operators
know to keep the agent gated behind the authenticated FastAPI layer.
"""

from __future__ import annotations

import ast
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from showme.engine.core.base_agent import AgentResult, AgentTask, BaseAgent

LOG = logging.getLogger("showme.engine.agents.code")

# Modules that grant filesystem, network, or process-control primitives.
# Blocking them at the import stage stops the bulk of trivial escapes.
_FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "os",
    "subprocess",
    "shutil",
    "socket",
    "asyncio.subprocess",
    "pathlib",
    "ctypes",
    "ctypes.util",
    "importlib",
    "importlib.util",
    "multiprocessing",
    "fcntl",
    "pty",
    "pwd",
    "signal",
    "sys",
    "platform",
    "resource",
    "select",
    "threading",
    "urllib",
    "urllib.request",
    "urllib.parse",
    "http.client",
    "http.server",
    "requests",
    "httpx",
    "telnetlib",
    "smtplib",
    "ftplib",
    "ssl",
})

# Builtins that turn opaque payloads into executable code or escape the
# sandbox. ``open`` is blocked regardless of mode because allowing arbitrary
# file reads is also a leak vector.
_FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "memoryview",
    "open",
})


class _SandboxViolation(ValueError):
    """Raised by ``_validate_code`` when the script is unsafe to execute."""


def _validate_code(code: str) -> None:
    """Reject scripts containing dangerous imports/calls/literals.

    Raises ``_SandboxViolation`` describing the first offending node so the
    caller can return a clear ``error`` payload instead of executing the
    snippet.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        # Refuse rather than letting the subprocess silently print a
        # syntax error — keeps the contract uniform.
        raise _SandboxViolation(f"syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name in _FORBIDDEN_MODULES or root in _FORBIDDEN_MODULES:
                    raise _SandboxViolation(f"forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if (node.module or "") in _FORBIDDEN_MODULES or mod in _FORBIDDEN_MODULES:
                raise _SandboxViolation(f"forbidden import-from: {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _FORBIDDEN_CALLS:
                raise _SandboxViolation(f"forbidden call: {name}(...)")
        elif isinstance(node, ast.Attribute):
            # Block dotted access (e.g. dangerous_mod.dangerous_attr) even
            # when the import was masked behind a dynamic mechanism that
            # somehow slipped past the import-walk.
            attr_chain: list[str] = []
            cursor: ast.AST = node
            while isinstance(cursor, ast.Attribute):
                attr_chain.append(cursor.attr)
                cursor = cursor.value  # type: ignore[assignment]
            if isinstance(cursor, ast.Name):
                attr_chain.append(cursor.id)
            dotted = ".".join(reversed(attr_chain))
            for forbidden in _FORBIDDEN_MODULES:
                if dotted.startswith(forbidden + "."):
                    raise _SandboxViolation(f"forbidden attribute: {dotted}")


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
        # QA-fix: AST allowlist — bail out before spawning the interpreter
        # if the script contains a dangerous import or call.
        try:
            _validate_code(code)
        except _SandboxViolation as exc:
            LOG.warning("CodeAgent refused unsafe snippet: %s", exc)
            return AgentResult(
                agent=self.name,
                task=task,
                error=f"sandbox: {exc}",
                output={"refused": True, "reason": str(exc)},
            )
        wrapped = textwrap.dedent("""
            import json, sys
            try:
        """) + textwrap.indent(textwrap.dedent(code), "    ") + textwrap.dedent("""
            except Exception as e:
                print(json.dumps({"error": str(e)}))
        """)
        # QA-fix: per-call temp dir as CWD so any artifact the script
        # produces lands in an isolated directory we delete on exit.
        sandbox_root = Path(tempfile.mkdtemp(prefix="showme-code-"))
        try:
            with tempfile.NamedTemporaryFile(
                "w", delete=False, suffix=".py", dir=str(sandbox_root)
            ) as f:
                f.write(wrapped)
                f.flush()
                path = f.name
            try:
                r = subprocess.run(
                    [sys.executable, path],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=str(sandbox_root),
                    env={"PATH": os.environ.get("PATH", "")},
                )
                return AgentResult(
                    agent=self.name,
                    task=task,
                    output={
                        "stdout": r.stdout,
                        "stderr": r.stderr,
                        "returncode": r.returncode,
                    },
                )
            except subprocess.TimeoutExpired:
                return AgentResult(agent=self.name, task=task, error="timeout")
        finally:
            # Best-effort cleanup; never raise from the finally block.
            shutil.rmtree(sandbox_root, ignore_errors=True)
