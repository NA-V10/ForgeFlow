from textwrap import dedent

from ff_semantic import (
    ChangeSet,
    build_dependency_graph,
    classify_domains,
    detect_semantic_conflicts,
    extract_symbols,
    semantic_diff,
)


def b(s: str) -> bytes:
    return dedent(s).lstrip("\n").encode()


OLD_APP = b('''
    from flask import Flask
    import os

    app = Flask(__name__)
    TIMEOUT = 30


    @app.route("/login", methods=["POST"])
    def login(username, password):
        return check(username, password)


    def check(username, password):
        return username == "admin"


    class UserStore:
        def get(self, user_id):
            return None

        def delete(self, user_id):
            pass
''')

NEW_APP = b('''
    from flask import Flask
    from oauthlib.oauth2 import WebApplicationClient
    import os

    app = Flask(__name__)
    TIMEOUT = 30


    @app.route("/login", methods=["POST"])
    def login(username, password, otp=None):
        # now validates JWT too
        return check(username, password) and validate_jwt(otp)


    def check(username,   password):
        return username == "admin"  # formatting change only


    def validate_jwt(token):
        return bool(token)


    @app.get("/health")
    def health():
        return "ok"


    class UserStore:
        def get(self, user_id):
            return {"id": user_id}
''')


def test_extract_python_symbols_routes_imports():
    fs = extract_symbols("app.py", NEW_APP)
    assert fs is not None and fs.language == "python"
    assert {"login", "check", "validate_jwt", "health", "UserStore", "UserStore.get", "app", "TIMEOUT"} <= set(fs.symbols)
    assert fs.symbols["UserStore.get"].kind == "method"
    assert "validate_jwt" in fs.symbols["login"].references
    assert "username" not in fs.symbols["login"].references  # parameters are excluded
    assert {r.key for r in fs.routes} == {"POST /login", "GET /health"}
    assert any(i.module == "oauthlib.oauth2" and i.names == ("WebApplicationClient",) for i in fs.imports)


def test_formatting_and_comments_do_not_change_hash():
    a = extract_symbols("x.py", b"def f(a, b):\n    return a+b\n")
    c = extract_symbols("x.py", b"def f(a,   b):\n    # comment\n    return a+b  # trailing\n")
    assert a.symbols["f"].body_hash == c.symbols["f"].body_hash


def test_semantic_diff_python():
    sd = semantic_diff({"app.py": OLD_APP}, {"app.py": NEW_APP})
    kinds = {(c.kind, c.symbol) for c in sd.changes if c.symbol}
    assert ("function_modified", "login") in kinds
    assert ("function_added", "validate_jwt") in kinds
    assert ("function_added", "health") in kinds
    assert ("function_modified", "UserStore.get") in kinds
    assert ("function_removed", "UserStore.delete") in kinds
    assert not any(c.symbol == "check" for c in sd.changes), "formatting-only change must not be reported"
    login = next(c for c in sd.changes if c.symbol == "login" and c.category == "functions")
    assert login.details["signature_changed"] is True
    assert "Authentication" in login.domains
    route_kinds = {(c.kind, c.details.get("path")) for c in sd.changes if c.category == "apis"}
    assert ("route_changed", "/login") in route_kinds
    assert ("route_added", "/health") in route_kinds
    assert any(c.kind == "import_added" and c.details["module"] == "oauthlib.oauth2" for c in sd.changes)
    groups = sd.groups()
    assert {"functions", "imports", "apis"} <= set(groups)
    assert "Authentication" in sd.domains()
    assert "Semantic changes:" in sd.summary_text()


def test_semantic_diff_typescript_and_express():
    old = b('''
        import { db } from './db';
        export function listUsers(limit: number) { return db.query('select * from users limit ' + limit); }
        app.get('/users', listUsers);
    ''')
    new = b('''
        import { db } from './db';
        import jwt from 'jsonwebtoken';
        export function listUsers(limit: number, offset: number) { return db.query('select * from users', [limit, offset]); }
        export const requireAuth = (req, res, next) => { jwt.verify(req.token); next(); };
        export class AuthService { login(user: string) { return jwt.sign(user); } }
        app.get('/users', listUsers);
        app.post('/login', requireAuth);
    ''')
    sd = semantic_diff({"src/server.ts": old}, {"src/server.ts": new})
    kinds = {(c.kind, c.symbol) for c in sd.changes}
    assert ("function_modified", "listUsers") in kinds
    assert ("function_added", "requireAuth") in kinds
    assert ("class_added", "AuthService") in kinds
    assert ("function_added", "AuthService.login") in kinds
    assert any(c.kind == "route_added" and c.details["path"] == "/login" for c in sd.changes)
    assert any(c.kind == "route_changed" and c.details["path"] == "/users" for c in sd.changes)
    assert any(c.kind == "import_added" and c.details["module"] == "jsonwebtoken" for c in sd.changes)


def test_dependency_and_config_changes():
    sd = semantic_diff(
        {
            "package.json": b'{"dependencies": {"express": "^4.18.0", "lodash": "4.17.0"}}',
            "requirements.txt": b"flask==3.0\nrequests>=2\n",
            "config/settings.yaml": b"db:\n  pool: 5\nfeature: false\n",
        },
        {
            "package.json": b'{"dependencies": {"express": "^4.19.0", "jsonwebtoken": "^9.0.0"}}',
            "requirements.txt": b"flask==3.0\noauthlib==3.2.2\n",
            "config/settings.yaml": b"db:\n  pool: 20\nfeature: false\napi_token: x\n",
        },
    )
    by_kind = {}
    for c in sd.changes:
        by_kind.setdefault(c.kind, set()).add(c.details.get("package") or c.details.get("key"))
    assert by_kind["dependency_added"] == {"npm:jsonwebtoken", "pypi:oauthlib"}
    assert by_kind["dependency_removed"] == {"npm:lodash", "pypi:requests"}
    assert by_kind["dependency_changed"] == {"npm:express"}
    assert by_kind["config_changed"] == {"db.pool", "api_token"}
    token = next(c for c in sd.changes if c.details.get("key") == "api_token")
    assert token.details["sensitive"] and "Security" in token.domains


def test_unsupported_and_deleted_files():
    sd = semantic_diff({"logo.png": b"\x89PNG", "old.py": b"def f():\n  pass\n"}, {"logo.png": b"\x89PNG2", "old.py": None})
    kinds = {(c.kind, c.path) for c in sd.changes}
    assert ("file_modified", "logo.png") in kinds
    assert ("function_removed", "old.py") in kinds


def test_domain_classification_uses_words():
    assert classify_domains("AuthorizationContext") == ["Authorization"]
    assert "Authentication" in classify_domains("AuthenticationContext")
    assert "Authentication" in classify_domains("auth/oauth.py")
    assert "Database" in classify_domains("db/queries.py")
    assert classify_domains("utils/strings.py") == []


AUTH = b('''
    class AuthenticationContext:
        def __init__(self, user):
            self.user = user

        def is_authenticated(self):
            return self.user is not None
''')

AUTHZ = b('''
    from app.authn import AuthenticationContext


    class AuthorizationContext:
        def __init__(self, authn: AuthenticationContext, roles):
            self.authn = authn
            self.roles = roles

        def can(self, action):
            return self.authn.is_authenticated() and action in self.roles
''')


def _changeset(name, base_files, head_files):
    changed = {p for p in set(base_files) | set(head_files) if base_files.get(p) != head_files.get(p)}
    sd = semantic_diff({p: base_files.get(p) for p in changed}, {p: head_files.get(p) for p in changed})
    graph = build_dependency_graph({p: c for p, c in head_files.items() if c is not None})
    return ChangeSet(name=name, diff=sd, graph=graph)


def test_graph_resolves_imports():
    g = build_dependency_graph({"app/authn.py": AUTH, "app/authz.py": AUTHZ})
    assert "app/authn.py::AuthenticationContext" in g.dependencies_of("app/authz.py::AuthorizationContext.__init__")
    assert "app/authz.py::AuthorizationContext.__init__" in g.dependents_of("app/authn.py::AuthenticationContext")


def test_semantic_conflict_dependency():
    base = {"app/authn.py": AUTH, "app/authz.py": AUTHZ}
    a_head = {**base, "app/authn.py": AUTH.replace(b"self.user is not None", b"self.user is not None and self.user.active")}
    b_head = {**base, "app/authz.py": AUTHZ.replace(b"action in self.roles", b"(action in self.roles or 'admin' in self.roles)")}
    conflicts = detect_semantic_conflicts(_changeset("agent-a", base, a_head), _changeset("agent-b", base, b_head))
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.conflict_type == "dependency_conflict"
    assert c.severity == "MEDIUM"
    assert set(c.affected_symbols) == {"AuthenticationContext", "AuthorizationContext"}
    assert c.affected_files == ["app/authn.py", "app/authz.py"]
    assert "AuthorizationContext" in c.explanation


def test_semantic_conflict_broken_reference_and_signature():
    base = {"lib.py": b"def helper(x):\n    return x\n\ndef other(x):\n    return x\n", "main.py": b"from lib import helper\n"}
    a_head = {**base, "lib.py": b"def other(x, y):\n    return x + y\n"}  # removes helper, changes other's signature
    b_head = {**base, "main.py": b"from lib import helper, other\n\ndef run():\n    return helper(1) + other(2)\n"}
    conflicts = detect_semantic_conflicts(_changeset("A", base, a_head), _changeset("B", base, b_head))
    types = {(c.conflict_type, c.severity) for c in conflicts}
    assert ("broken_reference", "CRITICAL") in types
    assert ("signature_change", "HIGH") in types
    assert conflicts[0].severity == "CRITICAL"


def test_no_conflict_for_independent_changes():
    base = {"a.py": b"def f():\n    return 1\n", "b.py": b"def g():\n    return 2\n"}
    conflicts = detect_semantic_conflicts(
        _changeset("A", base, {**base, "a.py": b"def f():\n    return 10\n"}),
        _changeset("B", base, {**base, "b.py": b"def g():\n    return 20\n"}),
    )
    assert conflicts == []


def test_same_symbol_route_dependency_config_conflicts():
    base = {"api.py": b"@app.post('/login')\ndef login():\n    return 1\n", "package.json": b'{"dependencies": {}}',
            "app.yaml": b"timeout: 1\n"}
    a_head = {"api.py": b"@app.post('/login')\ndef login():\n    return 2\n",
              "package.json": b'{"dependencies": {"jsonwebtoken": "9.0.0"}}', "app.yaml": b"timeout: 2\n"}
    b_head = {"api.py": b"@app.post('/login')\ndef login():\n    return 3\n",
              "package.json": b'{"dependencies": {"jsonwebtoken": "8.5.1"}}', "app.yaml": b"timeout: 3\n"}
    types = {c.conflict_type for c in detect_semantic_conflicts(_changeset("A", base, a_head), _changeset("B", base, b_head))}
    assert {"same_symbol", "route_collision", "dependency_version", "config_key"} <= types



def test_local_bindings_are_not_references():
    fs = extract_symbols("t.py", b('''
        def test_x():
            orders = list_orders(1)
            for item, qty in orders:
                total = qty
            with open("f") as handle:
                pass
            return validate(total, handle)
    '''))
    refs = fs.symbols["test_x"].references
    assert {"list_orders", "validate"} <= refs
    assert not refs & {"orders", "item", "qty", "total", "handle"}
    js = extract_symbols("a.js", b"function f(){ const orders = listOrders(); return render(orders); }\n")
    assert "orders" not in js.symbols["f"].references and "listOrders" in js.symbols["f"].references
