"""A deliberately tiny routing layer so the demo shop needs no third-party packages."""


class App:
    def __init__(self):
        self.routes = {}

    def route(self, path, methods=("GET",)):
        def decorator(fn):
            for method in methods:
                self.routes[(method, path)] = fn
            return fn

        return decorator

    def get(self, path):
        return self.route(path, methods=["GET"])

    def post(self, path):
        return self.route(path, methods=["POST"])

    def handle(self, method, path, body=None, headers=None):
        handler = self.routes.get((method, path))
        if handler is None:
            return 404, {"error": "not found"}
        return handler(body or {}, headers or {})
