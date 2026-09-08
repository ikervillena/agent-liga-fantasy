"""Adapter for the official LaLiga Fantasy API (2026/27)."""

from .auth import AuthError, TokenStore
from .client import ApiError, FantasyClient

__all__ = ["ApiError", "AuthError", "FantasyClient", "TokenStore"]
