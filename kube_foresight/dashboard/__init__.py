"""Web dashboard for kube-foresight."""

from __future__ import annotations


def create_app():
    """Create and configure the FastAPI application."""
    from kube_foresight.dashboard.app import build_app

    return build_app()
