"""Thin, typed wrapper around PyGithub for the Reviewer agent's GitHub I/O.

The Reviewer (Sprint 6) needs to push generated code to a branch, open a pull
request, read the resulting CI status, post an inline review, and optionally
auto-merge. PyGithub is dynamically typed (everything is ``Any``); this wrapper
gives the rest of the codebase a small, strictly-typed surface and funnels every
PyGithub failure through a single :class:`GitHubError` so callers don't import
``github.*`` exceptions.

The underlying ``github.Github`` handle is created lazily (so importing this
module never touches the network or requires a token) and can be **injected**
for tests — every method takes the ``"owner/name"`` repo slug and resolves it
through the injected handle, so unit tests mock the handle and assert calls
without any live API access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from src.core.config import settings
from src.core.logging import logger


class GitHubError(Exception):
    """Raised when a GitHub API operation fails (wraps PyGithub errors)."""


@dataclass(frozen=True)
class PullRequestHandle:
    """Lightweight reference to a created/opened pull request."""

    number: int
    url: str


class GitHubClient:
    """Typed facade over PyGithub for branch/commit/PR/review operations."""

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        client: Optional[Any] = None,
    ) -> None:
        """Bind to a GitHub token (or an injected ``github.Github`` handle).

        Args:
            token: Personal access token; defaults to ``settings.GITHUB_TOKEN``.
            client: Pre-built ``github.Github`` handle (used by tests to inject a
                mock); when given, ``token`` is ignored and no real handle is made.
        """
        self._token = token if token is not None else settings.GITHUB_TOKEN
        self._client = client

    # --- handle / repo resolution ---------------------------------------- #

    def _gh(self) -> Any:
        """Return the (lazily constructed) ``github.Github`` handle."""
        if self._client is None:
            if not self._token:
                raise GitHubError("no GitHub token configured (set GITHUB_TOKEN)")
            try:
                # Imported lazily; PyGithub need not be importable at module load.
                from github import Github
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise GitHubError("PyGithub is not installed") from exc
            self._client = Github(self._token)
        return self._client

    def _repo(self, repo: str) -> Any:
        """Resolve an ``"owner/name"`` slug to a PyGithub ``Repository``."""
        try:
            return self._gh().get_repo(repo)
        except Exception as exc:  # PyGithub raises GithubException subclasses
            raise GitHubError(f"could not resolve repo '{repo}': {exc}") from exc

    # --- write operations ------------------------------------------------- #

    def create_branch(self, repo: str, branch: str, base: str = "main") -> str:
        """Create ``branch`` off ``base`` and return the new branch name.

        Idempotent-ish: if the branch already exists the existing ref is returned
        rather than raising, so a re-run of the Reviewer doesn't hard-fail.
        """
        repository = self._repo(repo)
        try:
            base_sha = repository.get_branch(base).commit.sha
            ref = f"refs/heads/{branch}"
            try:
                repository.create_git_ref(ref=ref, sha=base_sha)
            except Exception:
                # Most likely "Reference already exists" — treat as success.
                repository.get_branch(branch)
            logger.info("GitHub branch ready", repo=repo, branch=branch, base=base)
            return branch
        except GitHubError:
            raise
        except Exception as exc:
            raise GitHubError(f"create_branch failed for '{branch}': {exc}") from exc

    def commit_files(
        self,
        repo: str,
        branch: str,
        files: dict[str, str],
        message: str,
    ) -> list[str]:
        """Create/update each file in ``files`` on ``branch`` in one logical commit.

        Returns the list of paths written. Each path is created if absent or
        updated (using its current blob sha) if it already exists on the branch.
        """
        repository = self._repo(repo)
        written: list[str] = []
        for path, content in files.items():
            try:
                existing = repository.get_contents(path, ref=branch)
                repository.update_file(
                    path=path,
                    message=message,
                    content=content,
                    sha=existing.sha,
                    branch=branch,
                )
            except Exception:
                # Not present (or get_contents failed) → create it.
                try:
                    repository.create_file(
                        path=path, message=message, content=content, branch=branch
                    )
                except Exception as exc:
                    raise GitHubError(
                        f"commit_files failed for '{path}': {exc}"
                    ) from exc
            written.append(path)
        logger.info(
            "GitHub files committed", repo=repo, branch=branch, count=len(written)
        )
        return written

    def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PullRequestHandle:
        """Open a pull request and return its number + html URL."""
        repository = self._repo(repo)
        try:
            pr = repository.create_pull(title=title, body=body, head=head, base=base)
            logger.info("GitHub PR opened", repo=repo, number=pr.number)
            return PullRequestHandle(number=int(pr.number), url=str(pr.html_url))
        except Exception as exc:
            raise GitHubError(f"create_pull_request failed: {exc}") from exc

    # --- read / review operations ----------------------------------------- #

    def get_ci_logs(self, repo: str, pr_number: int) -> str:
        """Return a best-effort text summary of the PR head commit's CI checks.

        PyGithub exposes check runs (name + status + conclusion + output summary)
        rather than raw log files; we fold those into a single text block that the
        Reviewer can analyze. Empty string when no checks are present.
        """
        repository = self._repo(repo)
        try:
            pr = repository.get_pull(pr_number)
            head_sha = pr.head.sha
            commit = repository.get_commit(head_sha)
            blocks: list[str] = []
            for run in commit.get_check_runs():
                summary = ""
                output = getattr(run, "output", None)
                if output is not None and getattr(output, "summary", None):
                    summary = f"\n  {output.summary}"
                blocks.append(
                    f"- {run.name}: status={run.status} "
                    f"conclusion={run.conclusion}{summary}"
                )
            return "\n".join(blocks)
        except Exception as exc:
            raise GitHubError(f"get_ci_logs failed for PR #{pr_number}: {exc}") from exc

    def submit_review(
        self,
        repo: str,
        pr_number: int,
        event: str,
        body: str,
        comments: Optional[list[dict[str, Any]]] = None,
    ) -> int:
        """Submit a PR review and return the created review's id.

        Args:
            event: GitHub review event — ``APPROVE``, ``REQUEST_CHANGES``, or
                ``COMMENT``.
            comments: Optional inline comments as PyGithub dicts
                (``{"path", "line"|"position", "body"}``).
        """
        repository = self._repo(repo)
        try:
            pr = repository.get_pull(pr_number)
            review = pr.create_review(
                body=body, event=event, comments=comments or []
            )
            logger.info(
                "GitHub review submitted",
                repo=repo,
                number=pr_number,
                review_event=event,
            )
            return int(review.id)
        except Exception as exc:
            raise GitHubError(
                f"submit_review failed for PR #{pr_number}: {exc}"
            ) from exc

    def auto_merge(
        self, repo: str, pr_number: int, merge_method: str = "squash"
    ) -> bool:
        """Merge the PR (default squash). Returns True if GitHub reports merged."""
        repository = self._repo(repo)
        try:
            pr = repository.get_pull(pr_number)
            result = pr.merge(merge_method=merge_method)
            merged = bool(getattr(result, "merged", False))
            logger.info(
                "GitHub PR merge attempted",
                repo=repo,
                number=pr_number,
                merged=merged,
            )
            return merged
        except Exception as exc:
            raise GitHubError(f"auto_merge failed for PR #{pr_number}: {exc}") from exc
