"""Semantic (symbol-level) diff between two versions of a set of files."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

from .extract import FileSymbols, detect_language, extract_symbols
from .manifests import diff_keys, is_config_file, is_dependency_manifest, parse_config, parse_dependencies, SECRET_KEY_RE

CATEGORY_TITLES = {
    "functions": "Functions",
    "classes": "Classes",
    "imports": "Imports",
    "apis": "APIs",
    "dependencies": "Dependencies",
    "configuration": "Configuration",
    "variables": "Module variables",
    "files": "Files",
}

_KIND_CATEGORY = {
    "function": "functions",
    "method": "functions",
    "class": "classes",
    "interface": "classes",
    "variable": "variables",
}

# Domain keywords are matched against *words* (camelCase/snake_case/path segments
# split apart) so that e.g. "AuthorizationContext" is not counted as authentication.
DOMAIN_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # (domain, exact words, word prefixes)
    ("Authentication", ("auth", "authn", "login", "logout", "jwt", "sso", "mfa", "oidc", "signin", "signup", "otp"),
     ("authenticat", "oauth", "password", "passwd", "credential", "token", "session")),
    ("Authorization", ("authz", "acl", "rbac", "role", "roles", "guard", "scope", "scopes"),
     ("authoriz", "permission", "privilege", "policy", "policies")),
    ("Database", ("db", "sql", "orm", "model", "models", "schema", "index", "cursor", "repository"),
     ("database", "query", "queries", "migration", "transaction", "sqlalchemy", "postgres", "sqlite", "prisma")),
    ("Security", ("csrf", "xss", "cors", "tls", "ssl", "secret", "secrets"),
     ("crypt", "secur", "sanitiz", "encrypt", "hmac", "signature")),
    ("API", ("api", "route", "routes", "router", "endpoint", "endpoints", "handler", "handlers", "views", "controller",
             "controllers"), ()),
    ("Tests", ("test", "tests", "spec", "specs", "conftest", "fixture", "fixtures"), ("test",)),
    ("Infrastructure", ("dockerfile", "docker", "k8s", "helm", "terraform", "ci", "workflows"), ("deploy",)),
]

_WORD_SPLIT = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_SPLIT.findall(text)]


def classify_domains(*texts: str) -> list[str]:
    tokens = set()
    for t in texts:
        if t:
            tokens.update(words(t))
    found = []
    for domain, exact, prefixes in DOMAIN_RULES:
        if tokens & set(exact) or any(tok.startswith(p) for tok in tokens for p in prefixes):
            found.append(domain)
    return found


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name.lower()
    return (
        name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js",
                                                   ".test.tsx", ".spec.tsx"))
        or any(part in ("tests", "test", "__tests__", "e2e") for part in p.parts[:-1])
    )


def is_migration_path(path: str) -> bool:
    lower = path.lower()
    return "migrations/" in lower or "alembic/versions" in lower or lower.endswith(".sql") and "migrat" in lower


@dataclass
class SemanticChange:
    kind: str
    category: str
    path: str
    description: str
    symbol: str | None = None
    symbol_kind: str | None = None
    line: int | None = None
    domains: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def symbol_id(self) -> str | None:
        return f"{self.path}::{self.symbol}" if self.symbol else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["symbol_id"] = self.symbol_id
        return d


@dataclass
class FileSemanticDiff:
    path: str
    status: str  # A | M | D
    language: str | None
    changes: list[SemanticChange]
    analyzed: bool = True
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "language": self.language,
            "analyzed": self.analyzed,
            "note": self.note,
            "changes": [c.to_dict() for c in self.changes],
        }


@dataclass
class SemanticDiff:
    files: list[FileSemanticDiff]

    @property
    def changes(self) -> list[SemanticChange]:
        return [c for f in self.files for c in f.changes]

    def groups(self) -> dict[str, list[SemanticChange]]:
        out: dict[str, list[SemanticChange]] = {k: [] for k in CATEGORY_TITLES}
        for c in self.changes:
            out.setdefault(c.category, []).append(c)
        return {k: v for k, v in out.items() if v}

    def domains(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for c in self.changes:
            for d in c.domains or ["General"]:
                out.setdefault(d, [])
                if c.description not in out[d]:
                    out[d].append(c.description)
        order = [d for d, *_ in DOMAIN_RULES] + ["Dependencies", "Configuration", "General"]
        return {d: out[d] for d in sorted(out, key=lambda d: order.index(d) if d in order else len(order))}

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.changes:
            out[c.kind] = out.get(c.kind, 0) + 1
        return dict(sorted(out.items()))

    def summary_text(self) -> str:
        lines = ["Semantic changes:"]
        for domain, items in self.domains().items():
            lines.append("")
            lines.append(domain)
            lines.extend(f"- {i}" for i in items)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "files": [f.to_dict() for f in self.files],
            "groups": {k: [c.to_dict() for c in v] for k, v in self.groups().items()},
            "domains": self.domains(),
            "stats": self.stats(),
        }


def _label(kind: str) -> str:
    return {"function": "function", "method": "method", "class": "class", "interface": "interface",
            "variable": "variable"}.get(kind, kind)


def _symbol_changes(path: str, old: FileSymbols | None, new: FileSymbols | None) -> list[SemanticChange]:
    changes: list[SemanticChange] = []
    old_syms = old.symbols if old else {}
    new_syms = new.symbols if new else {}
    file_domains = classify_domains(path)

    for name in sorted(set(old_syms) | set(new_syms)):
        o, n = old_syms.get(name), new_syms.get(name)
        sym = n or o
        assert sym is not None
        category = _KIND_CATEGORY.get(sym.kind, "functions")
        base_kind = "class" if category == "classes" else ("variable" if category == "variables" else "function")
        domains = sorted(set(file_domains) | set(classify_domains(name, *(sym.decorators or []))))
        if o is None:
            changes.append(SemanticChange(
                kind=f"{base_kind}_added", category=category, path=path, symbol=name, symbol_kind=sym.kind,
                line=n.start_line, domains=domains,
                description=f"Added {_label(sym.kind)} `{name}`" + (f"{n.signature}" if base_kind == "function" else "")
                + f" in {path}",
                details={"signature": n.signature},
            ))
        elif n is None:
            changes.append(SemanticChange(
                kind=f"{base_kind}_removed", category=category, path=path, symbol=name, symbol_kind=sym.kind,
                line=o.start_line, domains=domains,
                description=f"Removed {_label(sym.kind)} `{name}` from {path}",
                details={"signature": o.signature},
            ))
        elif o.body_hash != n.body_hash:
            sig_changed = o.signature != n.signature
            desc = f"Modified {_label(sym.kind)} `{name}` in {path}"
            if sig_changed and base_kind == "function":
                desc += f" (signature {o.signature} → {n.signature})"
            changes.append(SemanticChange(
                kind=f"{base_kind}_modified", category=category, path=path, symbol=name, symbol_kind=sym.kind,
                line=n.start_line, domains=domains, description=desc,
                details={"signature_changed": sig_changed, "old_signature": o.signature, "new_signature": n.signature,
                         "old_lines": [o.start_line, o.end_line], "new_lines": [n.start_line, n.end_line]},
            ))

    old_imports = {i.key: i for i in (old.imports if old else [])}
    new_imports = {i.key: i for i in (new.imports if new else [])}
    for key in sorted(set(new_imports) - set(old_imports)):
        imp = new_imports[key]
        what = f"{', '.join(imp.names)} from {imp.module}" if imp.names else imp.module
        changes.append(SemanticChange(
            kind="import_added", category="imports", path=path, line=imp.line,
            description=f"Added import {what} in {path}",
            domains=sorted(set(file_domains) | set(classify_domains(imp.module, *imp.names))),
            details={"module": imp.module, "names": list(imp.names)},
        ))
    for key in sorted(set(old_imports) - set(new_imports)):
        imp = old_imports[key]
        what = f"{', '.join(imp.names)} from {imp.module}" if imp.names else imp.module
        changes.append(SemanticChange(
            kind="import_removed", category="imports", path=path, line=imp.line,
            description=f"Removed import {what} in {path}",
            domains=sorted(set(file_domains) | set(classify_domains(imp.module, *imp.names))),
            details={"module": imp.module, "names": list(imp.names)},
        ))

    old_routes = {r.key: r for r in (old.routes if old else [])}
    new_routes = {r.key: r for r in (new.routes if new else [])}
    modified_symbols = {c.symbol for c in changes if c.kind.endswith("_modified")}
    for key in sorted(set(old_routes) | set(new_routes)):
        o, n = old_routes.get(key), new_routes.get(key)
        r = n or o
        assert r is not None
        domains = sorted({"API"} | set(file_domains) | set(classify_domains(r.path, r.handler or "")))
        details = {"method": r.method, "path": r.path, "handler": r.handler}
        if o is None:
            changes.append(SemanticChange(kind="route_added", category="apis", path=path, line=r.line,
                                          symbol=r.handler, description=f"Added route {key}", domains=domains,
                                          details=details))
        elif n is None:
            changes.append(SemanticChange(kind="route_removed", category="apis", path=path, line=r.line,
                                          symbol=r.handler, description=f"Removed route {key}", domains=domains,
                                          details=details))
        elif o.handler != n.handler or (n.handler and n.handler in modified_symbols):
            reason = f"handler `{n.handler}` modified" if o.handler == n.handler else \
                f"handler {o.handler} → {n.handler}"
            changes.append(SemanticChange(kind="route_changed", category="apis", path=path, line=r.line,
                                          symbol=n.handler, description=f"{key} changed ({reason})",
                                          domains=domains, details=details))
    return changes


def _dependency_changes(path: str, old: bytes | None, new: bytes | None) -> list[SemanticChange]:
    o, n = parse_dependencies(path, old), parse_dependencies(path, new)
    added, removed, changed = diff_keys(o, n)
    out = []
    for key in added:
        name = key.split(":", 1)[1]
        out.append(SemanticChange(kind="dependency_added", category="dependencies", path=path,
                                  description=f"Added {name} {n[key]}".rstrip(),
                                  domains=["Dependencies", *classify_domains(name)],
                                  details={"package": key, "version": n[key]}))
    for key in removed:
        name = key.split(":", 1)[1]
        out.append(SemanticChange(kind="dependency_removed", category="dependencies", path=path,
                                  description=f"Removed {name}", domains=["Dependencies", *classify_domains(name)],
                                  details={"package": key, "version": o[key]}))
    for key in changed:
        name = key.split(":", 1)[1]
        out.append(SemanticChange(kind="dependency_changed", category="dependencies", path=path,
                                  description=f"Changed {name} {o[key]} → {n[key]}",
                                  domains=["Dependencies", *classify_domains(name)],
                                  details={"package": key, "old_version": o[key], "version": n[key]}))
    return out


_DEP_KEY_PREFIXES = ("project.dependencies", "project.optional-dependencies", "tool.poetry.dependencies",
                     "dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def _config_changes(path: str, old: bytes | None, new: bytes | None) -> list[SemanticChange] | None:
    o, n = parse_config(path, old), parse_config(path, new)
    if o is None or n is None:
        return None
    added, removed, changed = diff_keys(o, n)
    out = []
    domains = sorted({"Configuration", *classify_domains(path)})
    for verb, keys in (("Added", added), ("Removed", removed), ("Changed", changed)):
        for key in keys:
            if key.startswith(_DEP_KEY_PREFIXES):
                continue
            sensitive = bool(SECRET_KEY_RE.search(key))
            out.append(SemanticChange(
                kind="config_changed", category="configuration", path=path,
                description=f"{verb} config key `{key}` in {path}",
                domains=sorted(set(domains) | set(classify_domains(key)) | ({"Security"} if sensitive else set())),
                details={"key": key, "change": verb.lower(), "sensitive": sensitive},
            ))
    return out


def file_semantic_diff(path: str, old: bytes | None, new: bytes | None) -> FileSemanticDiff:
    status = "A" if old is None else ("D" if new is None else "M")
    lang = detect_language(path)
    changes: list[SemanticChange] = []
    analyzed = True
    note = None

    if is_dependency_manifest(path):
        changes.extend(_dependency_changes(path, old, new))
    if is_config_file(path):
        cfg = _config_changes(path, old, new)
        if cfg is None:
            analyzed = False
            note = "configuration could not be parsed; file-level change only"
            changes.append(SemanticChange(kind="config_changed", category="configuration", path=path,
                                          description=f"Configuration file {path} changed",
                                          domains=["Configuration"]))
        else:
            changes.extend(cfg)
    elif lang is not None:
        old_fs = extract_symbols(path, old) if old is not None else None
        new_fs = extract_symbols(path, new) if new is not None else None
        changes.extend(_symbol_changes(path, old_fs, new_fs))
        if (new_fs and new_fs.parse_errors) or (old_fs and old_fs.parse_errors):
            note = "source contains syntax errors; symbol analysis may be incomplete"
    elif not is_dependency_manifest(path):
        analyzed = False

    if not changes:
        verb = {"A": "Added", "D": "Deleted", "M": "Modified"}[status]
        kind = {"A": "file_added", "D": "file_removed", "M": "file_modified"}[status]
        if lang is not None and status == "M":
            note = note or "no semantic change (formatting or comments only)"
        else:
            changes.append(SemanticChange(kind=kind, category="files", path=path, description=f"{verb} file {path}",
                                          domains=classify_domains(path)))
    if is_migration_path(path) and status != "D":
        for c in changes:
            if "Database" not in c.domains:
                c.domains.append("Database")
    return FileSemanticDiff(path=path, status=status, language=lang, changes=changes, analyzed=analyzed, note=note)


def semantic_diff(old_files: dict[str, bytes | None], new_files: dict[str, bytes | None]) -> SemanticDiff:
    """Compute the semantic diff for the given changed paths.

    ``old_files``/``new_files`` map path → content (``None`` when the file does not
    exist on that side). Only paths present in either mapping are analysed.
    """
    paths = sorted(set(old_files) | set(new_files))
    files = []
    for p in paths:
        o, n = old_files.get(p), new_files.get(p)
        if o == n:
            continue
        files.append(file_semantic_diff(p, o, n))
    return SemanticDiff(files=files)
