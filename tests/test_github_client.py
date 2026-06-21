"""Unit tests for the GitHub integration client (Sprint 6, PR#11).

All tests inject a mock ``github.Github`` handle — no live API calls. They assert
the wrapper resolves repos, performs branch/commit/PR/review operations, and
funnels PyGithub failures through :class:`GitHubError`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.integrations.github_client import (
    GitHubClient,
    GitHubError,
    PullRequestHandle,
)


def _client_with_repo(repo: Any) -> tuple[GitHubClient, MagicMock]:
    """Build a GitHubClient whose injected handle resolves to ``repo``."""
    handle = MagicMock()
    handle.get_repo.return_value = repo
    return GitHubClient(client=handle), handle


# --------------------------------------------------------------------------- #
# handle / repo resolution
# --------------------------------------------------------------------------- #


def test_missing_token_raises_when_no_client() -> None:
    client = GitHubClient(token="")
    with pytest.raises(GitHubError, match="no GitHub token"):
        client.create_branch("owner/repo", "feature/x")


def test_repo_resolution_failure_wrapped() -> None:
    handle = MagicMock()
    handle.get_repo.side_effect = RuntimeError("404 not found")
    client = GitHubClient(client=handle)
    with pytest.raises(GitHubError, match="could not resolve repo"):
        client.create_pull_request("owner/repo", "t", "b", "head")


# --------------------------------------------------------------------------- #
# create_branch
# --------------------------------------------------------------------------- #


def test_create_branch_creates_ref() -> None:
    repo = MagicMock()
    repo.get_branch.return_value = SimpleNamespace(
        commit=SimpleNamespace(sha="basesha")
    )
    client, _ = _client_with_repo(repo)

    result = client.create_branch("owner/repo", "feature/x", base="develop")

    assert result == "feature/x"
    repo.create_git_ref.assert_called_once_with(
        ref="refs/heads/feature/x", sha="basesha"
    )


def test_create_branch_tolerates_existing_ref() -> None:
    repo = MagicMock()
    repo.get_branch.return_value = SimpleNamespace(commit=SimpleNamespace(sha="s"))
    repo.create_git_ref.side_effect = RuntimeError("Reference already exists")
    client, _ = _client_with_repo(repo)

    # Should not raise — existing branch is treated as success.
    assert client.create_branch("owner/repo", "feature/x") == "feature/x"


# --------------------------------------------------------------------------- #
# commit_files
# --------------------------------------------------------------------------- #


def test_commit_files_creates_new_file() -> None:
    repo = MagicMock()
    repo.get_contents.side_effect = RuntimeError("not found")  # file absent
    client, _ = _client_with_repo(repo)

    written = client.commit_files(
        "owner/repo", "feature/x", {"src/App.tsx": "code"}, "msg"
    )

    assert written == ["src/App.tsx"]
    repo.create_file.assert_called_once()
    repo.update_file.assert_not_called()


def test_commit_files_updates_existing_file() -> None:
    repo = MagicMock()
    repo.get_contents.return_value = SimpleNamespace(sha="oldsha")
    client, _ = _client_with_repo(repo)

    written = client.commit_files(
        "owner/repo", "feature/x", {"src/App.tsx": "newcode"}, "msg"
    )

    assert written == ["src/App.tsx"]
    repo.update_file.assert_called_once()
    _, kwargs = repo.update_file.call_args
    assert kwargs["sha"] == "oldsha"


# --------------------------------------------------------------------------- #
# create_pull_request
# --------------------------------------------------------------------------- #


def test_create_pull_request_returns_handle() -> None:
    repo = MagicMock()
    repo.create_pull.return_value = SimpleNamespace(
        number=42, html_url="https://github.com/owner/repo/pull/42"
    )
    client, _ = _client_with_repo(repo)

    handle = client.create_pull_request("owner/repo", "title", "body", "feature/x")

    assert isinstance(handle, PullRequestHandle)
    assert handle.number == 42
    assert handle.url.endswith("/pull/42")


# --------------------------------------------------------------------------- #
# get_ci_logs
# --------------------------------------------------------------------------- #


def test_get_ci_logs_summarizes_check_runs() -> None:
    run = SimpleNamespace(
        name="build",
        status="completed",
        conclusion="failure",
        output=SimpleNamespace(summary="compile error on line 3"),
    )
    commit = MagicMock()
    commit.get_check_runs.return_value = [run]
    repo = MagicMock()
    repo.get_pull.return_value = SimpleNamespace(head=SimpleNamespace(sha="headsha"))
    repo.get_commit.return_value = commit
    client, _ = _client_with_repo(repo)

    logs = client.get_ci_logs("owner/repo", 7)

    assert "build" in logs
    assert "conclusion=failure" in logs
    assert "compile error on line 3" in logs


# --------------------------------------------------------------------------- #
# submit_review / auto_merge
# --------------------------------------------------------------------------- #


def test_submit_review_returns_id() -> None:
    pr = MagicMock()
    pr.create_review.return_value = SimpleNamespace(id=123)
    repo = MagicMock()
    repo.get_pull.return_value = pr
    client, _ = _client_with_repo(repo)

    review_id = client.submit_review(
        "owner/repo", 7, "APPROVE", "lgtm", comments=[]
    )

    assert review_id == 123
    _, kwargs = pr.create_review.call_args
    assert kwargs["event"] == "APPROVE"


def test_auto_merge_returns_merged_flag() -> None:
    pr = MagicMock()
    pr.merge.return_value = SimpleNamespace(merged=True)
    repo = MagicMock()
    repo.get_pull.return_value = pr
    client, _ = _client_with_repo(repo)

    assert client.auto_merge("owner/repo", 7) is True
    _, kwargs = pr.merge.call_args
    assert kwargs["merge_method"] == "squash"


def test_submit_review_wraps_failure() -> None:
    repo = MagicMock()
    repo.get_pull.side_effect = RuntimeError("422 unprocessable")
    client, _ = _client_with_repo(repo)

    with pytest.raises(GitHubError, match="submit_review failed"):
        client.submit_review("owner/repo", 7, "APPROVE", "x")
