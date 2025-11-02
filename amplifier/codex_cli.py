"""Helper utilities for working with the external Codex CLI."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from amplifier.config.codex import CodexSettings, codex_settings


class CodexUnavailableError(RuntimeError):
    """Raised when the Codex binary cannot be located or executed."""


class CodexSandboxError(RuntimeError):
    """Raised when sandbox restrictions cannot be satisfied."""


class CodexExecutionError(RuntimeError):
    """Raised when Codex exits unsuccessfully."""

    def __init__(self, command: list[str], returncode: int, stdout: str, stderr: str, message: str | None = None) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.message = message or "Codex execution failed"
        super().__init__(self.message)


class CodexExecutionCancelled(RuntimeError):
    """Raised when the user declines to execute the Codex command."""


@dataclass
class CodexRunResult:
    """Outcome of invoking the Codex CLI."""

    command: list[str]
    returncode: Optional[int]
    stdout: str
    stderr: str
    dry_run: bool = False

    def command_display(self) -> str:
        """Render the executed command as a shell string for humans."""

        return " ".join(shlex.quote(part) for part in self.command)


class CodexCLI:
    """Encapsulates discovery and execution of the Codex CLI."""

    def __init__(self, settings: Optional[CodexSettings] = None, codex_bin: Optional[str] = None) -> None:
        self.settings = settings or codex_settings
        self._binary_override = codex_bin
        self._cached_binary: Optional[str] = None

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------
    def resolve_binary(self) -> str:
        """Locate the Codex executable."""

        if self._cached_binary:
            return self._cached_binary

        candidates: list[str] = []
        if self._binary_override:
            candidates.append(self._binary_override)
        if self.settings.bin and self.settings.bin not in candidates:
            candidates.append(self.settings.bin)
        if "codex" not in candidates:
            candidates.append("codex")

        for candidate in candidates:
            binary = self._resolve_single_candidate(candidate)
            if binary:
                self._cached_binary = binary
                return binary

        raise CodexUnavailableError(
            "Unable to locate the Codex CLI. Set AMPLIFIER_CODEX_BIN or use --codex-bin."
        )

    def _resolve_single_candidate(self, candidate: str) -> Optional[str]:
        """Resolve a single candidate to an absolute executable path."""

        if os.path.isabs(candidate) and os.access(candidate, os.X_OK):
            return self._verify_binary(candidate)

        resolved = shutil.which(candidate)
        if resolved:
            return self._verify_binary(resolved)

        return None

    def _verify_binary(self, binary: str) -> str:
        """Verify that the binary executes successfully."""

        try:
            subprocess.run(
                [binary, "--version"],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise CodexUnavailableError("Codex binary not found") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or exc.stdout or ""
            raise CodexUnavailableError(
                f"Codex binary at '{binary}' is not executable: {stderr.strip()}"
            ) from exc

        return binary

    # ------------------------------------------------------------------
    # Sandbox helpers
    # ------------------------------------------------------------------
    def resolve_sandbox(self, sandbox_override: Optional[Path | str]) -> Path:
        """Resolve and prepare the sandbox directory for Codex."""

        sandbox_source = sandbox_override or self.settings.sandbox
        if sandbox_source is None:
            raise CodexSandboxError(
                "Sandbox directory is not configured. Use --sandbox or AMPLIFIER_CODEX_SANDBOX."
            )

        sandbox_path = Path(sandbox_source).expanduser().resolve()
        try:
            sandbox_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CodexSandboxError(f"Unable to create sandbox directory '{sandbox_path}': {exc}") from exc

        if not sandbox_path.is_dir():
            raise CodexSandboxError(f"Sandbox path '{sandbox_path}' is not a directory")

        return sandbox_path

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def execute(
        self,
        *,
        mode: Optional[str] = None,
        context: Optional[str] = None,
        sandbox: Optional[Path | str] = None,
        dry_run: bool = False,
        approve: bool = False,
        timeout: Optional[int] = None,
    ) -> CodexRunResult:
        """Execute the Codex CLI with safety rails."""

        binary = self.resolve_binary()
        sandbox_path = self.resolve_sandbox(sandbox)

        effective_mode = mode or self.settings.default_mode or "suggest"
        if effective_mode not in {"suggest", "auto"}:
            raise CodexExecutionError(
                [binary],
                returncode=-1,
                stdout="",
                stderr="",
                message=f"Unsupported Codex mode '{effective_mode}'.",
            )

        command = [binary, "run", "--mode", effective_mode, "--sandbox", str(sandbox_path)]

        if context:
            command.extend(["--context", context])
        if dry_run:
            command.append("--dry-run")
        effective_timeout = timeout if timeout is not None else self.settings.default_timeout
        if effective_timeout is not None:
            command.extend(["--timeout", str(effective_timeout)])

        # Render command for user display
        command_display = " ".join(shlex.quote(part) for part in command)

        if not approve:
            import click

            prompt = (
                "Codex will run in AUTO mode. Proceed?"
                if effective_mode == "auto"
                else "Execute Codex in SUGGEST mode?"
            )
            prompt = f"{prompt}\n{command_display}\nContinue?"
            if not click.confirm(prompt, default=False):
                raise CodexExecutionCancelled("Codex execution cancelled by user")

        if dry_run:
            return CodexRunResult(command=command, returncode=None, stdout="", stderr="", dry_run=True)

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexExecutionError(
                command,
                returncode=-1,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + (
                    "\nTimed out after "
                    f"{effective_timeout}s" if effective_timeout is not None else ""
                ),
                message="Codex execution timed out",
            ) from exc
        except FileNotFoundError as exc:
            raise CodexUnavailableError("Codex binary disappeared during execution") from exc

        if completed.returncode != 0:
            raise CodexExecutionError(command, completed.returncode, completed.stdout, completed.stderr)

        return CodexRunResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            dry_run=False,
        )


__all__ = [
    "CodexCLI",
    "CodexExecutionCancelled",
    "CodexExecutionError",
    "CodexRunResult",
    "CodexSandboxError",
    "CodexUnavailableError",
]
