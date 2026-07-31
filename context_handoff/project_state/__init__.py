"""Where the project keeps its state on disk, and how that state is read.

Exists so the stores above it can describe WHAT they store without also owning
WHERE it lives and HOW to survive a half-written file.
"""
