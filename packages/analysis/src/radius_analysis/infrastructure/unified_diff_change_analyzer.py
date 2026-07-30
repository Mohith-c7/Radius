"""Deterministic parser for raw unified git diff text."""

from dataclasses import dataclass

from radius_shared.errors import ValidationError

from radius_analysis.dto.commands import ChangedFileInput

CHANGE_PRIORITY = {
    "modified": 0,
    "renamed": 1,
    "added": 2,
    "deleted": 3,
}


@dataclass(slots=True)
class _FileChange:
    path: str
    change_type: str = "modified"
    additions: int = 0
    deletions: int = 0


class UnifiedDiffChangeAnalyzer:
    """Parse unified git diffs into Radius changed-file inputs."""

    def analyze_diff(self, diff_text: str) -> tuple[ChangedFileInput, ...]:
        """Parse raw diff text into changed-file input records."""

        if not diff_text.strip():
            msg = "Diff text cannot be empty."
            raise ValidationError(msg)

        changes: dict[str, _FileChange] = {}
        current: _FileChange | None = None
        saw_block = False

        for raw_line in diff_text.splitlines():
            line = raw_line.rstrip("\n")
            if line.startswith("diff --git "):
                if current is not None:
                    self._merge(changes, current)
                current = self._start_change(line)
                saw_block = True
                continue

            if current is None:
                continue

            if line.startswith("new file mode"):
                current.change_type = "added"
            elif line.startswith("deleted file mode"):
                current.change_type = "deleted"
            elif line.startswith("rename to "):
                current.path = self._normalize_path(line.removeprefix("rename to "))
                current.change_type = "renamed"
            elif line.startswith("+++ "):
                path = self._normalize_path(line.removeprefix("+++ "))
                if path:
                    current.path = path
            elif line.startswith("--- ") and current.change_type == "deleted":
                path = self._normalize_path(line.removeprefix("--- "))
                if path:
                    current.path = path
            elif line.startswith("+") and not line.startswith("+++"):
                current.additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                current.deletions += 1

        if current is not None:
            self._merge(changes, current)

        if not saw_block:
            msg = "Diff text does not contain git file blocks."
            raise ValidationError(msg)

        return tuple(
            ChangedFileInput(
                path=change.path,
                change_type=change.change_type,
                additions=change.additions,
                deletions=change.deletions,
            )
            for change in sorted(changes.values(), key=lambda item: item.path)
        )

    def _start_change(self, line: str) -> _FileChange:
        parts = line.split()
        if len(parts) < 4:
            msg = f"Malformed git diff block header: {line}."
            raise ValidationError(msg)

        path = self._normalize_path(parts[3])
        if not path:
            path = self._normalize_path(parts[2])
        if not path:
            msg = f"Diff block does not contain a file path: {line}."
            raise ValidationError(msg)
        return _FileChange(path=path)

    @staticmethod
    def _normalize_path(path: str) -> str:
        value = path.strip().replace("\\", "/")
        if value == "/dev/null":
            return ""
        if value.startswith("a/") or value.startswith("b/"):
            return value[2:]
        return value

    @staticmethod
    def _merge(changes: dict[str, _FileChange], change: _FileChange) -> None:
        existing = changes.get(change.path)
        if existing is None:
            changes[change.path] = change
            return

        existing.additions += change.additions
        existing.deletions += change.deletions
        if CHANGE_PRIORITY[change.change_type] > CHANGE_PRIORITY[existing.change_type]:
            existing.change_type = change.change_type
