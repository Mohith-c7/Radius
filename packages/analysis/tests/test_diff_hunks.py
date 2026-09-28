"""Unit tests for git diff hunk line parser."""

from radius_analysis.diff_hunks import parse_diff_modified_lines


def test_single_line_modification() -> None:
    diff = """diff --git a/src/api.py b/src/api.py
index abc1234..def5678 100644
--- a/src/api.py
+++ b/src/api.py
@@ -10,3 +10,3 @@
 context line 9
-old line 10
+new line 10
 context line 11
"""
    result = parse_diff_modified_lines(diff)
    assert result == {"src/api.py": {11}}


def test_multi_line_addition_and_deletion() -> None:
    diff = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -20,6 +20,7 @@
 context 20
-deleted line 21
-deleted line 22
+added line 21
+added line 22
+added line 23
 context 24
"""
    result = parse_diff_modified_lines(diff)
    # Line 20 is context (current_line advances to 21).
    # Two deletions at position 21 mark line 21.
    # Three additions mark 21, 22, 23 (current_line advances to 24).
    assert result == {"src/service.py": {21, 22, 23}}


def test_deletion_only() -> None:
    diff = """diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -5,4 +5,2 @@
 context 5
-deleted line 6
-deleted line 7
 context 6 (originally 8)
"""
    result = parse_diff_modified_lines(diff)
    # Line 5 is context (advances to 6).
    # Deletions mark position 6.
    assert result == {"src/calc.py": {6}}


def test_multiple_files_in_one_diff() -> None:
    diff = """diff --git a/src/first.py b/src/first.py
--- a/src/first.py
+++ b/src/first.py
@@ -1,3 +1,4 @@
 line 1
+line 2
 line 3
 line 4
diff --git a/src/second.py b/src/second.py
--- a/src/second.py
+++ b/src/second.py
@@ -10,3 +10,2 @@
 line 10
-line 11
 line 11 (new position)
"""
    result = parse_diff_modified_lines(diff)
    assert result == {
        "src/first.py": {2},
        "src/second.py": {11},
    }


def test_multiple_hunks_in_same_file() -> None:
    diff = """diff --git a/src/multi.py b/src/multi.py
--- a/src/multi.py
+++ b/src/multi.py
@@ -5,2 +5,3 @@
 line 5
+line 6
 line 7
@@ -30,3 +31,3 @@
 line 31
-line 32
+line 32 updated
 line 33
"""
    result = parse_diff_modified_lines(diff)
    assert result == {"src/multi.py": {6, 32}}


def test_hunk_header_without_counts() -> None:
    diff = """diff --git a/src/single.py b/src/single.py
--- a/src/single.py
+++ b/src/single.py
@@ -1 +1 @@
-old
+new
"""
    result = parse_diff_modified_lines(diff)
    assert result == {"src/single.py": {1}}


def test_empty_or_non_diff_strings_returning_empty_dict() -> None:
    assert parse_diff_modified_lines("") == {}
    assert parse_diff_modified_lines("   \n\t  ") == {}
    assert parse_diff_modified_lines("This is just regular text\nnot a diff at all") == {}
    assert parse_diff_modified_lines(None) == {}  # type: ignore[arg-type]
