"""Vercel/FastAPI entrypoint.

Vercel discovers a FastAPI instance named ``app`` from a root-level app.py.
The application itself stays in webapp/ so the local Uvicorn command and the
hosted deployment use the same routes.
"""

from webapp.app import app

__all__ = ["app"]
