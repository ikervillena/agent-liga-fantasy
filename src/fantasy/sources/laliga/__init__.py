"""Adapter for the official LaLiga Fantasy API (2026/27)."""

from fantasy.sources.laliga.auth import AuthError, TokenStore
from fantasy.sources.laliga.client import ApiError, FantasyClient

__all__ = ["ApiError", "AuthError", "FantasyClient", "TokenStore"]
