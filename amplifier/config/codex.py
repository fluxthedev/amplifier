"""Codex configuration settings for Amplifier.

This module exposes a dedicated settings model for configuring Codex CLI
integration. Values can be supplied through configuration files (``.env``)
or via ``AMPLIFIER_CODEX_*`` environment variables. Sensible defaults are
provided so existing workflows continue to function when Codex is not
available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import paths


class CodexSettings(BaseSettings):
    """Configuration for interacting with the Codex CLI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="AMPLIFIER_CODEX_",
        extra="ignore",
    )

    bin: Optional[str] = Field(
        default=None,
        description="Explicit path or command name for the Codex binary.",
    )
    sandbox: Path = Field(
        default_factory=lambda: (paths.data_dir / "codex" / "sandbox"),
        description="Default sandbox directory where Codex is allowed to operate.",
    )
    default_mode: str = Field(
        default="suggest",
        description="Default execution mode passed to the Codex CLI.",
    )
    default_timeout: Optional[int] = Field(
        default=None,
        description="Default timeout (in seconds) enforced when invoking Codex.",
    )


codex_settings = CodexSettings()

__all__ = ["CodexSettings", "codex_settings"]
