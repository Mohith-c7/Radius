"""Ports of the v2 renderer/publisher (implemented by VD-06).

The worker injects a GitHub client; nothing here talks to the network.
"""

from __future__ import annotations

from typing import Protocol

from radius_github.verdict_v2.view import VerdictV2View


class VerdictRenderer(Protocol):
    """Pure rendering of a view to GitHub Markdown (escaping and caps inside)."""

    def render_comment(self, view: VerdictV2View) -> str: ...

    def render_check_summary(self, view: VerdictV2View) -> str: ...


class VerdictPublisher(Protocol):
    """Create or update the single comment and Check Run in place.

    Returns the digest of the rendered body so identical re-renders can be
    skipped by the caller (``published_digest``).
    """

    def publish(self, view: VerdictV2View) -> str: ...
