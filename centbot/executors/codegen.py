"""Generate Python solutions for programming tasks (Ollama + heuristic fallback).

Generated solutions are validated against **independent** tests that are not
copied from the visible unit-test examples, to reject look-up-table overfitting.
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
            if "args ==" in src or "args==" in src.replace(" ", ""):
                literal_branches += 1
            else:
                other_logic += 1
        elif isinstance(node, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp)):
            other_logic += 1
    if literal_branches >= 2 and other_logic == 0:
        return True
    # Heuristic string marker from older codegen
    if "Literal cases derived from unit tests" in code and "while " not in code and "for " not in code:
        return True
    return False


def heuristic_solution(task: dict[str, Any], tests_src: str = "") -> str | None:
    """Synthesize an algorithmic solution for common patterns — never a case table."""
    desc = str(task.get("description") or "")
    title = str(task.get("title") or "")
    blob = f"{title}\n{desc}\n{tests_src}"

    if re.search(r"merge[_\s-]*sorted", blob, re.I):
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

    if re.search(r"\b(add|sum_two|sum2)\b", blob, re.I) or (
        "def add" in tests_src and "==" in tests_src
    ):
        funcs = _extract_function_names(blob) or ["add"]
        fn = next((f for f in funcs if f in {"add", "sum_two", "sum2"}), funcs[0])
        return f"def {fn}(a, b):\n    return a + b\n"

    if re.search(r"factorial", blob, re.I):
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

    if re.search(r"palindrome", blob, re.I):
        return textwrap.dedent(
            """\
            def is_palindrome(s):
                t = ''.join(ch.lower() for ch in str(s) if ch.isalnum())
                return t == t[::-1]
            """
        )

    if re.search(r"fibonacci|fib\b", blob, re.I):
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

    # Refuse to emit assert-case lookup tables — force Ollama or fail closed
    return None


def build_independent_tests(task: dict[str, Any], tests_src: str = "") -> str | None:
    """Property / unseen-input tests that are not copies of visible asserts."""
    desc = str(task.get("description") or "")
    title = str(task.get("title") or "")
    blob = f"{title}\n{desc}\n{tests_src}"
    funcs = _extract_function_names(blob)

    if re.search(r"merge[_\s-]*sorted", blob, re.I):
        return textwrap.dedent(
            """\
            from solution import merge_sorted

            def test_independent_empty_and_dupes():
                assert merge_sorted([], []) == []
                assert merge_sorted([1, 1, 1], [1, 1]) == [1, 1, 1, 1, 1]
                assert merge_sorted([-5, 0, 2], [-4, -1, 3]) == [-5, -4, -1, 0, 2, 3]

            def test_independent_length_invariant():
                a = list(range(0, 40, 2))
                b = list(range(1, 41, 2))
                out = merge_sorted(a, b)
                assert len(out) == len(a) + len(b)
                assert out == sorted(a + b)
            """
        )

    if re.search(r"factorial", blob, re.I):
        return textwrap.dedent(
            """\
            from solution import factorial

            def test_independent_factorial():
                assert factorial(0) == 1
                assert factorial(1) == 1
                assert factorial(7) == 5040
            """
        )

    if re.search(r"palindrome", blob, re.I):
        return textwrap.dedent(
            """\
            from solution import is_palindrome

            def test_independent_palindrome():
                assert is_palindrome("A man, a plan, a canal: Panama")
                assert not is_palindrome("centbot")
            """
        )

    if re.search(r"fibonacci|fib\b", blob, re.I):
        return textwrap.dedent(
            """\
            from solution import fibonacci

            def test_independent_fib():
                assert fibonacci(0) == 0
                assert fibonacci(10) == 55
            """
        )

    # Generic: for a binary numeric function, check commutativity / identity on unseen values
    if funcs:
        fn = funcs[0]
        visible_nums = {int(x) for x in re.findall(r"(?<!\w)(-?\d+)(?!\w)", tests_src)}
        # Choose values unlikely to appear in visible tests
        a, b = 17, -9
        if a in visible_nums or b in visible_nums:
            a, b = 101, 203
        return textwrap.dedent(
            f"""\
            from solution import {fn}

            def test_independent_unseen_inputs():
                # Unseen inputs — must not rely on a literal lookup of visible asserts
                left = {fn}({a}, {b})
                right = {fn}({b}, {a})
                # Accept either commutative numeric add or ordered merge-like results
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    assert left == right == {a} + {b}
                elif isinstance(left, list):
                    assert sorted(left) == sorted([{a}, {b}] if not isinstance({a}, list) else {a} + {b})
                else:
                    assert left is not None
            """
        )
    return None


def run_independent_validation(workdir: Path, task: dict[str, Any], tests_src: str = "") -> dict[str, Any]:
    """Write and execute independent tests against solution.py."""
    workdir = Path(workdir)
    solution = workdir / "solution.py"
    if not solution.exists():
        return {"ok": False, "error": "missing_solution"}
    code = solution.read_text(encoding="utf-8")
    if looks_like_lookup_table(code):
        return {"ok": False, "error": "lookup_table_rejected", "reason": "overfit_visible_cases"}

    indep = build_independent_tests(task, tests_src)
    if not indep:
        # No pattern-specific independent suite — structural reject of lookup tables already done
        return {"ok": True, "skipped": True, "reason": "no_independent_suite"}

    indep_path = workdir / "_independent_tests.py"
    indep_path.write_text(indep, encoding="utf-8")
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
    return {"ok": ok, "result": result, "suite": str(indep_path)}


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
    """Create solution.py and optionally prove it on independent tests."""
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
            if not indep.get("ok") and not indep.get("skipped"):
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
            if indep.get("ok") or indep.get("skipped"):
                return meta
            solution.unlink(missing_ok=True)
            continue
        return meta

    return {"ok": False, "error": "codegen_failed"}
