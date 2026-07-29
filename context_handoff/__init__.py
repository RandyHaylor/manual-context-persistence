"""Context-handoff POC: a persistent base session kept compact by accumulated handoffs.

The core turn loop depends only on the abstract interfaces in
``context_handoff.interfaces``. Concrete Claude CLI and tmux behaviour lives in
``context_handoff.adapters`` and is never imported by the core.
"""
