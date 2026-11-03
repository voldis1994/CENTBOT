"""Programming task executor — sandboxed; no baked-in demo solutions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor
from centbot.sandbox.isolated import run_python_isolated


class ProgrammingExecutor(Executor):
    category = "programming"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        solution = workdir / "solution.py"
        tests = workdir / "test_solution.py"
        runner_script = workdir / "run.py"

        # Prefer explicit solution; otherwise attempt to run provided run.py / tests only
        if not solution.exists() and not runner_script.exists() and not tests.exists():
            # If description contains a fenced python block, materialize it
            desc = str(task.get("description") or "")
            code = _extract_python_fence(desc)
            if code:
                solution.write_text(code, encoding="utf-8")
            else:
                return ExecutionResult(
                    ok=False,
                    category=self.category,
                    error="missing_input:solution.py|run.py|test_solution.py (no demo fallback)",
                )

        if tests.exists():
            runner = workdir / "_run_tests.py"
            # Discover test_* callables without assuming a specific demo name
            runner.write_text(
                "import importlib.util, sys\n"
                "from pathlib import Path\n"
                "p = Path('test_solution.py')\n"
                "spec = importlib.util.spec_from_file_location('test_solution', p)\n"
                "mod = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(mod)\n"
                "ran = 0\n"
                "for name in dir(mod):\n"
                "    if name.startswith('test_') and callable(getattr(mod, name)):\n"
                "        getattr(mod, name)(); ran += 1\n"
                "assert ran > 0, 'no tests found'\n"
                "print('OK', ran)\n",
                encoding="utf-8",
            )
            result = run_python_isolated(script_path=runner, workdir=workdir, timeout=60)
        elif runner_script.exists():
            result = run_python_isolated(script_path=runner_script, workdir=workdir, timeout=60)
        else:
            result = run_python_isolated(script_path=solution, workdir=workdir, timeout=60)

        ok = result.get("returncode", 1) == 0
        artifacts = [str(p) for p in (solution, tests, runner_script) if p.exists()]
        return ExecutionResult(
            ok=ok,
            category=self.category,
            output=result,
            artifacts=artifacts,
            error=None if ok else result.get("stderr") or result.get("error") or "tests_failed",
        )


def _extract_python_fence(text: str) -> str | None:
    import re

    m = re.search(r"```(?:python|py)\s*([\s\S]*?)```", text, re.I)
    if not m:
        return None
    code = m.group(1).strip()
    return code or None
