"""Architecture guard: interface CODE must name no concrete technology.

Adapter boundaries only hold if nothing leaks across them, and the drift that
breaks them happens one convenient constant at a time. This test strips
docstrings and comments — where naming the first implementations is legitimate
documentation — and asserts the remaining executable source mentions no Claude
CLI or tmux term.
"""
from __future__ import annotations

import ast
import io
import os
import tokenize

import pytest

INTERFACES_PACKAGE_DIRECTORY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "context_handoff",
    "interfaces",
)

FORBIDDEN_TECHNOLOGY_SUBSTRINGS = (
    "claude",
    "tmux",
    "gnome-terminal",
    "--resume",
    "--fork-session",
    "--session-id",
    "send-keys",
    "pipe-pane",
)


def _iter_interface_source_paths() -> list[str]:
    return [
        os.path.join(INTERFACES_PACKAGE_DIRECTORY, file_name)
        for file_name in sorted(os.listdir(INTERFACES_PACKAGE_DIRECTORY))
        if file_name.endswith(".py")
    ]


def strip_comments_and_docstrings_from_python_source(source_text: str) -> str:
    """Return only the executable part of ``source_text``.

    Comments are removed by token type. Docstrings are removed by walking the
    AST and blanking the line span of every expression statement whose sole
    value is a string constant — the documented definition of a docstring —
    which also covers module, class, and method docstrings uniformly.
    """
    source_lines = source_text.splitlines()
    lines_to_blank: set[int] = set()

    parsed_module = ast.parse(source_text)
    for node in ast.walk(parsed_module):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for statement in body:
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                end_line_number = statement.end_lineno or statement.lineno
                lines_to_blank.update(range(statement.lineno, end_line_number + 1))

    source_without_docstrings = "\n".join(
        "" if (line_number + 1) in lines_to_blank else line_text
        for line_number, line_text in enumerate(source_lines)
    )

    kept_tokens = [
        token
        for token in tokenize.generate_tokens(
            io.StringIO(source_without_docstrings).readline
        )
        if token.type != tokenize.COMMENT
    ]
    # untokenize with full 5-tuples restores original spacing, so the result
    # reads as real source rather than a run-together token stream.
    return tokenize.untokenize(kept_tokens)


@pytest.mark.parametrize("interface_source_path", _iter_interface_source_paths())
def test_interface_code_names_no_concrete_technology(interface_source_path: str) -> None:
    with open(interface_source_path, "r", encoding="utf-8") as source_file:
        source_text = source_file.read()
    executable_source_lowercased = strip_comments_and_docstrings_from_python_source(
        source_text
    ).lower()
    for forbidden_substring in FORBIDDEN_TECHNOLOGY_SUBSTRINGS:
        assert forbidden_substring not in executable_source_lowercased, (
            f"{os.path.basename(interface_source_path)} references {forbidden_substring!r} "
            "in executable code; concrete technology belongs in an adapter"
        )


@pytest.mark.parametrize("interface_source_path", _iter_interface_source_paths())
def test_interface_module_imports_nothing_from_the_adapters_package(
    interface_source_path: str,
) -> None:
    with open(interface_source_path, "r", encoding="utf-8") as source_file:
        parsed_module = ast.parse(source_file.read())
    for node in ast.walk(parsed_module):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "adapters" not in node.module, (
                f"{os.path.basename(interface_source_path)} imports from "
                f"{node.module}; interfaces must not depend on adapters"
            )
        elif isinstance(node, ast.Import):
            for imported_name in node.names:
                assert "adapters" not in imported_name.name, (
                    f"{os.path.basename(interface_source_path)} imports "
                    f"{imported_name.name}; interfaces must not depend on adapters"
                )


def test_at_least_one_interface_source_file_was_scanned() -> None:
    """Guards against the scan silently passing because it found no files."""
    assert _iter_interface_source_paths()


def test_the_stripper_actually_removes_docstrings_and_comments() -> None:
    """The guard is only meaningful if its stripper works; prove it here."""
    sample_source = '"""module docstring mentioning tmux."""\n' 'X = 1  # comment mentioning claude\n'
    stripped = strip_comments_and_docstrings_from_python_source(sample_source)
    assert "tmux" not in stripped
    assert "claude" not in stripped
    assert "X = 1" in stripped


def test_the_stripper_keeps_technology_names_that_appear_in_real_code() -> None:
    """A leak in executable code must survive stripping, or the guard is blind."""
    sample_source = '"""docstring."""\nDEFAULT_COMMAND = "claude --resume"\n'
    stripped = strip_comments_and_docstrings_from_python_source(sample_source)
    assert "claude --resume" in stripped
