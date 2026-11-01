"""Filesystem source discovery adapter."""

from hashlib import sha256
from pathlib import Path

from radius_parser.domain.entities import SourceFile
from radius_parser.domain.enums import SourceLanguage
from radius_parser.domain.value_objects import FileChecksum, SourcePath

LANGUAGE_BY_SUFFIX = {
    ".py": SourceLanguage.PYTHON,
    ".ts": SourceLanguage.TYPESCRIPT,
    ".tsx": SourceLanguage.TYPESCRIPT,
    ".js": SourceLanguage.JAVASCRIPT,
    ".jsx": SourceLanguage.JAVASCRIPT,
    ".go": SourceLanguage.GO,
    ".java": SourceLanguage.JAVA,
    ".rs": SourceLanguage.RUST,
    ".json": SourceLanguage.JSON,
    ".md": SourceLanguage.MARKDOWN,
}

IGNORED_DIRECTORIES = {
    ".git",
    ".next",
    ".turbo",
    "__pycache__",
    "dist",
    "node_modules",
}


class FilesystemSourceDiscovery:
    """Discover source files from a local repository snapshot."""

    def discover(self, repository_path: Path) -> list[SourceFile]:
        """Return supported source files with stable checksums."""

        root = repository_path.resolve()
        discovered: list[SourceFile] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or self._is_ignored(path, root):
                continue

            language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
            if language is None:
                continue

            relative_path = path.relative_to(root).as_posix()
            discovered.append(
                SourceFile(
                    path=SourcePath(relative_path),
                    language=language,
                    checksum=FileChecksum(self._checksum(path)),
                    absolute_path=path,
                )
            )
        return discovered

    @staticmethod
    def _is_ignored(path: Path, root: Path) -> bool:
        relative_parts = path.relative_to(root).parts
        return any(part in IGNORED_DIRECTORIES for part in relative_parts)

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
