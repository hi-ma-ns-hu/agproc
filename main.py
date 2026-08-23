"""Entrypoint for `fastapi deploy` / `fastapi run` — re-exports the app built in app.py."""

from app import app

__all__ = ['app']
