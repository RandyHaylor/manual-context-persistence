"""Hook handlers and their executable entry points.

Handlers are plain functions taking a decoded payload and returning a response
dictionary, so they are testable without running a process. The scripts beside
them do nothing but read stdin, call a handler, and print the response.
"""
