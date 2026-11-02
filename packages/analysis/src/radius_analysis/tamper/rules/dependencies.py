"""T012: hallucinated or unverifiable dependencies (offline first; registry behind a port)."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import PurePosixPath

from radius_analysis.tamper.classify import Role
from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.model import CheckSpec, Family, Finding, RuleDoc, Severity
from radius_analysis.tamper.rules.base import BaseRule
from radius_analysis.tamper.rules.popular import ALIASES, POPULAR

_SEP = re.compile(r"[-_.]+")
_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;#]*)")
_TEST_ONLY = frozenset({"hypothesis", "coverage", "mock", "freezegun", "responses", "nose"})
_LOCKS = ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock")


def _dir(path: PurePosixPath) -> str:
    text = path.as_posix()
    return "" if text == "." else text


def normalize_name(name: str) -> str:
    """PEP 503 normalisation."""
    return _SEP.sub("-", name).lower()


def parse_requirements(text: str) -> dict[str, str]:
    """``{normalized name: version spec}`` of a requirements file (best effort)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "git+", "http://", "https://", ".", "/")):
            continue
        m = _REQ.match(line)
        if m:
            out[normalize_name(m.group(1))] = m.group(3).strip()
    return out


def _spec_name(spec: str) -> str | None:
    m = _REQ.match(spec)
    return normalize_name(m.group(1)) if m else None


def parse_pyproject(text: str) -> dict[str, str]:
    """Dependencies declared in ``pyproject.toml`` (PEP 621, groups, poetry)."""
    data = tomllib.loads(text)
    out: dict[str, str] = {}

    def add_specs(specs: object) -> None:
        for s in specs if isinstance(specs, list) else []:
            if isinstance(s, str) and (n := _spec_name(s)):
                out[n] = s

    project = data.get("project", {})
    add_specs(project.get("dependencies"))
    for group in (project.get("optional-dependencies") or {}).values():
        add_specs(group)
    for group in (data.get("dependency-groups") or {}).values():
        add_specs(group)
    poetry = data.get("tool", {}).get("poetry", {})
    tables = [poetry.get("dependencies") or {}, poetry.get("dev-dependencies") or {}]
    tables += [g.get("dependencies") or {} for g in (poetry.get("group") or {}).values()]
    for table in tables:
        for name, spec in table.items():
            if name.lower() != "python":
                out[normalize_name(name)] = str(spec)
    return out


def parse_lock_names(name: str, text: str) -> set[str]:
    if name == "Pipfile.lock":
        data = json.loads(text)
        return {normalize_name(k) for sec in ("default", "develop") for k in data.get(sec, {})}
    data = tomllib.loads(text)
    return {normalize_name(p["name"]) for p in data.get("package", []) if "name" in p}


def manifest_deps(view_path: str, text: str) -> dict[str, str]:
    name = PurePosixPath(view_path).name.lower()
    if name == "pyproject.toml":
        return parse_pyproject(text)
    return parse_requirements(text)


def edit_distance(a: str, b: str, limit: int = 2) -> int:
    """Levenshtein distance, early exit above ``limit`` (names are short)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def dist_for_module(module: str) -> str:
    top = module.split(".")[0]
    return ALIASES.get(top, normalize_name(top))


def _guarded_imports(tree: ast.AST) -> set[str]:
    """Distribution names imported inside ``try`` blocks that catch ImportError."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches = any(
            h.type is None or any(
                n in ast.unparse(h.type) for n in ("ImportError", "ModuleNotFoundError", "Exception")
            )
            for h in node.handlers
        )
        if not catches:
            continue
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Import):
                    found.update(dist_for_module(a.name) for a in sub.names)
                elif isinstance(sub, ast.ImportFrom) and sub.module and sub.level == 0:
                    found.add(dist_for_module(sub.module))
    return found


class DependencyRule(BaseRule):
    id = "T012"
    family = Family.DEPENDENCY
    languages = frozenset({"python", "*"})
    checks = {
        "registry_missing": CheckSpec(Severity.HIGH, "registry port reports the package does not exist"),
        "typosquat": CheckSpec(Severity.HIGH, "new dependency one edit away from a popular package"),
        "unverified_guarded_import": CheckSpec(
            Severity.HIGH,
            "new unlocked dependency whose import is wrapped in try/except ImportError",
        ),
        "lockfile_drift": CheckSpec(Severity.MEDIUM, "new dependency missing from the lockfile"),
        "unverified_new_dependency": CheckSpec(
            Severity.MEDIUM, "new dependency that cannot be verified offline"
        ),
        "undeclared_import": CheckSpec(
            Severity.MEDIUM, "new import of a third-party package declared nowhere"
        ),
    }
    doc = RuleDoc(
        title="Hallucinated or unverifiable dependency",
        rationale="AI-generated code invents plausible package names. A new dependency that is "
        "not in the lockfile, not a well-known package, or imported only behind try/except "
        "ImportError may not exist (supply-chain risk) while the tests stay green.",
        example_before="# runtime dependencies: none",
        example_after="pytimeparse-ultra==3.1.4",
        limitations="Offline mode cannot prove a package does not exist: unknown but real "
        "packages are reported with low confidence (0.4) unless a lockfile covers them. The "
        "popular-package list is small and bundled. A registry lookup runs only when "
        "`params.use_registry` is true AND a registry port is injected; no network adapter "
        "ships with EV-02.",
        maps_to="T012",
    )

    def evaluate(self, context: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        guarded = self._guarded(context)
        for view in context.views(Role.MANIFEST):
            name = PurePosixPath(view.path).name.lower()
            if name in ("setup.py", "package.json", "pipfile") or view.head_text is None:
                continue
            out.extend(self._manifest(context, view, guarded))
        out.extend(self._undeclared(context))
        return out

    # ---------------------------------------------------------------- helpers

    def _guarded(self, ctx: TamperContext) -> dict[str, str]:
        found: dict[str, str] = {}
        for view in ctx.views(python_only=True):
            tree = ctx.tree_of(view, "head")
            if tree is None or not view.has(Role.SOURCE, Role.TEST, Role.CONFTEST):
                continue
            for dist in _guarded_imports(tree):
                found.setdefault(dist, view.path)
        return found

    def _lock_names(self, ctx: TamperContext, directory: str) -> set[str] | None:
        for lock in _LOCKS:
            path = f"{directory}/{lock}".lstrip("/")
            text = ctx.read_head(path)
            if text is not None:
                try:
                    return parse_lock_names(lock, text)
                except (ValueError, KeyError, tomllib.TOMLDecodeError):
                    ctx.mark_unanalyzable(path, "head", "lockfile_parse_error")
        return None

    def _manifest(self, ctx: TamperContext, view: FileView, guarded: dict[str, str]) -> list[Finding]:
        try:
            head = manifest_deps(view.path, view.head_text or "")
            base = manifest_deps(view.path, view.base_text or "") if view.base_text else {}
        except (ValueError, tomllib.TOMLDecodeError):
            ctx.mark_unanalyzable(view.path, "head", "manifest_parse_error")
            return []
        directory = _dir(PurePosixPath(view.path).parent)
        locked = self._lock_names(ctx, directory)
        out: list[Finding] = []
        for dep in sorted(set(head) - set(base)):
            finding = self._judge(ctx, view, dep, head[dep], locked, guarded)
            if finding:
                out.append(finding)
        return out

    def _line_of(self, view: FileView, dep: str) -> int:
        for n, text in sorted(view.added.items()):
            m = _REQ.match(text.strip().strip("\"',"))
            if m and normalize_name(m.group(1)) == dep:
                return n
        return min(view.added) if view.added else 1

    def _judge(
        self, ctx: TamperContext, view: FileView, dep: str, spec: str,
        locked: set[str] | None, guarded: dict[str, str],
    ) -> Finding | None:
        line = self._line_of(view, dep)
        shown = f"{dep}{(' ' + spec) if spec and not spec.startswith(dep) else ''}".strip()
        new = view.added.get(line, shown)
        kwargs = dict(new_range=(line, line), new=new)
        if ctx.config.params.use_registry and ctx.registry is not None:
            exists = ctx.registry.exists(dep)
            if exists is False:
                return ctx.finding(
                    self, "registry_missing", view.path,
                    f"new dependency `{dep}` does not exist on the package registry",
                    confidence=0.95, evidence=("registry:not_found",), **kwargs,
                )
            if exists is True:
                return None
        if dep in POPULAR:
            return None
        if locked is not None and dep in locked:
            return None
        if len(dep) >= 5:
            for known in POPULAR:
                if known != dep and edit_distance(dep, known, ctx.config.params.typosquat_max_distance) \
                        <= ctx.config.params.typosquat_max_distance:
                    return ctx.finding(
                        self, "typosquat", view.path,
                        f"new dependency `{dep}` is one edit away from popular package `{known}`",
                        confidence=0.7, evidence=(f"similar_to:{known}",), **kwargs,
                    )
        if dep in guarded:
            return ctx.finding(
                self, "unverified_guarded_import", view.path,
                f"new dependency `{dep}` is not in a lockfile or the known-package list and its "
                f"import in `{guarded[dep]}` is wrapped in try/except ImportError, so a missing "
                "package would go unnoticed; verify it exists on the registry",
                confidence=0.65, evidence=(f"guarded_import:{guarded[dep]}",), **kwargs,
            )
        if locked is not None:
            return ctx.finding(
                self, "lockfile_drift", view.path,
                f"new dependency `{dep}` is declared but missing from the lockfile",
                confidence=0.7, evidence=("lockfile:missing",), **kwargs,
            )
        return ctx.finding(
            self, "unverified_new_dependency", view.path,
            f"new dependency `{dep}` cannot be verified offline (no lockfile entry, not a "
            "well-known package)",
            confidence=0.4, **kwargs,
        )

    def _declared(self, ctx: TamperContext, directories: list[str]) -> tuple[set[str], bool]:
        names: set[str] = set()
        seen_manifest = False
        for d in directories:
            for fname in ("requirements.txt", "requirements-dev.txt", "requirements-test.txt",
                          "pyproject.toml"):
                text = ctx.read_head(f"{d}/{fname}".lstrip("/"))
                if text is None:
                    continue
                try:
                    names.update(manifest_deps(fname, text))
                    seen_manifest = True
                except (ValueError, tomllib.TOMLDecodeError):
                    continue
            lock = self._lock_names(ctx, d)
            if lock:
                names.update(lock)
        return names, seen_manifest

    def _source_roots(self, ctx: TamperContext) -> list[str]:
        """Import roots declared by the project (pytest ``pythonpath``, setuptools layout)."""
        cached = ctx.source_roots
        if cached is not None:
            return cached
        roots: list[str] = []
        text = ctx.read_head("pyproject.toml")
        if text:
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                data = {}
            tool = data.get("tool", {})
            roots += list(tool.get("pytest", {}).get("ini_options", {}).get("pythonpath", []) or [])
            setuptools = tool.get("setuptools", {})
            roots += list((setuptools.get("package-dir") or {}).values())
            packages = setuptools.get("packages")
            if isinstance(packages, dict):
                roots += list(packages.get("find", {}).get("where", []) or [])
        ini = ctx.read_head("pytest.ini")
        if ini:
            m = re.search(r"^pythonpath\s*=\s*(.*(?:\n[ \t]+.*)*)", ini, re.MULTILINE)
            if m:
                roots += m.group(1).split()
        clean = [r.strip("/").removeprefix("./") for r in roots if isinstance(r, str)]
        ctx.source_roots = clean
        return clean

    def _is_local(self, ctx: TamperContext, module: str, file_path: str) -> bool:
        top = module.split(".")[0]
        parents = [("" if str(p) == "." else str(p)) for p in PurePosixPath(file_path).parents]
        roots = {"", "src", "lib", *parents, *self._source_roots(ctx)}
        roots |= {f"{p}/src" if p else "src" for p in parents}
        for r in sorted(roots):
            prefix = f"{r}/" if r else ""
            if ctx.head_exists(f"{prefix}{top}.py") or ctx.head_exists(f"{prefix}{top}/__init__.py"):
                return True
        return any(
            v.path.startswith((f"{top}/", f"src/{top}/")) or v.path.endswith(f"/{top}.py")
            for v in ctx.files.values()
        )

    def _undeclared(self, ctx: TamperContext) -> list[Finding]:
        out: list[Finding] = []
        stdlib = sys.stdlib_module_names
        cache: dict[str, tuple[set[str], bool]] = {}
        for view in ctx.views(python_only=True):
            if not view.has(Role.SOURCE, Role.TEST, Role.CONFTEST):
                continue
            tree = ctx.tree_of(view, "head")
            if tree is None:
                continue
            base_tree = ctx.tree_of(view, "base")
            base_imports = {ast.unparse(n) for n in ast.walk(base_tree) if isinstance(n, ast.Import | ast.ImportFrom)} \
                if base_tree else set()
            guarded = _guarded_imports(tree)
            dirs = sorted({_dir(p) for p in PurePosixPath(view.path).parents})
            key = "|".join(dirs)
            if key not in cache:
                cache[key] = self._declared(ctx, dirs)
            declared, has_manifest = cache[key]
            if not has_manifest:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Import | ast.ImportFrom) or node.lineno not in view.added:
                    continue
                if ast.unparse(node) in base_imports:
                    continue
                modules = (
                    [a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module] if node.module and node.level == 0 else []
                )
                for module in modules:
                    top = module.split(".")[0]
                    dist = dist_for_module(module)
                    if view.has(Role.TEST, Role.CONFTEST) and (
                        dist.startswith("pytest") or dist in _TEST_ONLY
                    ):
                        continue
                    if (top in stdlib or top == "__future__" or dist in declared
                            or normalize_name(top) in declared or dist in guarded
                            or self._is_local(ctx, module, view.path)):
                        continue
                    out.append(ctx.finding(
                        self, "undeclared_import", view.path,
                        f"`import {module}` is not stdlib, not a local module and not declared "
                        "in any manifest or lockfile",
                        new_range=(node.lineno, node.lineno), new=ast.unparse(node), confidence=0.6,
                        evidence=(f"distribution:{dist}",),
                    ))
        return out
