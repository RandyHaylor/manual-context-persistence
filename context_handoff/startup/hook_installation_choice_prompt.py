"""Ask whether to install the missing hooks, or abort the run.

This is only reached when the project already has a ``settings.local.json`` that
does not register our hooks. A file that is not there at all is set up without
asking — there is nothing of the operator's to disturb. A file that exists is
theirs, so writing into it is a decision they make.

There is no third answer. Continuing without the hooks is not offered here
because a run with no capture looks healthy and records nothing; the operator who
genuinely wants that passes the skip flag on the command line, where it is an
explicit choice rather than a menu option chosen in passing.

Reading and writing are injected, as in the base-session prompt, so the
conversation runs in a test with scripted answers instead of a terminal.
"""
from __future__ import annotations

from typing import Callable

INSTALL_ANSWERS = frozenset({"install", "i", "yes", "y"})
ABORT_ANSWERS = frozenset({"abort", "a", "no", "n", "quit"})


def ask_whether_to_install_missing_hooks(
    read_answer: Callable[[str], str],
    write_line: Callable[[str], None],
    missing_hook_event_names: list[str],
    settings_file_path: str,
) -> bool:
    """Return True to install, False to abort.

    Propagates ``EOFError`` from ``read_answer``: a closed input stream is not
    an answer, and must never be read as consent to write the operator's file.
    """
    write_line(
        f"{settings_file_path} does not register hooks for: "
        + ", ".join(missing_hook_event_names)
    )
    while True:
        answer = read_answer(
            "[install] them, or [abort]? "
        ).strip().lower()
        if answer in INSTALL_ANSWERS:
            return True
        if answer in ABORT_ANSWERS:
            return False
        write_line("Please answer 'install' or 'abort'.")
