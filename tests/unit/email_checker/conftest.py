"""Shared sys.path bootstrap for email_checker unit tests.

Lets us import ``apps.email_checker.services.*`` without needing a
Django settings module (the ``services/`` modules are framework-free).
"""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend")
_BACKEND_ABS = os.path.abspath(_BACKEND)
if _BACKEND_ABS not in sys.path:
    sys.path.insert(0, _BACKEND_ABS)
