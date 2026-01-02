#!/usr/bin/env python3
# /// script
# dependencies = [
#   "astor",
#   "autopep8",
# ]
# ///

# flake8: noqa
"""
Script to rename project from aider-ce to cecli.

This script handles:
1. Python import statements (import aider, from aider import, etc.)
2. Documentation and configuration files
3. Package metadata and references
4. Path assignments using .aider paths to use handle_core_files()

Usage:
    python rename_to_cecli.py [--dry-run] [--backup]

Options:
    --dry-run: Show what would be changed without making changes
    --backup: Create backup copies of modified files
    --skip-python: Skip Python file updates
    --skip-other: Skip non-Python file updates
    --skip-path-assignments: Skip updating path assignments to use handle_core_files()
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Rename aider-ce to cecli")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be changed without making changes"
    )
    parser.add_argument(
        "--backup", action="store_true", help="Create backup copies of modified files"
    )
    parser.add_argument("--skip-python", action="store_true", help="Skip Python file updates")
    parser.add_argument("--skip-other", action="store_true", help="Skip non-Python file updates")
    parser.add_argument(
        "--skip-path-assignments",
        action="store_true",
        help="Skip updating path assignments to use handle_core_files()",
    )
    return parser.parse_args()


def should_skip_file(filepath):
    """Check if file should be skipped based on path patterns."""
    skip_patterns = [
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "node_modules",
        "build",
        "dist",
        "*.egg-info",
        "venv/",
        "file_searcher.py",
        "pyproject.toml",
        "CHANGELOG.md",
        "rename_to_cecli.py",  # Skip this script itself
    ]

    file_str = str(filepath)
    for pattern in skip_patterns:
        if pattern in file_str:
            return True
    return False


def update_python_file(filepath, dry_run=False, backup=False):
    """
    Update Python file imports and references.

    Handles:
    - import aider
    - from aider import ...
    - import aider.submodule
    - aider.xxx references
    - String literals containing 'aider'
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    changes = []

    # Track line numbers for reporting
    lines = content.split("\n")

    # 1. Update import statements
    # Pattern: import aider
    new_content = re.sub(
        r"^(\s*)import aider(\s*(?:#.*)?)$", r"\1import cecli\2", content, flags=re.MULTILINE
    )

    # Pattern: from aider import ...
    new_content = re.sub(
        r"^(\s*)from aider import (.*)$", r"\1from cecli import \2", new_content, flags=re.MULTILINE
    )

    # Pattern: import aider.submodule
    new_content = re.sub(
        r"^(\s*)import aider\.(.*)$", r"\1import cecli.\2", new_content, flags=re.MULTILINE
    )

    # Pattern: from aider.submodule import ...
    new_content = re.sub(
        r"^(\s*)from aider\.(.*)$", r"\1from cecli.\2", new_content, flags=re.MULTILINE
    )

    # 2. Update aider.xxx references (but be careful with strings/comments)
    # This regex tries to match aider.xxx not in strings or comments
    # It's not perfect but works for most cases
    def replace_aider_dot(match):
        # Check if it's likely in a string or comment
        text_before = content[: match.start()]
        # Count quotes before this position
        single_quotes = text_before.count("'") - text_before.count("\\'")
        double_quotes = text_before.count('"') - text_before.count('\\"')
        comment_pos = text_before.rfind("#")
        line_start = text_before.rfind("\n", 0, match.start())

        # If there's an unclosed quote or comment on this line, skip
        if (
            single_quotes % 2 == 1
            or double_quotes % 2 == 1
            or (comment_pos > line_start and comment_pos < match.start())
        ):
            return match.group(0)

        return match.group(0).replace("aider.", "cecli.")

    # Apply the replacement
    new_content = re.sub(r"\baider\.(\w+)", replace_aider_dot, new_content)

    # 3. Update string literals (carefully)
    # Replace 'aider' and "aider" when they appear as standalone strings
    # but not as part of larger words
    def replace_aider_string(match):
        full_match = match.group(0)
        # Check if it's 'aider' or "aider" exactly
        if full_match in ["'aider'", '"aider"']:
            return full_match.replace("aider", "cecli")
        return full_match

    new_content = re.sub(r"'[^']*'|\"[^\"]*\"", replace_aider_string, new_content)

    # 4. Special case: aider.__version__ references
    new_content = new_content.replace("aider.__version__", "cecli.__version__")
    new_content = new_content.replace("aider.__version_tuple__", "cecli.__version_tuple__")

    # 5 Wensite references
    new_content = new_content.replace("aider.chat", "cecli.dev")

    # 6. Test-specific patterns
    # patch("aider.module -> patch("cecli.module
    new_content = re.sub(r'patch\("aider\.', 'patch("cecli.', new_content)

    # monkeypatch.setattr("aider.module -> monkeypatch.setattr("cecli.module
    new_content = re.sub(
        r'monkeypatch\.setattr\("aider\.', 'monkeypatch.setattr("cecli.', new_content
    )

    # unittest.mock.patch("aider.module -> unittest.mock.patch("cecli.module
    new_content = re.sub(
        r'unittest\.mock\.patch\("aider\.', 'unittest.mock.patch("cecli.', new_content
    )

    # mock.patch("aider.module -> mock.patch("cecli.module
    new_content = re.sub(r'mock\.patch\("aider\.', 'mock.patch("cecli.', new_content)

    # @patch("aider.module -> @patch("cecli.module
    new_content = re.sub(r'@patch\("aider\.', '@patch("cecli.', new_content)

    # @mock.patch("aider.module -> @mock.patch("cecli.module
    new_content = re.sub(r'@mock\.patch\("aider\.', '@mock.patch("cecli.', new_content)

    # @unittest.mock.patch("aider.module -> @unittest.mock.patch("cecli.module
    new_content = re.sub(
        r'@unittest\.mock\.patch\("aider\.', '@unittest.mock.patch("cecli.', new_content
    )

    # MagicMock(spec=aider.module -> MagicMock(spec=cecli.module
    new_content = re.sub(r"MagicMock\(spec=aider\.", "MagicMock(spec=cecli.", new_content)

    # create_autospec(aider.module -> create_autospec(cecli.module
    new_content = re.sub(r"create_autospec\(aider\.", "create_autospec(cecli.", new_content)

    # Mock(spec=aider.module -> Mock(spec=cecli.module
    new_content = re.sub(r"Mock\(spec=aider\.", "Mock(spec=cecli.", new_content)

    # mock.patch("aider. -> mock.patch("cecli.
    new_content = re.sub(r'mock\.patch\("aider\.', 'mock.patch("cecli.', new_content)

    # 7 aider.resources and aider.website
    new_content = new_content.replace("aider.resources", "cecli.resources")
    new_content = new_content.replace("aider.website", "cecli.website")

    # 8 explicit renames because we have a few variables to update globally
    new_content = new_content.replace("_aider_coders", "_cecli_coders")
    new_content = new_content.replace("aider_commit_hashes", "coder_commit_hashes")
    new_content = new_content.replace("last_aider_commit_hash", "last_coder_commit_hash")
    new_content = new_content.replace("last_aider_commit_message", "last_coder_commit_message")
    new_content = new_content.replace("aider_edited_files", "coder_edited_files")
    new_content = new_content.replace("aider_edits", "coder_edits")
    new_content = new_content.replace("aider_mode", "coder_mode")
    new_content = new_content.replace("aider_user_agent", "coder_user_agent")
    new_content = new_content.replace("aider_conf_path", "conf_path")
    new_content = new_content.replace("AiderFooter", "MainFooter")
    new_content = new_content.replace("AIDER_APP_NAME", "APP_NAME")
    new_content = new_content.replace("AIDER_SITE_URL", "SITE_URL")

    # 9 replace aider in strings
    new_content = new_content.replace('"aider"', '"cecli"')
    new_content = new_content.replace("Aider", "cecli")
    new_content = new_content.replace("cecli-CE", "cecli")
    new_content = new_content.replace("aider-ce", "cecli")
    new_content = new_content.replace(".aider/", ".cecli/")
    new_content = new_content.replace('and not os.getenv("AIDER_CE_DEFAULT_TLS")', "")
    new_content = new_content.replace("AIDER", "CECLI")
    new_content = new_content.replace(".aider.model.settings.yml", ".cecli.model.settings.yml")
    new_content = new_content.replace(".aider.model.metadata.json", ".cecli.model.metadata.json")
    new_content = new_content.replace(".aider.model.overrides.yml", ".cecli.model.overrides.yml")
    new_content = new_content.replace(".aider.", ".cecli.")
    new_content = new_content.replace(" aider ", " cecli ")
    new_content = new_content.replace("aider.conf.yml", "cecli.conf.yml")
    new_content = new_content.replace("aider_default", "cecli_default")

    # Fix things to change back (for now)
    new_content = new_content.replace("cecli-AI", "Aider-AI")
    new_content = new_content.replace(
        "https://pypi.org/pypi/cecli/json", "https://pypi.org/pypi/aider-ce/json"
    )
    new_content = new_content.replace("CECLI_", "CECLI")

    # 10 changes related to .aiderignore
    new_content = new_content.replace("AIDERIGNORE", "CECLI_IGNORE")
    new_content = new_content.replace("--aiderignore", "--cecli-ignore")
    new_content = new_content.replace("aiderignore =", "cecli_ignore =")
    new_content = new_content.replace(" aiderignore", " cecli.ignore")
    new_content = new_content.replace('".aiderignore"', '"cecli.ignore"')
    new_content = new_content.replace("aiderignore", "cecli_ignore")
    new_content = new_content.replace("aider_ignore", "cecli_ignore")

    # 11 Final renames
    new_content = new_content.replace("aider.", "cecli.")
    new_content = new_content.replace(".aider*", ".cecli*")
    new_content = new_content.replace('"aider/', '"cecli/')
    new_content = new_content.replace("'aider/", "'cecli/")
    new_content = new_content.replace("github.com/aider-chat/aider", "github.com/dwash96/cecli")
    new_content = new_content.replace("aider", "cecli")

    # 12 Final renames back
    new_content = new_content.replace("AIDER-AI/cecli", "AIDER-AI/aider")

    if new_content != original:
        # Find what changed for reporting
        orig_lines = original.split("\n")
        new_lines = new_content.split("\n")

        for i, (orig, new) in enumerate(zip(orig_lines, new_lines)):
            if orig != new:
                changes.append(f"  Line {i+1}: {orig.strip()} -> {new.strip()}")

        if not dry_run:
            if backup:
                backup_path = filepath.with_suffix(filepath.suffix + ".bak")
                shutil.copy2(filepath, backup_path)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)

        return True, changes

    return False, []


def update_other_file(filepath, dry_run=False, backup=False):
    """
    Update non-Python files (docs, configs, etc.).

    Handles:
    - aider-ce references
    - GitHub URLs
    - Documentation references
    """
    if filepath.suffix not in [
        ".md",
        ".txt",
        ".toml",
        ".cfg",
        ".yml",
        ".yaml",
        ".rst",
        ".json",
        ".ini",
        ".cfg",
        ".html",
        ".js",
        ".css",
    ]:
        return False, []

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    changes = []

    # Update aider-ce to cecli (package name)
    new_content = content.replace("aider-ce", "cecli")

    # Update GitHub URLs (but keep aider.chat external links)
    new_content = new_content.replace("github.com/dwash96/aider-ce", "github.com/dwash96/cecli")

    # Update pip install commands
    new_content = re.sub(r"pip install aider-ce(\s|$)", r"pip install cecli\1", new_content)
    new_content = re.sub(r"pipx install aider-ce(\s|$)", r"pipx install cecli\1", new_content)

    # Update command examples (but be careful with aider.chat which is external)
    # Replace 'aider-ce' command but not URLs containing aider.chat
    def replace_aider_ce_command(match):
        text = match.group(0)
        # Don't replace if it's part of a URL
        if "://" in text or "aider.chat" in text:
            return text
        return text.replace("aider-ce", "cecli")

    # Apply replacement for aider-ce as a command/word
    new_content = re.sub(r"\baider-ce\b", replace_aider_ce_command, new_content)

    # Update Aider-CE (capitalized) to CECLI
    new_content = re.sub(r"\bAider-CE\b", "CECLI", new_content)
    new_content = re.sub(r"\bAider CE\b", "CECLI", new_content)

    if new_content != original:
        # Find what changed for reporting
        orig_lines = original.split("\n")
        new_lines = new_content.split("\n")

        for i, (orig, new) in enumerate(zip(orig_lines, new_lines)):
            if orig != new:
                changes.append(f"  Line {i+1}: {orig.strip()} -> {new.strip()}")

        if not dry_run:
            if backup:
                backup_path = filepath.with_suffix(filepath.suffix + ".bak")
                shutil.copy2(filepath, backup_path)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)

        return True, changes

    return False, []


def update_path_assignments(filepath, dry_run=False, backup=False):
    """
    Update path assignments to use handle_core_files() for .aider paths.

    Handles transformations like:
    1. self.cache_dir = Path.home() / ".aider" / "caches"
       → self.cache_dir = handle_core_files(Path.home() / ".cecli" / "caches")

    2. todo_path = self.coder.abs_root_path(".aider.todo.txt")
       → todo_path = self.coder.abs_root_path(handle_core_files(".cecli.todo.txt"))

    3. config_path = ".aider/config.yml"
       → config_path = handle_core_files(".cecli/config.yml")

    4. Also adds import for cecli.helpers.file_searcher if needed
    """
    if filepath.suffix != ".py":
        return False, []

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    changes = []

    try:
        import ast

        import astor  # We'll need astor to convert AST back to code

        # Parse the AST
        tree = ast.parse(content)

        # Track if we need to add the import
        needs_import = True
        import_added = False

        # First pass: check if import already exists
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "cecli.helpers.file_searcher" and any(
                    alias.name == "handle_core_files" for alias in node.names
                ):
                    needs_import = False
                    break

        # Second pass: transform assignments and add import if needed
        class Transformer(ast.NodeTransformer):
            def __init__(self):
                super().__init__()
                self.modified = False
                self.import_added = False

            def visit_Assign(self, node):
                # Check if this is an assignment we should transform
                self.generic_visit(node)  # Visit children first

                # Try to extract string values from the assignment
                if isinstance(node.value, ast.BinOp):
                    # Pattern 1: Path operations like Path.home() / ".aider" / "caches"
                    transformed = self._transform_path_operation(node.value)
                    if transformed:
                        node.value = transformed
                        self.modified = True
                        return node

                elif isinstance(node.value, ast.Call):
                    # Pattern 2: Function calls with string arguments
                    transformed = self._transform_function_call(node.value)
                    if transformed:
                        node.value = transformed
                        self.modified = True
                        return node

                elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    # Pattern 3: Direct string assignments
                    if ".aider" in node.value.value:
                        # Change .aider to .cecli and wrap with handle_core_files
                        new_str = node.value.value.replace(".aider", ".cecli")
                        # Create handle_core_files(new_str) call
                        node.value = ast.Call(
                            func=ast.Name(id="handle_core_files", ctx=ast.Load()),
                            args=[ast.Constant(value=new_str)],
                            keywords=[],
                        )
                        self.modified = True
                        return node

                return node

            def visit_With(self, node):
                """Transform with statements containing .aider paths."""
                self.generic_visit(node)  # Visit children first

                # Check each item in the with statement
                for item in node.items:
                    if isinstance(item.context_expr, ast.Call):
                        # Check if it's a function call like open(".aider/path")
                        transformed = self._transform_function_call(item.context_expr)
                        if transformed:
                            item.context_expr = transformed
                            self.modified = True

                return node

            def visit_Call(self, node):
                """Transform function calls containing .aider paths (not in assignments)."""
                self.generic_visit(node)  # Visit children first

                # Transform function calls that have .aider string arguments
                transformed = self._transform_function_call(node)
                if transformed:
                    self.modified = True
                    return transformed

                return node

            def _transform_path_operation(self, node):
                """Transform Path operations containing .aider strings."""

                # Recursively check for string constants with .aider
                def find_and_replace_aider(node):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        if ".aider" in node.value:
                            # Replace .aider with .cecli
                            node.value = node.value.replace(".aider", ".cecli")
                            return True
                    elif isinstance(node, ast.BinOp):
                        left_changed = find_and_replace_aider(node.left)
                        right_changed = find_and_replace_aider(node.right)
                        return left_changed or right_changed
                    elif isinstance(node, ast.Call):
                        # Check arguments in function calls
                        changed = False
                        for arg in node.args:
                            if find_and_replace_aider(arg):
                                changed = True
                        return changed
                    return False

                # Check if this path operation contains .aider
                if find_and_replace_aider(node):
                    # Wrap the entire expression with handle_core_files()
                    return ast.Call(
                        func=ast.Name(id="handle_core_files", ctx=ast.Load()),
                        args=[node],
                        keywords=[],
                    )
                return None

            def _transform_function_call(self, node):
                """Transform function calls with .aider string arguments."""
                # Special handling for certain functions where we should wrap arguments
                # instead of the entire call
                wrap_arguments_functions = {"open", "Path", "os.path.join", "os.path.abspath"}

                # Check if this is a function where we should wrap arguments
                func_name = self._get_function_name(node)
                should_wrap_arguments = func_name in wrap_arguments_functions

                modified = False
                new_args = []

                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if ".aider" in arg.value:
                            # Replace .aider with .cecli
                            new_str = arg.value.replace(".aider", ".cecli")

                            if should_wrap_arguments:
                                # Wrap the argument with handle_core_files()
                                new_arg = ast.Call(
                                    func=ast.Name(id="handle_core_files", ctx=ast.Load()),
                                    args=[ast.Constant(value=new_str)],
                                    keywords=[],
                                )
                            else:
                                # For other functions, just update the string
                                new_arg = ast.Constant(value=new_str)

                            new_args.append(new_arg)
                            modified = True
                        else:
                            new_args.append(arg)
                    else:
                        new_args.append(arg)

                if modified:
                    node.args = new_args
                    return node
                return None

            def _get_function_name(self, node):
                """Extract function name from a Call node."""
                if isinstance(node.func, ast.Name):
                    return node.func.id
                elif isinstance(node.func, ast.Attribute):
                    # Handle cases like os.path.join
                    parts = []
                    current = node.func
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    return ".".join(reversed(parts))
                return None

        # Apply transformations
        transformer = Transformer()
        tree = transformer.visit(tree)

        # Add import if needed and we made modifications
        if needs_import and transformer.modified:
            # Create the import statement
            import_node = ast.ImportFrom(
                module="cecli.helpers.file_searcher",
                names=[ast.alias(name="handle_core_files")],
                level=0,
            )

            # Find the best place to insert the import (after other imports)
            import_index = 0
            for i, node in enumerate(tree.body):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    import_index = i + 1
                else:
                    # Stop at first non-import statement
                    break

            # Insert the import
            tree.body.insert(import_index, import_node)
            import_added = True
            changes.append(f"  Added import for handle_core_files at position {import_index + 1}")

        # Convert AST back to source code
        if transformer.modified or import_added:
            # Use astor if available, otherwise use ast.unparse (Python 3.9+)
            try:
                import astor

                new_content = astor.to_source(tree)
            except ImportError:
                # Fall back to ast.unparse for Python 3.9+
                new_content = ast.unparse(tree)

            # Format the code
            import autopep8

            new_content = autopep8.fix_code(new_content)

            # Track changes
            orig_lines = original.split("\n")
            new_lines = new_content.split("\n")

            for i, (orig, new) in enumerate(zip(orig_lines, new_lines)):
                if i < len(orig_lines) and i < len(new_lines) and orig != new:
                    changes.append(f"  Line {i+1}: {orig.strip()[:50]}... -> {new.strip()[:50]}...")

            if not dry_run:
                if backup:
                    backup_path = filepath.with_suffix(filepath.suffix + ".bak")
                    shutil.copy2(filepath, backup_path)

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)

            return True, changes

        return False, []

    except (SyntaxError, ImportError) as e:
        # If AST parsing fails or dependencies missing, fall back to regex
        print(f"  Warning: AST transformation failed for {filepath}: {e}")
        print(f"  Falling back to regex-based transformation")
        return _update_path_assignments_regex(filepath, dry_run, backup)


def _update_path_assignments_regex(filepath, dry_run=False, backup=False):
    """
    Fallback regex-based implementation for update_path_assignments.
    Used when AST transformation fails.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    changes = []

    # List of path patterns to search for
    path_patterns = [
        r"\.aider\.",  # .aider.todo.txt, .aider.config.yml, etc.
        r'"/\.aider/',  # "/.aider/...
        r"'/\.aider/",  # '/.aider/...
        r'"/\.aider"',  # "/.aider"
        r"'/\.aider'",  # '/.aider'
        r'Path\(.*?\)\s*/\s*"\.aider"',  # Path(...) / ".aider"
        r"Path\(.*?\)\s*/\s*\'\.aider\'",  # Path(...) / '.aider'
    ]

    # Check if file contains any .aider path patterns
    has_aider_paths = False
    for pattern in path_patterns:
        if re.search(pattern, content):
            has_aider_paths = True
            break

    if not has_aider_paths:
        return False, []

    new_content = content
    lines = content.split("\n")

    # First, ensure we have the import for handle_core_files
    import_added = False

    # Check if import already exists
    if "from cecli.helpers.file_searcher import handle_core_files" not in new_content:
        # Try to add import after other imports
        import_pattern = r"^(from|import)\s+"
        import_lines = []

        for i, line in enumerate(lines):
            if re.match(import_pattern, line.strip()):
                import_lines.append(i)

        if import_lines:
            # Add after the last import
            last_import_line = max(import_lines)
            lines.insert(
                last_import_line + 1, "from cecli.helpers.file_searcher import handle_core_files"
            )
            import_added = True
            changes.append(f"  Line {last_import_line + 2}: Added import for handle_core_files")
        else:
            # Add at the top of the file
            lines.insert(0, "from cecli.helpers.file_searcher import handle_core_files")
            import_added = True
            changes.append("  Line 1: Added import for handle_core_files")

    # Now transform path assignments
    # Pattern 1: Simple assignments with Path operations
    # Example: self.cache_dir = Path.home() / ".aider" / "caches"
    path_assignment_pattern = r'(\w+(?:\.\w+)*\s*=\s*)(Path\([^)]+\)(?:\s*/\s*["\'][^"\']*["\'])+)'

    def wrap_path_with_handle_core_files(match):
        assignment = match.group(1)  # e.g., "self.cache_dir = "
        path_expr = match.group(2)  # e.g., 'Path.home() / ".aider" / "caches"'

        # Check if the path expression contains .aider
        if ".aider" in path_expr:
            # Change .aider to .cecli in the path expression
            cecli_path_expr = path_expr.replace(".aider", ".cecli")
            return f"{assignment}handle_core_files({cecli_path_expr})"
        return match.group(0)

    new_content = "\n".join(lines)
    new_content = re.sub(path_assignment_pattern, wrap_path_with_handle_core_files, new_content)

    # Pattern 2: Function arguments with .aider paths
    # Example: todo_path = self.coder.abs_root_path(".aider.todo.txt")
    func_arg_pattern = r'(\w+(?:\.\w+)*\s*=\s*\w+(?:\.\w+)*\(["\'])([^"\']*\.aider[^"\']*)(["\']\))'

    def wrap_arg_with_handle_core_files(match):
        prefix = match.group(1)  # e.g., "todo_path = self.coder.abs_root_path("
        path_arg = match.group(2)  # e.g., ".aider.todo.txt"
        suffix = match.group(3)  # e.g., ")"

        # Change .aider to .cecli in the path argument
        cecli_path_arg = path_arg.replace(".aider", ".cecli")
        return f'{prefix}handle_core_files("{cecli_path_arg}"){suffix}'

    new_content = re.sub(func_arg_pattern, wrap_arg_with_handle_core_files, new_content)

    # Pattern 3: Direct string assignments with .aider
    # Example: config_path = ".aider/config.yml"
    direct_assignment_pattern = r'(\w+(?:\.\w+)*\s*=\s*["\'])([^"\']*\.aider[^"\']*)(["\'])'

    def wrap_direct_with_handle_core_files(match):
        prefix = match.group(1)  # e.g., "config_path = "
        path_str = match.group(2)  # e.g., ".aider/config.yml"
        suffix = match.group(3)  # e.g., '"'

        # Change .aider to .cecli in the path string
        cecli_path_str = path_str.replace(".aider", ".cecli")
        return f'{prefix}handle_core_files("{cecli_path_str}"){suffix}'

    new_content = re.sub(direct_assignment_pattern, wrap_direct_with_handle_core_files, new_content)

    if new_content != original:
        # Find what changed for reporting (excluding the import we already tracked)
        orig_lines = original.split("\n")
        new_lines = new_content.split("\n")

        for i, (orig, new) in enumerate(zip(orig_lines, new_lines)):
            if orig != new and not (
                import_added
                and i == 0
                and new == "from cecli.helpers.file_searcher import handle_core_files"
            ):
                # Skip reporting the import line we already tracked
                changes.append(f"  Line {i+1}: {orig.strip()} -> {new.strip()}")

        if not dry_run:
            if backup:
                backup_path = filepath.with_suffix(filepath.suffix + ".bak")
                shutil.copy2(filepath, backup_path)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)

        return True, changes

    return False, []


def main():
    args = parse_args()
    project_root = Path(".")

    print("Renaming aider-ce to cecli")
    print("=" * 50)

    if args.dry_run:
        print("DRY RUN - No changes will be made")
    if args.backup:
        print("Backups will be created for modified files")
    print()

    updated_files = []
    skipped_files = []

    # Process all files
    for filepath in project_root.rglob("*"):
        if filepath.is_dir():
            continue

        if should_skip_file(filepath):
            skipped_files.append(filepath)
            continue

        file_updated = False
        changes = []

        try:
            # Python files
            if filepath.suffix == ".py" and not args.skip_python:
                # First update imports and references
                file_updated, changes = update_python_file(filepath, args.dry_run, args.backup)

                # Then update path assignments to use handle_core_files()
                if not args.skip_path_assignments:
                    path_updated, path_changes = update_path_assignments(
                        filepath, args.dry_run, args.backup
                    )
                    if path_updated:
                        file_updated = file_updated or path_updated
                        changes.extend(path_changes)

            # Other files
            elif not args.skip_other:
                file_updated, changes = update_other_file(filepath, args.dry_run, args.backup)

            if file_updated:
                updated_files.append((filepath, changes))
                print(f"✓ {filepath.relative_to(project_root)}")
                for change in changes[:3]:  # Show first 3 changes
                    print(change)
                if len(changes) > 3:
                    print(f"  ... and {len(changes) - 3} more changes")
                print()

        except Exception as e:
            print(f"✗ Error processing {filepath}: {e}")
            continue

    # Summary
    print("=" * 50)
    print(f"Summary:")
    print(f"  Files updated: {len(updated_files)}")
    print(f"  Files skipped: {len(skipped_files)}")

    if args.dry_run:
        print("\nThis was a dry run. To apply changes, run without --dry-run")

    if updated_files:
        print("\nUpdated files:")
        for filepath, changes in updated_files:
            print(f"  - {filepath.relative_to(project_root)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
