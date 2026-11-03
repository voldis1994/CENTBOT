"""Programming task executor — generates solutions and runs them in the sandbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.ai.ollama_client import OllamaClient
from centbot.executors.base import ExecutionResult, Executor
from centbot.executors.codegen import generate_solution
from centbot.sandbox.isolated import run_python_isolated


class ProgrammingExecutor(Executor):
    category = "programming"

    def __init__(self, ollama: OllamaClient | None = None):
        self.ollama = ollama

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        solution = workdir / "solution.py"
        tests = workdir / "test_solution.py"
        runner_script = workdir / "run.py"

        gen_meta: dict[str, Any] = {"ok": True, "source": "provided"}
        if not solution.exists() and not runner_script.exists():
            gen_meta = generate_solution(task, workdir, ollama=self.ollama)
            if not gen_meta.get("ok") and not tests.exists():
                return ExecutionResult(
                    ok=False,
                    category=self.category,
                    error=gen_meta.get("error") or "codegen_failed",
                )

        # If we only have tests, ensure a solution was generated
        if tests.exists() and not solution.exists() and not runner_script.exists():
            gen_meta = generate_solution(task, workdir, ollama=self.ollama)
            if not gen_meta.get("ok"):
                return ExecutionResult(ok=False, category=self.category, error=gen_meta.get("error") or "codegen_failed")

        attempts = []
        for attempt in range(1, 3):
            if tests.exists():
                runner = workdir / "_run_tests.py"
                runner.write_text(
                    "import importlib.util\n"
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
            elif solution.exists():
                result = run_python_isolated(script_path=solution, workdir=workdir, timeout=60)
            else:
                return ExecutionResult(ok=False, category=self.category, error="missing_solution_after_codegen")

            attempts.append({"attempt": attempt, "result": result, "codegen": gen_meta})
            if result.get("returncode", 1) == 0:
                artifacts = [str(p) for p in (solution, tests, runner_script) if p.exists()]
                return ExecutionResult(
                    ok=True,
                    category=self.category,
                    output={"run": result, "codegen": gen_meta, "attempts": attempts},
                    artifacts=artifacts,
                )

            # One repair pass: regenerate if AI available
            if attempt == 1 and self.ollama and self.ollama.available():
                if solution.exists():
                    solution.unlink()
                gen_meta = generate_solution(task, workdir, ollama=self.ollama)

        artifacts = [str(p) for p in (solution, tests, runner_script) if p.exists()]
        last = attempts[-1]["result"] if attempts else {}
        return ExecutionResult(
            ok=False,
            category=self.category,
            output={"codegen": gen_meta, "attempts": attempts},
            artifacts=artifacts,
            error=last.get("stderr") or last.get("error") or "tests_failed",
        )
