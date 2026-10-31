"""Deterministic symbol extraction with Tree-sitter.

For every supported source file we extract top-level functions, classes, methods,
module-level variables, imports and HTTP routes. Each symbol carries a
*normalized token hash* (comments and formatting are ignored), a signature and
the set of identifiers it references; those feed the semantic diff and the
dependency graph.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

from tree_sitter import Language, Node, Parser

ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "route", "api_route", "all"}

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}


def detect_language(path: str) -> str | None:
    lower = path.lower()
    for ext, lang in LANGUAGE_BY_EXT.items():
        if lower.endswith(ext):
            return lang
    return None


@lru_cache(maxsize=None)
def _parser(lang: str) -> Parser:
    if lang == "python":
        import tree_sitter_python as mod

        language = Language(mod.language())
    elif lang == "javascript":
        import tree_sitter_javascript as mod

        language = Language(mod.language())
    elif lang in ("typescript", "tsx"):
        import tree_sitter_typescript as mod

        language = Language(mod.language_tsx() if lang == "tsx" else mod.language_typescript())
    else:  # pragma: no cover - guarded by detect_language
        raise ValueError(lang)
    return Parser(language)


@dataclass
class Symbol:
    kind: str  # function | method | class | interface | variable
    name: str  # qualified within file, e.g. "AuthContext.login"
    start_line: int
    end_line: int
    body_hash: str
    signature: str = ""
    references: set[str] = field(default_factory=set)
    parent: str | None = None
    decorators: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Import:
    module: str
    names: tuple[str, ...]  # imported names ("*" for wildcard, alias resolved to original)
    aliases: tuple[tuple[str, str], ...] = ()  # (local, original)
    line: int = 0

    @property
    def key(self) -> str:
        return f"{self.module}:{','.join(self.names)}" if self.names else self.module


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: str | None
    line: int

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


@dataclass
class FileSymbols:
    path: str
    language: str
    symbols: dict[str, Symbol]
    imports: list[Import]
    routes: list[Route]
    parse_errors: bool = False


def _text(node: Node | None, src: bytes) -> str:
    if node is None:
        return ""
    return src[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _tokens(node: Node, src: bytes, skip: set[int] | None = None) -> list[str]:
    """Leaf tokens of a node, ignoring comments and any node ids in ``skip``."""
    out: list[str] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if skip and n.id in skip:
            continue
        if n.type == "comment":
            continue
        if n.child_count == 0:
            out.append(_text(n, src))
        else:
            stack.extend(reversed(n.children))
    return out


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _hash_tokens(tokens: list[str]) -> str:
    return hashlib.sha256("\x00".join(tokens).encode()).hexdigest()[:16]


_IDENT_TYPES = {"identifier", "property_identifier", "type_identifier", "shorthand_property_identifier"}


def _identifiers(node: Node | None, src: bytes, skip: set[int] | None = None) -> set[str]:
    out: set[str] = set()
    if node is None:
        return out
    stack = [node]
    while stack:
        n = stack.pop()
        if skip and n.id in skip:
            continue
        if n.type in _IDENT_TYPES:
            out.add(_text(n, src))
        stack.extend(n.children)
    return out


def _string_value(node: Node | None, src: bytes) -> str | None:
    if node is None:
        return None
    if node.type in ("string", "template_string"):
        raw = _text(node, src)
        # strip prefixes like f/r/b and quotes
        raw = raw.lstrip("rbfuRBFU")
        for q in ('"""', "'''", '"', "'", "`"):
            if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
                return raw[len(q) : -len(q)]
    return None


_PATTERN_TYPES = {"pattern_list", "tuple_pattern", "list_pattern", "list_splat_pattern", "as_pattern_target",
                  "parenthesized_expression", "tuple", "list"}


def _bound_names(target: Node | None, src: bytes) -> set[str]:
    """Identifiers bound by an assignment target (not attributes or subscripts)."""
    if target is None:
        return set()
    if target.type == "identifier":
        return {_text(target, src)}
    if target.type in _PATTERN_TYPES:
        out: set[str] = set()
        for c in target.named_children:
            out |= _bound_names(c, src)
        return out
    return set()


def _py_local_names(body: Node | None, src: bytes) -> set[str]:
    """Names bound inside a function body, so a local `orders = ...` is not mistaken for a global symbol."""
    out: set[str] = set()
    if body is None:
        return out
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type in ("assignment", "augmented_assignment", "for_statement", "for_in_clause"):
            out |= _bound_names(n.child_by_field_name("left"), src)
        elif n.type == "named_expression":
            out |= _bound_names(n.child_by_field_name("name"), src)
        elif n.type == "as_pattern_target":
            out |= _bound_names(n, src)
        stack.extend(n.named_children)
    return out


def _js_local_names(body: Node | None, src: bytes) -> set[str]:
    out: set[str] = set()
    if body is None:
        return out
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type == "variable_declarator":
            name = n.child_by_field_name("name")
            if name is not None and name.type == "identifier":
                out.add(_text(name, src))
        stack.extend(n.named_children)
    return out


# --------------------------------------------------------------------- python
def _py_params(node: Node, src: bytes) -> set[str]:
    params = node.child_by_field_name("parameters")
    names: set[str] = set()
    if params is None:
        return names
    for child in params.named_children:
        if child.type == "identifier":
            names.add(_text(child, src))
        else:
            name = child.child_by_field_name("name")
            if name is None:
                for c in child.named_children:
                    if c.type == "identifier":
                        name = c
                        break
            if name is not None:
                names.add(_text(name, src))
    return names


def _py_route(decorator: Node, src: bytes, handler: str) -> list[Route]:
    call = next((c for c in decorator.named_children if c.type == "call"), None)
    if call is None:
        return []
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "attribute":
        return []
    attr = _text(fn.child_by_field_name("attribute"), src)
    if attr not in ROUTE_METHODS:
        return []
    args = call.child_by_field_name("arguments")
    if args is None:
        return []
    path = None
    methods: list[str] = []
    for arg in args.named_children:
        if path is None and arg.type == "string":
            path = _string_value(arg, src)
        elif arg.type == "keyword_argument" and _text(arg.child_by_field_name("name"), src) == "methods":
            value = arg.child_by_field_name("value")
            if value is not None:
                methods = [(_string_value(s, src) or "").upper() for s in value.named_children if s.type == "string"]
    if path is None:
        return []
    if attr in ("route", "api_route"):
        methods = methods or ["GET"]
    else:
        methods = [attr.upper()]
    line = decorator.start_point[0] + 1
    return [Route(method=m, path=path, handler=handler, line=line) for m in methods]


def _extract_python(root: Node, src: bytes, fs: FileSymbols) -> None:
    def handle_def(node: Node, decorators: list[Node], parent: str | None) -> None:
        name_node = node.child_by_field_name("name")
        name = _text(name_node, src)
        qual = f"{parent}.{name}" if parent else name
        deco_text = [_text(d, src) for d in decorators]
        outer = decorators[0] if decorators else node
        if node.type == "function_definition":
            params = node.child_by_field_name("parameters")
            ret = node.child_by_field_name("return_type")
            sig = _collapse(_text(params, src)) if params else "()"
            if ret is not None:
                sig += " -> " + _collapse(_text(ret, src))
            refs = _identifiers(node.child_by_field_name("body"), src) | _identifiers(ret, src) | _identifiers(params, src)
            for d in decorators:
                refs |= _identifiers(d, src)
            refs -= _py_params(node, src) | _py_local_names(node.child_by_field_name("body"), src)
            refs.discard(name)
            tokens = [*(t for d in decorators for t in _tokens(d, src)), *_tokens(node, src)]
            fs.symbols[qual] = Symbol(
                kind="method" if parent else "function",
                name=qual,
                start_line=outer.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                body_hash=_hash_tokens(tokens),
                signature=sig,
                references=refs,
                parent=parent,
                decorators=deco_text,
            )
            for d in decorators:
                fs.routes.extend(_py_route(d, src, qual))
        else:  # class_definition
            body = node.child_by_field_name("body")
            supers = node.child_by_field_name("superclasses")
            method_nodes: list[tuple[Node, list[Node]]] = []
            skip: set[int] = set()
            if body is not None:
                for child in body.named_children:
                    if child.type == "function_definition":
                        method_nodes.append((child, []))
                        skip.add(child.id)
                    elif child.type == "decorated_definition":
                        inner = child.child_by_field_name("definition")
                        if inner is not None and inner.type == "function_definition":
                            method_nodes.append((inner, [d for d in child.named_children if d.type == "decorator"]))
                            skip.add(child.id)
            refs = _identifiers(body, src, skip) | _identifiers(supers, src)
            refs.discard(name)
            fs.symbols[qual] = Symbol(
                kind="class",
                name=qual,
                start_line=outer.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                body_hash=_hash_tokens(
                    [*(t for d in decorators for t in _tokens(d, src)), *_tokens(node, src, skip)]
                ),
                signature=_collapse(_text(supers, src)) if supers else "",
                references=refs,
                parent=parent,
                decorators=deco_text,
            )
            for m, decos in method_nodes:
                handle_def(m, decos, qual)

    for node in root.named_children:
        if node.type in ("function_definition", "class_definition"):
            handle_def(node, [], None)
        elif node.type == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is not None:
                handle_def(inner, [d for d in node.named_children if d.type == "decorator"], None)
        elif node.type == "import_statement":
            for child in node.named_children:
                if child.type == "dotted_name":
                    fs.imports.append(Import(module=_text(child, src), names=(), line=node.start_point[0] + 1))
                elif child.type == "aliased_import":
                    mod = _text(child.child_by_field_name("name"), src)
                    alias = _text(child.child_by_field_name("alias"), src)
                    fs.imports.append(
                        Import(module=mod, names=(), aliases=((alias, mod),), line=node.start_point[0] + 1)
                    )
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            module = _text(module_node, src)
            names: list[str] = []
            aliases: list[tuple[str, str]] = []
            for child in node.named_children:
                if child is module_node or child.id == getattr(module_node, "id", None):
                    continue
                if child.type == "dotted_name":
                    names.append(_text(child, src))
                elif child.type == "aliased_import":
                    orig = _text(child.child_by_field_name("name"), src)
                    names.append(orig)
                    aliases.append((_text(child.child_by_field_name("alias"), src), orig))
                elif child.type == "wildcard_import":
                    names.append("*")
            fs.imports.append(
                Import(module=module, names=tuple(names), aliases=tuple(aliases), line=node.start_point[0] + 1)
            )
        elif node.type == "expression_statement":
            assign = node.named_children[0] if node.named_children else None
            if assign is not None and assign.type == "assignment":
                left = assign.child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    name = _text(left, src)
                    right = assign.child_by_field_name("right")
                    fs.symbols[name] = Symbol(
                        kind="variable",
                        name=name,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        body_hash=_hash_tokens(_tokens(node, src)),
                        references=_identifiers(right, src) - {name},
                    )


# ------------------------------------------------------------------ javascript
def _js_route(call: Node, src: bytes) -> Route | None:
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "member_expression":
        return None
    prop = _text(fn.child_by_field_name("property"), src)
    obj = _text(fn.child_by_field_name("object"), src)
    if prop not in ROUTE_METHODS or prop == "route":
        return None
    if not any(k in obj.lower() for k in ("app", "router", "server", "api")):
        return None
    args = call.child_by_field_name("arguments")
    if args is None or not args.named_children:
        return None
    path = _string_value(args.named_children[0], src)
    if path is None or not path.startswith("/"):
        return None
    handler = None
    if len(args.named_children) > 1 and args.named_children[-1].type == "identifier":
        handler = _text(args.named_children[-1], src)
    return Route(method=prop.upper(), path=path, handler=handler, line=call.start_point[0] + 1)


def _js_param_names(params: Node | None, src: bytes) -> set[str]:
    """Names bound by a parameter list (not the identifiers used in its type annotations)."""
    if params is None:
        return set()
    if params.type == "identifier":
        return {_text(params, src)}
    names: set[str] = set()
    for p in params.named_children:
        target = p.child_by_field_name("pattern") or p.child_by_field_name("left") or p
        if target.type == "identifier":
            names.add(_text(target, src))
        elif target.type in ("object_pattern", "array_pattern"):
            names |= {_text(n, src) for n in target.named_children if n.type in ("identifier", "shorthand_property_identifier_pattern")}
    return names


def _extract_js(root: Node, src: bytes, fs: FileSymbols) -> None:
    def add_function(name: str, node: Node, fn: Node, parent: str | None, outer: Node) -> None:
        qual = f"{parent}.{name}" if parent else name
        params = fn.child_by_field_name("parameters") or fn.child_by_field_name("parameter")
        ret = fn.child_by_field_name("return_type")
        sig = _collapse(_text(params, src)) if params is not None else "()"
        if ret is not None:
            sig += " " + _collapse(_text(ret, src))
        refs = _identifiers(fn.child_by_field_name("body"), src) | _identifiers(ret, src) | _identifiers(params, src)
        refs -= _js_param_names(params, src) | _js_local_names(fn.child_by_field_name("body"), src)
        refs.discard(name)
        fs.symbols[qual] = Symbol(
            kind="method" if parent else "function",
            name=qual,
            start_line=outer.start_point[0] + 1,
            end_line=outer.end_point[0] + 1,
            body_hash=_hash_tokens(_tokens(node, src)),
            signature=sig,
            references=refs,
            parent=parent,
        )

    def handle(node: Node, outer: Node) -> None:
        t = node.type
        if t in ("function_declaration", "generator_function_declaration"):
            add_function(_text(node.child_by_field_name("name"), src), node, node, None, outer)
        elif t in ("class_declaration", "abstract_class_declaration", "interface_declaration"):
            name = _text(node.child_by_field_name("name"), src)
            body = node.child_by_field_name("body")
            skip: set[int] = set()
            methods: list[Node] = []
            if body is not None:
                for child in body.named_children:
                    if child.type == "method_definition":
                        methods.append(child)
                        skip.add(child.id)
            heritage = [c for c in node.named_children if c.type in ("class_heritage", "extends_type_clause")]
            refs = _identifiers(body, src, skip)
            for h in heritage:
                refs |= _identifiers(h, src)
            refs.discard(name)
            fs.symbols[name] = Symbol(
                kind="interface" if t == "interface_declaration" else "class",
                name=name,
                start_line=outer.start_point[0] + 1,
                end_line=outer.end_point[0] + 1,
                body_hash=_hash_tokens(_tokens(node, src, skip)),
                signature=" ".join(_text(h, src) for h in heritage),
                references=refs,
            )
            for m in methods:
                add_function(_text(m.child_by_field_name("name"), src), m, m, name, m)
        elif t in ("lexical_declaration", "variable_declaration"):
            for decl in node.named_children:
                if decl.type != "variable_declarator":
                    continue
                name_node = decl.child_by_field_name("name")
                if name_node is None or name_node.type != "identifier":
                    continue
                name = _text(name_node, src)
                value = decl.child_by_field_name("value")
                if value is not None and value.type in ("arrow_function", "function_expression", "function"):
                    add_function(name, outer, value, None, outer)
                else:
                    if value is not None and value.type == "call_expression" and _text(
                        value.child_by_field_name("function"), src
                    ) == "require":
                        args = value.child_by_field_name("arguments")
                        mod = _string_value(args.named_children[0], src) if args and args.named_children else None
                        if mod:
                            fs.imports.append(Import(module=mod, names=(name,), line=outer.start_point[0] + 1))
                    fs.symbols[name] = Symbol(
                        kind="variable",
                        name=name,
                        start_line=outer.start_point[0] + 1,
                        end_line=outer.end_point[0] + 1,
                        body_hash=_hash_tokens(_tokens(decl, src)),
                        references=_identifiers(value, src) - {name},
                    )
        elif t == "export_statement":
            decl = node.child_by_field_name("declaration")
            if decl is not None:
                handle(decl, outer)
        elif t == "import_statement":
            source = _string_value(node.child_by_field_name("source"), src) or ""
            names: list[str] = []
            aliases: list[tuple[str, str]] = []
            clause = next((c for c in node.named_children if c.type == "import_clause"), None)
            if clause is not None:
                for c in clause.named_children:
                    if c.type == "identifier":
                        names.append("default")
                        aliases.append((_text(c, src), "default"))
                    elif c.type == "named_imports":
                        for spec in c.named_children:
                            if spec.type == "import_specifier":
                                orig = _text(spec.child_by_field_name("name"), src)
                                alias = spec.child_by_field_name("alias")
                                names.append(orig)
                                if alias is not None:
                                    aliases.append((_text(alias, src), orig))
                    elif c.type == "namespace_import":
                        names.append("*")
            fs.imports.append(
                Import(module=source, names=tuple(names), aliases=tuple(aliases), line=node.start_point[0] + 1)
            )
        elif t == "expression_statement":
            expr = node.named_children[0] if node.named_children else None
            if expr is not None and expr.type == "call_expression":
                route = _js_route(expr, src)
                if route is not None:
                    fs.routes.append(route)

    for node in root.named_children:
        handle(node, node)


def extract_symbols(path: str, content: bytes) -> FileSymbols | None:
    lang = detect_language(path)
    if lang is None:
        return None
    return _extract_cached(path, lang, content)


@lru_cache(maxsize=4096)
def _extract_cached(path: str, lang: str, content: bytes) -> FileSymbols:
    tree = _parser(lang).parse(content)
    fs = FileSymbols(path=path, language=lang, symbols={}, imports=[], routes=[], parse_errors=tree.root_node.has_error)
    if lang == "python":
        _extract_python(tree.root_node, content, fs)
    else:
        _extract_js(tree.root_node, content, fs)
    return fs
