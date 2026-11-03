"""Programming task executor (sandboxed Python snippets)."""

from __future__ import annotations

import textwrap
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
        if not solution.exists():
            solution.write_text(
                textwrap.dedent(
                    '''\
                    def merge_sorted(a, b):
                        i = j = 0
                        out = []
                        while i < len(a) and j < len(b):
                            if a[i] <= b[j]:
                                out.append(a[i]); i += 1
                            else:
                                out.append(b[j]); j += 1
                        out.extend(a[i:])
                        out.extend(b[j:])
                        return out
                    '''
                ),
                encoding="utf-8",
            )
        if not tests.exists():
            tests.write_text(
                textwrap.dedent(
                    '''\
                    from solution import merge_sorted

                    def test_merge():
                        assert merge_sorted([1, 3], [2, 4]) == [1, 2, 3, 4]
                        assert merge_sorted([], [1]) == [1]
                        assert merge_sorted([1], []) == [1]
                    '''
                ),
                encoding="utf-8",
            )
        runner = workdir / "_run_tests.py"
        runner.write_text(
            "from test_solution import test_merge\n"
            "test_merge()\n"
            "print('OK')\n",
            encoding="utf-8",
        )
        result = run_python_isolated(script_path=runner, workdir=workdir, timeout=30)
        ok = result.get("returncode", 1) == 0
        return ExecutionResult(
            ok=ok,
            category=self.category,
            output=result,
            artifacts=[str(solution), str(tests)],
            error=None if ok else result.get("stderr") or "tests_failed",
        )
