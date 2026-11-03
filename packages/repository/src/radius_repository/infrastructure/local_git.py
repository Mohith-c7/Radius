"""Subprocess-backed local Git repository client.

Every value handed to git here may come from a database row or an API caller, so
this module does not trust it: clone URLs are re-validated (https, allow-listed
host, ``owner/repo`` shape), refs are validated, positional arguments follow
``--`` where git supports it, git never goes through a shell, only the ``https``
transport is enabled, and hooks, fsmonitor and credential helpers are switched
off for every invocation.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from radius_shared.errors import ValidationError
from radius_shared.redaction import REDACTED, redact_secrets

from radius_repository.domain.clone_url import GitUrlPolicy, host_of, validate_clone_url

_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
# A conservative ref/refspec: no leading '-', no whitespace or shell/git magic.
_REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./+:-]{0,254}$")


def _safe_ref(value: object, what: str) -> str:
    if (
        not isinstance(value, str)
        or not _REF.match(value)
        or ".." in value
        or value.endswith((".lock", "/"))
    ):
        raise ValidationError(f"Invalid git {what}.")
    return value


class LocalGitRepositoryClient:
    """Clone, fetch, and checkout repositories using the Git CLI."""

    def __init__(self, policy: GitUrlPolicy | None = None) -> None:
        self._policy = policy or GitUrlPolicy()

    @property
    def policy(self) -> GitUrlPolicy:
        """The clone URL policy this client enforces."""

        return self._policy

    def clone_or_fetch(
        self,
        clone_url: str,
        destination: Path,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> Path:
        """Clone a repository or fetch updates when it already exists."""

        if destination.exists():
            if not (destination / ".git").exists():
                msg = f"Destination is not a Git repository: {destination}."
                raise ValidationError(msg)
            # The checkout was created by an earlier run: do not trust its
            # recorded origin either (it is validated before git talks to it).
            remote = self._validated_origin(destination)
            self._run(
                ("git", "fetch", "--all", "--prune"),
                cwd=destination,
                extra_headers=extra_headers,
                remote_url=remote,
            )
            return destination

        safe_url = validate_clone_url(clone_url, policy=self._policy)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            (
                "git",
                "clone",
                "--no-recurse-submodules",
                "--",
                safe_url,
                str(destination),
            ),
            cwd=None,
            extra_headers=extra_headers,
            remote_url=safe_url,
        )
        return destination

    def checkout(self, repository_path: Path, branch_name: str) -> None:
        """Check out a commit (hex 7-64) or a plain ref name, detached."""

        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)
        ref = (
            branch_name
            if isinstance(branch_name, str) and _COMMIT_SHA.match(branch_name)
            else _safe_ref(branch_name, "ref")
        )
        self._run(("git", "checkout", "--detach", ref, "--"), cwd=repository_path)

    def fetch_pull_request(
        self,
        repository_path: Path,
        pr_number: int,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> None:
        """Fetch PR head ref from origin into refs/remotes/origin/pr/<pr_number>."""

        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)
        if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number < 1:
            raise ValidationError("Invalid pull request number.")
        remote = self._validated_origin(repository_path)
        self._run(
            (
                "git",
                "fetch",
                "origin",
                f"+refs/pull/{pr_number}/head:refs/remotes/origin/pr/{pr_number}",
            ),
            cwd=repository_path,
            extra_headers=extra_headers,
            remote_url=remote,
        )

    def fetch_ref(
        self,
        repository_path: Path,
        remote_ref: str,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> None:
        """Fetch a specific remote ref from origin."""

        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)
        ref = _safe_ref(remote_ref, "ref")
        remote = self._validated_origin(repository_path)
        self._run(
            ("git", "fetch", "origin", ref),
            cwd=repository_path,
            extra_headers=extra_headers,
            remote_url=remote,
        )

    def _validated_origin(self, repository_path: Path) -> str:
        """The checkout's ``origin`` URL, re-validated before git contacts it."""

        recorded = _origin_remote_url(repository_path)
        if recorded is None:
            raise ValidationError("The checkout has no usable 'origin' remote.")
        return validate_clone_url(recorded, policy=self._policy)

    def _run(
        self,
        command: tuple[str, ...],
        cwd: Path | None,
        *,
        extra_headers: tuple[str, ...] = (),
        remote_url: str | None = None,
    ) -> None:
        """Run git, passing credentials only through the child's environment.

        ``extra_headers`` (e.g. ``Authorization: Basic ...``) are handed to git
        as ``GIT_CONFIG_COUNT/KEY_n/VALUE_n`` environment variables, git's
        documented way to set config for one process. Unlike ``-c`` they never
        appear in the command line (``ps``, process listings, crash reports),
        and unlike ``git config`` / a credential URL they are never written to
        ``.git/config``. The header is scoped to the remote's origin, and only
        sent at all when that origin's host is on the allow-list, so it is
        neither replayed to another host after a redirect nor sent to a host a
        stored URL happens to name.
        """

        if extra_headers and remote_url is None and cwd is not None:
            remote_url = _origin_remote_url(cwd)
        env = _git_environment(extra_headers, remote_url, self._policy)
        argv = _hardened(command, self._policy)
        try:
            subprocess.run(  # noqa: S603 - argv list, never a shell
                argv,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                env=env,
                shell=False,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise ValidationError(_scrub(message, extra_headers)) from exc


def _hardened(command: tuple[str, ...], policy: GitUrlPolicy) -> tuple[str, ...]:
    """Insert per-invocation safety config right after ``git``.

    Only ``https`` (``http`` when the policy allows it, for loopback tests) may
    be used as a transport; ``file``, ``ext``, ``ssh`` and ``git`` are refused.
    Hooks, fsmonitor, credential helpers and submodule recursion are disabled
    because the checked-out content is untrusted.
    """

    config = [
        "protocol.allow=never",
        "protocol.https.allow=always",
        "core.fsmonitor=false",
        f"core.hooksPath={os.devnull}",
        "credential.helper=",
        "submodule.recurse=false",
    ]
    if policy.allow_http:
        config.append("protocol.http.allow=always")
    flags: list[str] = []
    for item in config:
        flags += ["-c", item]
    return (command[0], *flags, *command[1:])


def _origin_remote_url(repository_path: Path) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            _hardened(("git", "config", "--get", "remote.origin.url"), GitUrlPolicy()),
            cwd=repository_path,
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return result.stdout.strip() or None


def _header_scope(remote_url: str | None) -> str:
    """Return the git config subsection (``scheme://host[:port]/``) of the remote."""

    if remote_url and host_of(remote_url):
        scheme = remote_url.partition(":")[0].lower()
        if scheme in {"http", "https"}:
            netloc = remote_url.partition("//")[2].partition("/")[0].rpartition("@")[2]
            return f"{scheme}://{netloc}/"
    return ""


def _git_environment(
    extra_headers: tuple[str, ...],
    remote_url: str | None,
    policy: GitUrlPolicy | None = None,
) -> dict[str, str]:
    """Child environment: restricted transports plus the headers as git config."""

    policy = policy or GitUrlPolicy()
    env = dict(os.environ)
    for name in ("GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND", "GIT_EXTERNAL_DIFF"):
        env.pop(name, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ALLOW_PROTOCOL"] = "http:https" if policy.allow_http else "https"
    if not extra_headers:
        return env
    host = host_of(remote_url)
    if not host or host not in policy.allowed_hosts:
        # Never attach the credential to a host that is not explicitly trusted.
        raise ValidationError("Refusing to send credentials to an untrusted git host.")
    scope = _header_scope(remote_url)
    if not scope:
        raise ValidationError("Refusing to send credentials to an unscoped remote.")
    key = f"http.{scope}.extraHeader"
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        count = 0
    for header in extra_headers:
        env[f"GIT_CONFIG_KEY_{count}"] = key
        env[f"GIT_CONFIG_VALUE_{count}"] = header
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)
    return env


def _scrub(message: str, extra_headers: tuple[str, ...]) -> str:
    """Remove the credential (and its encodings) from git's error output."""

    for header in extra_headers:
        value = header.partition(":")[2].strip()
        for secret in {header, value, value.rpartition(" ")[2]}:
            if len(secret) >= 8:
                message = message.replace(secret, REDACTED)
    return redact_secrets(message.rstrip())
