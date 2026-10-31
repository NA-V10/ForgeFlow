"""Conservative symbol dependency graph.

Symbol ids are ``"<path>::<qualified name>"``. An edge ``A → B`` means the body of
A references an identifier that resolves to B. Resolution order, most precise first:

1. a method of the same class (``self.foo`` / ``this.foo``)
2. a symbol defined at the top level of the same file
3. a name imported from another repository file that defines it
4. a name defined at top level in exactly one file in the repository

Anything ambiguous is left unresolved rather than guessed.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

from .extract import FileSymbols, extract_symbols

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


@dataclass
class DependencyGraph:
    files: dict[str, FileSymbols]
    edges: dict[str, set[str]] = field(default_factory=dict)  # symbol → symbols it depends on

    def dependents_of(self, symbol_id: str) -> set[str]:
        return {s for s, deps in self.edges.items() if symbol_id in deps}

    def dependencies_of(self, symbol_id: str) -> set[str]:
        return set(self.edges.get(symbol_id, set()))

    def symbol(self, symbol_id: str):
        path, _, name = symbol_id.partition("::")
        fs = self.files.get(path)
        return fs.symbols.get(name) if fs else None

    def to_dict(self) -> dict:
        return {
            "nodes": [
                {"id": f"{p}::{n}", "path": p, "name": n, "kind": s.kind}
                for p, fs in sorted(self.files.items()) for n, s in sorted(fs.symbols.items())
            ],
            "edges": [{"from": a, "to": b} for a in sorted(self.edges) for b in sorted(self.edges[a])],
        }


def _python_module_candidates(importer: str, module: str) -> list[str]:
    if module.startswith("."):
        level = len(module) - len(module.lstrip("."))
        base = posixpath.dirname(importer)
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        rest = module.lstrip(".").replace(".", "/")
        stem = posixpath.join(base, rest) if rest else base
    else:
        stem = module.replace(".", "/")
    return [f"{stem}.py", f"{stem}/__init__.py", f"src/{stem}.py", f"src/{stem}/__init__.py"]


def _js_module_candidates(importer: str, module: str) -> list[str]:
    if not module.startswith("."):
        return []
    stem = posixpath.normpath(posixpath.join(posixpath.dirname(importer), module))
    cands = [stem] + [stem + e for e in _JS_EXTS] + [f"{stem}/index{e}" for e in _JS_EXTS]
    if stem.endswith(".js"):
        cands += [stem[:-3] + e for e in (".ts", ".tsx")]
    return cands


def resolve_module(importer: str, language: str, module: str, available: set[str]) -> str | None:
    cands = _python_module_candidates(importer, module) if language == "python" else _js_module_candidates(importer, module)
    return next((c for c in cands if c in available), None)


def build_dependency_graph(files: dict[str, bytes]) -> DependencyGraph:
    parsed: dict[str, FileSymbols] = {}
    for path, content in files.items():
        fs = extract_symbols(path, content)
        if fs is not None:
            parsed[path] = fs
    available = set(parsed)

    # name → files defining it at top level (for the uniqueness fallback)
    global_defs: dict[str, list[str]] = {}
    for path, fs in parsed.items():
        for name, sym in fs.symbols.items():
            if sym.parent is None:
                global_defs.setdefault(name, []).append(path)

    edges: dict[str, set[str]] = {}
    for path, fs in parsed.items():
        imported: dict[str, str] = {}  # local name → symbol id
        imported_modules: dict[str, str] = {}  # local alias → file
        for imp in fs.imports:
            target = resolve_module(path, fs.language, imp.module, available)
            if target is None:
                continue
            target_syms = parsed[target].symbols
            alias_map = dict(imp.aliases)
            reverse = {orig: local for local, orig in imp.aliases}
            for name in imp.names:
                if name == "*":
                    for n, s in target_syms.items():
                        if s.parent is None:
                            imported[n] = f"{target}::{n}"
                elif name in target_syms:
                    imported[reverse.get(name, name)] = f"{target}::{name}"
            if not imp.names:
                local = next(iter(alias_map), imp.module.split(".")[-1])
                imported_modules[local] = target

        for name, sym in fs.symbols.items():
            sid = f"{path}::{name}"
            deps: set[str] = set()
            for ref in sym.references:
                if sym.parent and f"{sym.parent}.{ref}" in fs.symbols:
                    deps.add(f"{path}::{sym.parent}.{ref}")
                elif ref in fs.symbols and fs.symbols[ref].parent is None:
                    deps.add(f"{path}::{ref}")
                elif ref in imported:
                    deps.add(imported[ref])
                elif ref in imported_modules:
                    continue  # the module itself; attribute names resolve below
                elif len(global_defs.get(ref, [])) == 1:
                    deps.add(f"{global_defs[ref][0]}::{ref}")
            deps.discard(sid)
            if sym.parent:
                deps.discard(f"{path}::{sym.parent}")
            if deps:
                edges[sid] = deps
    return DependencyGraph(files=parsed, edges=edges)
