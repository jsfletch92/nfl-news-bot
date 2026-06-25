"""Automated NFL breaking-news bot.

Reads recent posts from a fixed allowlist of NFL news accounts via the X API,
identifies genuinely new news items, rewrites each in original wording, and
posts a short text-only update to the operator's own X account.
"""

__all__ = ["config", "x_client", "summarizer", "state", "bot"]
