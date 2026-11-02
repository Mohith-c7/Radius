"""LK-01: unified diff parser edge cases."""

from __future__ import annotations

from radius_analysis.symbol_changes import FileStatus, parse_unified_diff
from radius_analysis.symbol_changes.diff_files import _unquote


def test_empty_and_whitespace_inputs() -> None:
    assert parse_unified_diff("") == []
    assert parse_unified_diff("  \n\n") == []


def test_modified_file_with_two_hunks_and_default_counts() -> None:
    diff = (
        "diff --git a/x.py b/x.py\nindex 1..2 100644\n--- a/x.py\n+++ b/x.py\n"
        "@@ -1 +1 @@\n-a\n+b\n"
        "@@ -10,2 +10,3 @@ def f():\n ctx\n+new\n ctx2\n"
    )
    (fd,) = parse_unified_diff(diff)
    assert (fd.old_path, fd.new_path, fd.status) == ("x.py", "x.py", FileStatus.MODIFIED)
    assert [(h.old_start, h.old_count, h.new_start, h.new_count) for h in fd.hunks] == [
        (1, 1, 1, 1),
        (10, 2, 10, 3),
    ]
    assert fd.hunks[0].deleted == [1]
    assert fd.hunks[0].added == [1]
    assert fd.hunks[1].added == [11]


def test_added_deleted_and_binary_files() -> None:
    diff = (
        "diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n"
        "@@ -0,0 +1,2 @@\n+a\n+b\n"
        "diff --git a/old.py b/old.py\ndeleted file mode 100644\n--- a/old.py\n+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n-a\n-b\n"
        "diff --git a/img.png b/img.png\nindex 1..2 100644\nBinary files a/img.png and b/img.png differ\n"
        "diff --git a/blob.bin b/blob.bin\nnew file mode 100644\nGIT binary patch\nliteral 3\nabc\n"
    )
    new, old, img, blob = parse_unified_diff(diff)
    assert (new.status, new.old_path, new.new_path) == (FileStatus.ADDED, None, "new.py")
    assert (old.status, old.old_path, old.new_path) == (FileStatus.DELETED, "old.py", None)
    assert img.binary and not img.hunks
    assert blob.binary and blob.status is FileStatus.ADDED


def test_rename_with_and_without_edit_and_copy() -> None:
    diff = (
        "diff --git a/a.py b/b.py\nsimilarity index 100%\nrename from a.py\nrename to b.py\n"
        "diff --git a/c.py b/d.py\nsimilarity index 80%\nrename from c.py\nrename to d.py\n"
        "--- a/c.py\n+++ b/d.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/e.py b/f.py\nsimilarity index 90%\ncopy from e.py\ncopy to f.py\n"
    )
    pure, edited, copied = parse_unified_diff(diff)
    assert (pure.status, pure.old_path, pure.new_path, pure.similarity) == (
        FileStatus.RENAMED, "a.py", "b.py", 100
    )
    assert edited.status is FileStatus.RENAMED and len(edited.hunks) == 1
    assert (copied.status, copied.old_path, copied.new_path) == (FileStatus.COPIED, "e.py", "f.py")


def test_mode_only_change() -> None:
    diff = "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
    (fd,) = parse_unified_diff(diff)
    assert fd.mode_only and "mode_only_change" in fd.notes and not fd.hunks


def test_deleted_line_that_looks_like_a_file_header_is_not_a_header() -> None:
    diff = (
        "diff --git a/x.sql b/x.sql\n--- a/x.sql\n+++ b/x.sql\n@@ -1,2 +1,1 @@\n"
        "--- comment\n keep\n"
    )
    (fd,) = parse_unified_diff(diff)
    assert [ln.tag for ln in fd.hunks[0].lines] == ["-", " "]
    assert fd.hunks[0].lines[0].text == "-- comment"


def test_no_newline_marker_and_crlf_content_are_preserved() -> None:
    diff = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n"
        " a\r\n-b\r\n\\ No newline at end of file\n+c\r\n\\ No newline at end of file\n"
    )
    (fd,) = parse_unified_diff(diff)
    assert [(ln.tag, ln.text) for ln in fd.hunks[0].lines] == [
        (" ", "a\r"),
        ("-", "b\r"),
        ("+", "c\r"),
    ]


def test_quoted_and_unicode_and_space_paths() -> None:
    diff = (
        'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n'
        '--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n@@ -1 +1 @@\n-a\n+b\n'
        "diff --git a/dir with space/m.py b/dir with space/m.py\nindex 1..2 100644\n"
        "--- a/dir with space/m.py\n+++ b/dir with space/m.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    first, second = parse_unified_diff(diff)
    assert first.path == "café.py"
    assert second.path == "dir with space/m.py"
    assert _unquote('"a\\tb\\"c\\\\"') == 'a\tb"c\\'
    assert _unquote("plain") == "plain"


def test_header_only_diff_with_spaces_uses_symmetric_split() -> None:
    (fd,) = parse_unified_diff("diff --git a/a b/x.py b/a b/x.py\nold mode 100644\nnew mode 100755\n")
    assert fd.path == "a b/x.py"


def test_plain_unified_diff_without_git_header_and_leading_junk() -> None:
    diff = (
        "From: someone\nSubject: [PATCH] x\n\n---\n"
        "--- a/p.py\t2020-01-01\n+++ b/p.py\t2020-01-02\n@@ -1 +1 @@\n-a\n+b\n"
        "--- a/q.py\n+++ b/q.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    first, second = parse_unified_diff(diff)
    assert (first.path, second.path) == ("p.py", "q.py")


def test_truncated_hunk_is_noted_not_fatal() -> None:
    diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,5 +1,5 @@\n a\n-b\ngarbage\n"
    (fd,) = parse_unified_diff(diff)
    assert "hunk_0_truncated" in fd.notes
    assert len(fd.hunks[0].lines) == 2


def test_combined_diff_is_flagged_unsupported() -> None:
    (fd,) = parse_unified_diff("diff --cc x.py\nindex 1,2..3\n--- a/x.py\n+++ b/x.py\n@@@ -1 -1 +1 @@@\n")
    assert "combined_diff_unsupported" in fd.notes
