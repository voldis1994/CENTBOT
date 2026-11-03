"""Generate Python solutions for programming tasks (Ollama + heuristic fallback).

Independent tests are derived from the **specific task requirements** (named
algorithms / stated properties). Generic assumptions such as “any binary
function is addition” are forbidden. If a sufficient independent suite cannot
be built, validation fails closed so the task is not auto-submitted.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path
from typing import Any

from centbot.ai.ollama_client import OllamaClient
from centbot.core.logger import get_logger
from centbot.sandbox.isolated import run_python_isolated

log = get_logger("centbot.codegen")


def extract_python_fence(text: str) -> str | None:
    m = re.search(r"```(?:python|py)\s*([\s\S]*?)```", text, re.I)
    if not m:
        return None
    code = m.group(1).strip()
    return code or None


def _extract_function_names(text: str) -> list[str]:
    names = re.findall(r"\bdef\s+([a-zA-Z_]\w*)\s*\(", text)
    names += re.findall(r"(?:function|named)\s+[`'\"]?([a-zA-Z_]\w*)", text, re.I)
    out: list[str] = []
    for n in names:
        if n.startswith("test_"):
            continue
        if n not in out:
            out.append(n)
    return out


def _task_blob(task: dict[str, Any], tests_src: str = "") -> str:
    return f"{task.get('title') or ''}\n{task.get('description') or ''}\n{tests_src}"


def detect_task_kind(task: dict[str, Any], tests_src: str = "") -> str | None:
    """Map a task to a known requirement family used for independent oracles."""
    blob = _task_blob(task, tests_src)
    if re.search(r"merge[_\s-]*sorted", blob, re.I):
        return "merge_sorted"
    if re.search(r"factorial", blob, re.I):
        return "factorial"
    if re.search(r"palindrome", blob, re.I):
        return "palindrome"
    if re.search(r"fibonacci|\bfib\b", blob, re.I):
        return "fibonacci"
    # Addition only when the task itself is about adding / summing two numbers
    if re.search(r"\b(add two|sum two|addition of two|implement\s+add\b|function\s+add\b)", blob, re.I):
        return "add"
    if re.search(r"\b(add|sum_two|sum2)\b", blob, re.I) and re.search(
        r"\b(add|sum)\b.{0,40}\b(two|2|numbers|integers)\b", blob, re.I
    ):
        return "add"
    funcs = _extract_function_names(blob)
    if funcs == ["add"] and re.search(r"assert\s+add\s*\(", tests_src):
        # Visible tests call add(...); still require description to mention add/sum
        if re.search(r"\b(add|sum|addition)\b", f"{task.get('title') or ''} {task.get('description') or ''}", re.I):
            return "add"
    return None


def looks_like_lookup_table(code: str) -> bool:
    """Detect solutions that only hard-code visible assert cases."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    literal_branches = 0
    other_logic = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            src = ast.unparse(node.test) if hasattr(ast, "unparse") else ""
            compact = src.replace(" ", "")
            if "args==" in compact or re.search(r"==\s*\(", src):
                literal_branches += 1
            else:
                other_logic += 1
        elif isinstance(node, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp)):
            other_logic += 1
    if literal_branches >= 2 and other_logic == 0:
        return True
    if "Literal cases derived from unit tests" in code and "while " not in code and "for " not in code:
        return True
    return False


def _visible_assert_literals(tests_src: str) -> set[str]:
    return set(re.findall(r"assert\s+.+$", tests_src, re.M))


def heuristic_solution(task: dict[str, Any], tests_src: str = "") -> str | None:
    """Synthesize an algorithmic solution only for recognized task kinds."""
    kind = detect_task_kind(task, tests_src)
    if kind == "merge_sorted":
        return textwrap.dedent(
            """\
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
            """
        )
    if kind == "add":
        funcs = _extract_function_names(_task_blob(task, tests_src)) or ["add"]
        fn = next((f for f in funcs if f in {"add", "sum_two", "sum2"}), funcs[0])
        return f"def {fn}(a, b):\n    return a + b\n"
    if kind == "factorial":
        return textwrap.dedent(
            """\
            def factorial(n):
                if n < 0:
                    raise ValueError(n)
                out = 1
                for i in range(2, n + 1):
                    out *= i
                return out
            """
        )
    if kind == "palindrome":
        return textwrap.dedent(
            """\
            def is_palindrome(s):
                t = ''.join(ch.lower() for ch in str(s) if ch.isalnum())
                return t == t[::-1]
            """
        )
    if kind == "fibonacci":
        return textwrap.dedent(
            """\
            def fibonacci(n):
                if n < 0:
                    raise ValueError(n)
                a, b = 0, 1
                for _ in range(n):
                    a, b = b, a + b
                return a
            """
        )
    return None


def build_independent_tests(task: dict[str, Any], tests_src: str = "") -> dict[str, Any]:
    """Build property / edge-case tests from the task kind — never generic add guesses.

    Returns ``{"ok": True, "source": ..., "code": "..."}`` or
    ``{"ok": False, "error": "insufficient_independent_coverage"}``.
    """
    kind = detect_task_kind(task, tests_src)
    visible = _visible_assert_literals(tests_src)

    if kind == "merge_sorted":
        code = textwrap.dedent(
            """\
            from solution import merge_sorted

            def test_independent_empty_and_dupes():
                assert merge_sorted([], []) == []
                assert merge_sorted([1, 1, 1], [1, 1]) == [1, 1, 1, 1, 1]
                assert merge_sorted([-5, 0, 2], [-4, -1, 3]) == [-5, -4, -1, 0, 2, 3]

            def test_independent_length_and_sorted_property():
                a = list(range(0, 40, 2))
                b = list(range(1, 41, 2))
                out = merge_sorted(a, b)
                assert len(out) == len(a) + len(b)
                assert out == sorted(a + b)

            def test_independent_single_sided():
                assert merge_sorted([2, 4, 6], []) == [2, 4, 6]
                assert merge_sorted([], [3, 5, 7]) == [3, 5, 7]
            """
        )
        return {"ok": True, "kind": kind, "code": code, "visible_overlap": _overlap(visible, code)}

    if kind == "factorial":
        code = textwrap.dedent(
            """\
            from solution import factorial

            def test_independent_factorial_edges():
                assert factorial(0) == 1
                assert factorial(1) == 1
                assert factorial(7) == 5040
                assert factorial(10) == 3628800
            """
        )
        return {"ok": True, "kind": kind, "code": code, "visible_overlap": _overlap(visible, code)}

    if kind == "palindrome":
        code = textwrap.dedent(
            """\
            from solution import is_palindrome

            def test_independent_palindrome_edges():
                assert is_palindrome("")
                assert is_palindrome("A man, a plan, a canal: Panama")
                assert not is_palindrome("centbot")
                assert is_palindrome(121) or is_palindrome("121")
            """
        )
        return {"ok": True, "kind": kind, "code": code, "visible_overlap": _overlap(visible, code)}

    if kind == "fibonacci":
        code = textwrap.dedent(
            """\
            from solution import fibonacci

            def test_independent_fib_edges():
                assert fibonacci(0) == 0
                assert fibonacci(1) == 1
                assert fibonacci(10) == 55
                assert fibonacci(15) == 610
            """
        )
        return {"ok": True, "kind": kind, "code": code, "visible_overlap": _overlap(visible, code)}

    if kind == "add":
        funcs = _extract_function_names(_task_blob(task, tests_src)) or ["add"]
        fn = next((f for f in funcs if f in {"add", "sum_two", "sum2"}), funcs[0])
        # Unseen inputs + algebraic properties (not copies of visible asserts)
        code = textwrap.dedent(
            f"""\
            from solution import {fn}

            def test_independent_unseen_sums():
                assert {fn}(17, -9) == 8
                assert {fn}(101, 203) == 304
                assert {fn}(0, 0) == 0

            def test_independent_add_properties():
                assert {fn}(42, 0) == 42
                assert {fn}(0, 42) == 42
                assert {fn}(19, 23) == {fn}(23, 19)
            """
        )
        return {"ok": True, "kind": kind, "code": code, "visible_overlap": _overlap(visible, code)}

    return {
        "ok": False,
        "error": "insufficient_independent_coverage",
        "reason": "no_task_specific_oracle",
        "kind": kind,
    }


def _overlap(visible: set[str], code: str) -> int:
    return sum(1 for line in visible if line.strip() and line.strip() in code)


def run_independent_validation(workdir: Path, task: dict[str, Any], tests_src: str = "") -> dict[str, Any]:
    """Write and execute independent tests; fail closed without a task-specific suite."""
    workdir = Path(workdir)
    solution = workdir / "solution.py"
    if not solution.exists():
        return {"ok": False, "error": "missing_solution"}
    code = solution.read_text(encoding="utf-8")
    if looks_like_lookup_table(code):
        return {"ok": False, "error": "lookup_table_rejected", "reason": "overfit_visible_cases"}

    built = build_independent_tests(task, tests_src)
    if not built.get("ok"):
        return {
            "ok": False,
            "error": built.get("error") or "insufficient_independent_coverage",
            "reason": built.get("reason"),
            "skipped": False,
        }

    indep_path = workdir / "_independent_tests.py"
    indep_path.write_text(str(built["code"]), encoding="utf-8")
    runner = workdir / "_run_independent.py"
    runner.write_text(
        textwrap.dedent(
            """\
            import importlib.util
            from pathlib import Path
            p = Path('_independent_tests.py')
            spec = importlib.util.spec_from_file_location('independent_tests', p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ran = 0
            for name in dir(mod):
                if name.startswith('test_') and callable(getattr(mod, name)):
                    getattr(mod, name)()
                    ran += 1
            assert ran > 0, 'no independent tests'
            print('INDEPENDENT_OK', ran)
            """
        ),
        encoding="utf-8",
    )
    result = run_python_isolated(script_path=runner, workdir=workdir, timeout=60)
    ok = bool(result.get("ok")) and "INDEPENDENT_OK" in (result.get("stdout") or "")
    return {
        "ok": ok,
        "result": result,
        "suite": str(indep_path),
        "kind": built.get("kind"),
        "skipped": False,
    }


def ollama_solution(task: dict[str, Any], tests_src: str, client: OllamaClient | None = None) -> str | None:
    client = client or OllamaClient()
    if not client.available():
        return None
    prompt = (
        "Write a complete, general Python module that solves the task for ALL valid inputs, "
        "not just the example asserts. Do not hard-code test cases. "
        "Reply with ONLY Python code, no markdown.\n\n"
        f"TASK TITLE: {task.get('title')}\n"
        f"TASK DESCRIPTION:\n{task.get('description')}\n\n"
        f"UNIT TESTS (examples only):\n{tests_src}\n"
    )
    result = client.generate(prompt)
    if not result.get("ok"):
        return None
    text = str(result.get("response") or "")
    fenced = extract_python_fence(text)
    code = fenced or text
    code = re.sub(r"^```(?:python|py)?\s*", "", code.strip())
    code = re.sub(r"\s*```$", "", code)
    if "def " not in code:
        return None
    if looks_like_lookup_table(code):
        return None
    return code


def generate_solution(
    task: dict[str, Any],
    workdir: Path,
    *,
    ollama: OllamaClient | None = None,
    validate_independent: bool = True,
) -> dict[str, Any]:
    """Create solution.py and prove it on task-specific independent tests."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    solution = workdir / "solution.py"
    tests = workdir / "test_solution.py"
    desc = str(task.get("description") or "")

    if not tests.exists():
        test_fence = None
        for m in re.finditer(r"```(?:python|py)\s*([\s\S]*?)```", desc, re.I):
            block = m.group(1)
            if "assert " in block or "def test_" in block:
                test_fence = block.strip()
                break
        if test_fence:
            tests.write_text(test_fence, encoding="utf-8")

    tests_src = tests.read_text(encoding="utf-8") if tests.exists() else ""

    if solution.exists():
        meta: dict[str, Any] = {"ok": True, "source": "existing", "path": str(solution)}
        if validate_independent:
            indep = run_independent_validation(workdir, task, tests_src)
            meta["independent"] = indep
            if not indep.get("ok"):
                meta["ok"] = False
                meta["error"] = indep.get("error") or "independent_tests_failed"
        return meta

    candidates: list[tuple[str, str]] = []
    fenced = extract_python_fence(desc)
    if fenced and "def test_" not in fenced:
        candidates.append(("description_fence", fenced))

    ai = ollama_solution(task, tests_src, client=ollama)
    if ai:
        candidates.append(("ollama", ai))

    heur = heuristic_solution(task, tests_src)
    if heur:
        candidates.append(("heuristic", heur))

    for source, code in candidates:
        if looks_like_lookup_table(code):
            continue
        solution.write_text(code, encoding="utf-8")
        meta = {"ok": True, "source": source, "path": str(solution)}
        if validate_independent:
            indep = run_independent_validation(workdir, task, tests_src)
            meta["independent"] = indep
            if indep.get("ok"):
                return meta
            solution.unlink(missing_ok=True)
            continue
        return meta

    # Fail closed when we cannot both generate and independently verify
    if validate_independent and detect_task_kind(task, tests_src) is None:
        return {"ok": False, "error": "insufficient_independent_coverage"}
    return {"ok": False, "error": "codegen_failed"}
