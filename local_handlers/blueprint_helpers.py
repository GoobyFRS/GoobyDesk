#!/usr/bin/env python3
"""Shared helpers for blueprint route placeholders."""

from flask import render_template


def render_not_implemented():
    """Render the shared under-construction page."""
    return render_template("under_construction.html")