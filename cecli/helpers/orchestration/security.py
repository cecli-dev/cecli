"""
AST-level security transforms for the orchestration sandbox.

- SecurityFilter: blocks imports, dunder attributes, dangerous builtins
- LoopYieldInjector: injects cooperative yields into loops
- _cooperative_yield: the injected yield function
"""

import ast
import asyncio


class SecurityError(Exception):
    """Raised when generated code violates security constraints."""


def _security_raise(message: str):
    """Runtime raise helper injected into sandbox globals.

    Called by AST-rewritten forbidden expressions so that private-access
    violations raise at *runtime* rather than rejecting the entire script
    during the pre-execution AST walk.  This allows try/except blocks to
    gracefully handle unreachable code paths.
    """
    raise SecurityError(message)


class SecurityFilter(ast.NodeTransformer):
    """
    AST node transformer that rewrites dangerous constructs into runtime
    ``__security_raise(...)`` calls.

    Instead of rejecting the entire script during the pre-execution walk,
    forbidden constructs are replaced with a call that raises
    ``SecurityError`` at *runtime*.  This means code inside ``try/except``
    blocks can gracefully handle unreachable paths while the security
    boundary is preserved — any actual execution of private access still
    fails.

    Rewrites:
    - All import statements (import X, from X import Y)
    - Access to private/dunder attributes (__class__, __subclasses__, etc.)
    - Calls to eval, exec, open, __import__, compile, breakpoint
    - global / nonlocal statements
    """

    _DANGEROUS_BUILTINS: set[str] = {
        "eval",
        "exec",
        "open",
        "__import__",
        "compile",
        "breakpoint",
        "globals",
        "locals",
        "setattr",
        "delattr",
    }

    _SAFE_DUNDER: set[str] = {"__name__", "__doc__"}

    _SAFE_CLASS_DUNDERS: frozenset[str] = frozenset(
        {
            "__init__",
            "__str__",
            "__repr__",
            "__iter__",
            "__next__",
            "__len__",
            "__getitem__",
            "__setitem__",
            "__contains__",
            "__enter__",
            "__exit__",
            "__aenter__",
            "__aexit__",
            "__await__",
            "__anext__",
            "__aiter__",
            "__del__",
            "__init_subclass__",
            "__set_name__",
            "__class_getitem__",
        }
    )

    def __init__(
        self,
        allowed_imports: frozenset[str] | None = None,
        allow_classes: bool = False,
    ):
        super().__init__()
        self._allowed_imports = allowed_imports or frozenset()
        self._allow_classes = allow_classes
        self._class_depth = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_raise_expr(message: str) -> ast.Call:
        """Return an AST Call node that invokes ``_security_raise(message)``.

        The function ``_security_raise`` is injected into the sandbox
        globals at execution time.
        """
        return ast.Call(
            func=ast.Name(id="__security_raise", ctx=ast.Load()),
            args=[ast.Constant(value=message)],
            keywords=[],
        )

    @staticmethod
    def _make_raise_stmt(message: str) -> ast.Expr:
        """Return an AST Expr statement wrapping ``_security_raise(message)``.

        Used when the forbidden construct is itself a statement
        (import / global / nonlocal) rather than an expression.
        """
        return ast.Expr(value=SecurityFilter._make_raise_expr(message))

    # ------------------------------------------------------------------
    # Statement visitors (import / global / nonlocal)
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> ast.Expr | ast.Import:
        for alias in node.names:
            if alias.name not in self._allowed_imports:
                return self._make_raise_stmt(
                    f"Security filter error at line {node.lineno}: "
                    f"Import '{alias.name}' is not in allowed_imports."
                )

        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.Expr | ast.ImportFrom:
        if node.module is None or node.module not in self._allowed_imports:
            return self._make_raise_stmt(
                f"Security filter error at line {node.lineno}: "
                f"Import from '{node.module}' is not in allowed_imports."
            )

        return node

    def visit_Global(self, node: ast.Global) -> ast.Expr:
        return self._make_raise_stmt(
            f"Security filter error at line {node.lineno}: "
            "The 'global' statement is disabled in the orchestration environment."
        )

    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.Expr:
        return self._make_raise_stmt(
            f"Security filter error at line {node.lineno}: "
            "The 'nonlocal' statement is disabled in the orchestration environment."
        )

    # ------------------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef | ast.Expr:
        if self._allow_classes:
            self._class_depth += 1
            self.generic_visit(node)
            self._class_depth -= 1
            return node

        return self._make_raise_stmt(
            f"Security filter error at line {node.lineno}: "
            "Class definitions are disabled in the orchestration environment."
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef | ast.Expr:
        if self._allow_classes and self._class_depth > 0 and node.name.startswith("__"):
            if node.name not in self._SAFE_CLASS_DUNDERS:
                return self._make_raise_stmt(
                    f"Security filter error at line {node.lineno}: "
                    f"Method name '{node.name}' is not allowed. "
                    f"Only safe dunder methods are permitted inside class bodies."
                )

        return self.generic_visit(node)

    # ------------------------------------------------------------------
    # Expression visitors (attribute access / dangerous calls)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("_"):
            if node.attr in self._SAFE_DUNDER:
                return self.generic_visit(node)

            if (
                self._allow_classes
                and self._class_depth > 0
                and node.attr in self._SAFE_CLASS_DUNDERS
            ):
                return self.generic_visit(node)

            if isinstance(node.ctx, (ast.Store, ast.Del)):
                verb = "assign to" if isinstance(node.ctx, ast.Store) else "delete"
                return self._make_raise_expr(
                    f"Security filter error at line {node.lineno}: "
                    f"cannot {verb} private attribute '{node.attr}'"
                )

            return self._make_raise_expr(
                f"Security filter error at line {node.lineno}: "
                f"Access to private/dunder attribute '{node.attr}' is forbidden."
            )

        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in self._DANGEROUS_BUILTINS:
            return self._make_raise_expr(
                f"Security filter error at line {node.lineno}: "
                f"Calling '{node.func.id}' is forbidden."
            )

        return self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> ast.Expr:
        """Block all ``match``/``case`` statements.

        Class patterns destructure objects via runtime ``getattr()``,
        bypassing the AST-level ``visit_Attribute`` guard entirely.
        Rather than trying to cover every pattern variant, we reject
        the ``match`` statement wholesale.
        """
        return self._make_raise_stmt(
            f"Security filter error at line {node.lineno}: "
            "The 'match'/'case' statement is disabled in the orchestration environment."
        )


class LoopYieldInjector(ast.NodeTransformer):
    """
    Injects ``await __yield()`` at the top of every ``for`` and ``while`` loop body.

    This forces cooperative multitasking so that infinite loops can be cancelled
    via ``asyncio.wait_for`` timeout.
    """

    def __init__(self) -> None:
        super().__init__()
        self._yield_stmt = ast.Expr(
            value=ast.Await(
                value=ast.Call(
                    func=ast.Name(id="__yield", ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
            )
        )

    def visit_While(self, node: ast.While) -> ast.While:
        self.generic_visit(node)
        node.body.insert(0, self._yield_stmt)
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        self.generic_visit(node)
        node.body.insert(0, self._yield_stmt)
        return node


async def _cooperative_yield() -> None:
    """Force the current coroutine to briefly yield to the event loop."""
    await asyncio.sleep(0)
