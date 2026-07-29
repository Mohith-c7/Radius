"""Unified diff change analyzer tests."""

import pytest
from radius_analysis.infrastructure import UnifiedDiffChangeAnalyzer
from radius_shared.errors import ValidationError


def test_analyze_diff_parses_modified_file_counts() -> None:
    changes = UnifiedDiffChangeAnalyzer().analyze_diff(
        """diff --git a/src/app.py b/src/app.py
index 111..222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
-old
+new
+added
 kept
"""
    )

    assert changes[0].path == "src/app.py"
    assert changes[0].change_type == "modified"
    assert changes[0].additions == 2
    assert changes[0].deletions == 1


def test_analyze_diff_parses_added_deleted_renamed_and_binary_files() -> None:
    changes = UnifiedDiffChangeAnalyzer().analyze_diff(
        """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+print("new")
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-print("old")
diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
diff --git a/assets/logo.png b/assets/logo.png
index 111..222 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
"""
    )

    result = [
        (item.path, item.change_type, item.additions, item.deletions)
        for item in changes
    ]
    assert result == [
        ("assets/logo.png", "modified", 0, 0),
        ("new.py", "added", 1, 0),
        ("new_name.py", "renamed", 0, 0),
        ("old.py", "deleted", 0, 1),
    ]


def test_analyze_diff_merges_duplicate_blocks_deterministically() -> None:
    changes = UnifiedDiffChangeAnalyzer().analyze_diff(
        """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old
+new
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -3 +3,2 @@
+another
"""
    )

    assert len(changes) == 1
    assert changes[0].path == "src/app.py"
    assert changes[0].additions == 2
    assert changes[0].deletions == 1


def test_analyze_diff_rejects_empty_or_malformed_diff() -> None:
    analyzer = UnifiedDiffChangeAnalyzer()

    with pytest.raises(ValidationError, match="cannot be empty"):
        analyzer.analyze_diff("")

    with pytest.raises(ValidationError, match="does not contain git file blocks"):
        analyzer.analyze_diff("@@ -1 +1 @@\n+orphan\n")
