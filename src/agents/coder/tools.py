"""File tools for the Coder's react-agent tool-loop.

The Coder doesn't touch the real filesystem during generation — it writes into an
in-memory :class:`Workspace` (a ``{path: content}`` map). After the loop the
workspace contents become the ``source_code`` channel of the graph state, where
the ``merge_source_code`` reducer folds them in. The inner loop (Sprint 5) is
what later materializes these files into a Docker container for lint/test.

Tools are built per-run by :func:`make_file_tools`, each closing over a single
``Workspace`` instance so concurrent runs never share state.
"""

from __future__ import annotations

import posixpath

from langchain_core.tools import BaseTool, StructuredTool

# Map of relative path -> file content.
WorkspaceFiles = dict[str, str]


class WorkspacePathError(ValueError):
    """Raised when a tool is asked to access an unsafe or invalid path."""


class Workspace:
    """An in-memory file workspace the Coder's tools read from and write to."""

    def __init__(self, files: WorkspaceFiles | None = None) -> None:
        """Initialize, optionally seeding with existing files (e.g. for self-fix)."""
        self.files: WorkspaceFiles = dict(files or {})

    # --- path safety ------------------------------------------------------ #

    @staticmethod
    def _normalize(path: str) -> str:
        """Validate and normalize a relative path, rejecting traversal/absolutes.

        Keeps everything inside the workspace root: no absolute paths, no drive
        letters, no ``..`` escapes. Returns a clean POSIX-style relative path.
        """
        raw = (path or "").strip().replace("\\", "/")
        if not raw:
            raise WorkspacePathError("path must not be empty")
        if raw.startswith("/") or ":" in raw.split("/")[0]:
            raise WorkspacePathError(f"absolute paths are not allowed: {path!r}")

        normalized = posixpath.normpath(raw)
        if normalized.startswith("..") or normalized == ".":
            raise WorkspacePathError(f"path escapes the workspace: {path!r}")
        return normalized

    # --- operations ------------------------------------------------------- #

    def write(self, path: str, content: str) -> str:
        """Create or overwrite a file. Returns a short confirmation message."""
        clean = self._normalize(path)
        self.files[clean] = content
        return f"wrote {clean} ({len(content)} bytes)"

    def read(self, path: str) -> str:
        """Return a file's contents, or raise if it doesn't exist."""
        clean = self._normalize(path)
        if clean not in self.files:
            raise WorkspacePathError(f"file not found: {clean}")
        return self.files[clean]

    def list_paths(self) -> list[str]:
        """Return all workspace paths, sorted."""
        return sorted(self.files)


def make_file_tools(workspace: Workspace) -> list[BaseTool]:
    """Build the file tools (write/read/list) bound to ``workspace``.

    Returned tools are plain LangChain ``StructuredTool`` objects suitable for
    ``create_react_agent``. Path errors are returned to the model as text (not
    raised) so the agent can self-correct rather than crashing the loop.
    """

    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file in the project workspace.

        Args:
            path: Relative path within the project (e.g. ``src/App.tsx``).
            content: Full file contents to write.
        """
        try:
            return workspace.write(path, content)
        except WorkspacePathError as exc:
            return f"ERROR: {exc}"

    def read_file(path: str) -> str:
        """Read a file's contents from the project workspace.

        Args:
            path: Relative path within the project.
        """
        try:
            return workspace.read(path)
        except WorkspacePathError as exc:
            return f"ERROR: {exc}"

    def list_files() -> str:
        """List all file paths currently in the project workspace."""
        paths = workspace.list_paths()
        return "\n".join(paths) if paths else "(workspace is empty)"

    return [
        StructuredTool.from_function(write_file),
        StructuredTool.from_function(read_file),
        StructuredTool.from_function(list_files),
    ]
