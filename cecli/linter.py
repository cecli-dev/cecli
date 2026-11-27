import asyncio
import os
import re
import sys
import tempfile
import traceback
import warnings
from dataclasses import dataclass
from pathlib import Path

import oslex

from cecli.dump import dump  # noqa: F401
from cecli.helpers.threading import ThreadSafeEvent
from cecli.run_cmd import run_cmd_async, run_cmd_subprocess  # noqa: F401

# tree_sitter is throwing a FutureWarning
warnings.simplefilter("ignore", category=FutureWarning)


class Linter:
    def __init__(self, encoding="utf-8", root=None, interrupt_event=None):
        self.encoding = encoding
        self.root = root
        self.interrupt_event = interrupt_event or ThreadSafeEvent()

        self.languages = dict(
            python=self.py_lint,
        )
        self.all_lint_cmd = None

    def set_linter(self, lang, cmd):
        if lang:
            self.languages[lang] = cmd
            return

        self.all_lint_cmd = cmd

    def get_rel_fname(self, fname):
        if self.root:
            try:
                return os.path.relpath(fname, self.root)
            except ValueError:
                return fname
        else:
            return fname

    async def run_cmd(self, cmd, rel_fname, code):
        cmd += " " + oslex.quote(rel_fname)

        returncode, stdout = await run_cmd_async(
            cmd,
            self.interrupt_event,
            cwd=self.root,
            encoding=self.encoding,
        )
        if stdout == "Interrupted":
            return

        errors = stdout
        if returncode == 0:
            return  # zero exit status

        res = f"## Running: {cmd}\n\n"
        res += errors

        return self.errors_to_lint_result(rel_fname, res)

    def errors_to_lint_result(self, rel_fname, errors):
        if not errors:
            return

        linenums = []
        filenames_linenums = find_filenames_and_linenums(errors, [rel_fname])
        if filenames_linenums:
            filename, linenums = next(iter(filenames_linenums.items()))
            linenums = [num - 1 for num in linenums]

        return LintResult(text=errors, lines=linenums)

    async def lint(self, fname, cmd=None):
        if self._is_temp_path(fname):
            return

        from cecli.helpers.grep_ast import filename_to_lang

        rel_fname = self.get_rel_fname(fname)
        try:
            code = Path(fname).read_text(encoding=self.encoding, errors="replace")
        except OSError as err:
            print(f"Unable to read {fname}: {err}")
            return

        if cmd:
            cmd = cmd.strip()
        if not cmd:
            lang = filename_to_lang(fname)
            if not lang:
                return
            if self.all_lint_cmd:
                cmd = self.all_lint_cmd
            else:
                cmd = self.languages.get(lang)

        if callable(cmd):
            # Check if the callable is a coroutine function
            if asyncio.iscoroutinefunction(cmd):
                lintres = await cmd(fname, rel_fname, code)
            else:
                lintres = cmd(fname, rel_fname, code)
        elif cmd:
            lintres = await self.run_cmd(cmd, rel_fname, code)
        else:
            lintres = basic_lint(rel_fname, code)

        if not lintres:
            return

        res = "# Fix any linting errors below, if possible.\n\n"
        res += lintres.text
        res += "\n"
        res += tree_context(rel_fname, code, lintres.lines)

        return res

    async def py_lint(self, fname, rel_fname, code):
        basic_res = basic_lint(rel_fname, code)
        compile_res = lint_python_compile(fname, code)
        flake_res = await self.flake8_lint(rel_fname)

        text = ""
        lines = set()
        for res in [basic_res, compile_res, flake_res]:
            if not res:
                continue
            if text:
                text += "\n"
            text += res.text
            lines.update(res.lines)

        if text or lines:
            return LintResult(text, lines)

    async def flake8_lint(self, rel_fname):
        fatal = "E9,F821,F823,F831,F406,F407,F701,F702,F704,F706"
        flake8_cmd_list = [
            sys.executable,
            "-m",
            "flake8",
            f"--select={fatal}",
            "--show-source",
            "--isolated",
            rel_fname,
        ]
        flake8_cmd = " ".join(flake8_cmd_list)

        text = f"## Running: {flake8_cmd}\n\n"

        returncode, stdout = await run_cmd_async(
            flake8_cmd,
            self.interrupt_event,
            cwd=self.root,
            encoding=self.encoding,
            should_print=False,
        )
        if stdout == "Interrupted":
            return

        errors = stdout
        if returncode == 0 or not errors:
            return

        text += errors
        return self.errors_to_lint_result(rel_fname, text)

    def _is_temp_path(self, fname):
        """Scratch files under .cecli/temp or the OS temp dirs are never linted."""

        parts = Path(fname).parts
        if any(
            parts[index].casefold() == ".cecli" and parts[index + 1].casefold() == "temp"
            for index in range(len(parts) - 1)
        ):
            return True

        absolute = Path(os.path.abspath(fname))
        if self.root and self._is_within(absolute, self.root):
            return False

        return any(self._is_within(absolute, root) for root in self._os_temp_roots())

    def _is_within(self, path, root):
        norm_path = os.path.normcase(os.path.realpath(path))
        norm_root = os.path.normcase(os.path.realpath(root))
        return norm_path == norm_root or norm_path.startswith(norm_root + os.sep)

    def _os_temp_roots(self):
        roots = [tempfile.gettempdir()]

        for name in ("TMPDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value:
                roots.append(value)

        if os.name != "nt":
            roots.extend(["/tmp", "/var/tmp"])

        return roots


@dataclass
class LintResult:
    text: str
    lines: list


def lint_python_compile(fname, code):
    try:
        compile(code, fname, "exec")  # USE TRACEBACK BELOW HERE
        return
    except Exception as err:
        end_lineno = getattr(err, "end_lineno", err.lineno)
        line_numbers = list(range(err.lineno - 1, end_lineno))

        tb_lines = traceback.format_exception(type(err), err, err.__traceback__)
        last_file_i = 0

        target = "# USE TRACEBACK"
        target += " BELOW HERE"
        for i in range(len(tb_lines)):
            if target in tb_lines[i]:
                last_file_i = i
                break

        tb_lines = tb_lines[:1] + tb_lines[last_file_i + 1 :]

    res = "".join(tb_lines)
    return LintResult(text=res, lines=line_numbers)


def basic_lint(fname, code):
    """
    Use tree-sitter to look for syntax errors, display them with tree context.
    """

    from cecli.helpers.grep_ast import filename_to_lang
    from cecli.helpers.grep_ast.tsl import get_parser

    lang = filename_to_lang(fname)
    if not lang:
        return

    # Tree-sitter linter is not capable of working with typescript #1132
    if lang == "typescript":
        return

    try:
        parser = get_parser(lang)
    except Exception as err:
        print(f"Unable to load parser: {err}")
        return

    tree = parser.parse(bytes(code, "utf-8"))

    try:
        errors = traverse_tree(tree.root_node)
    except RecursionError:
        print(f"Unable to lint {fname} due to RecursionError")
        return

    if not errors:
        return

    return LintResult(text="", lines=errors)


def tree_context(fname, code, line_nums):
    from cecli.helpers.grep_ast import TreeContext

    context = TreeContext(
        fname,
        code,
        color=False,
        line_number=True,
        child_context=False,
        last_line=False,
        margin=0,
        mark_lois=True,
        loi_pad=3,
        # header_max=30,
        show_top_of_file_parent_scope=False,
    )
    line_nums = set(line_nums)
    context.add_lines_of_interest(line_nums)
    context.add_context()
    s = "s" if len(line_nums) > 1 else ""
    output = f"## See relevant line{s} below marked with █.\n\n"
    output += fname + ":\n"
    output += context.format()

    return output


# Traverse the tree to find errors
def traverse_tree(node):
    errors = []
    if node.type == "ERROR" or node.is_missing:
        line_no = node.start_point[0]
        errors.append(line_no)

    for child in node.children:
        errors += traverse_tree(child)

    return errors


def find_filenames_and_linenums(text, fnames):
    """
    Search text for all occurrences of <filename>:\\d+ and make a list of them
    where <filename> is one of the filenames in the list `fnames`.
    """
    pattern = re.compile(r"(\b(?:" + "|".join(re.escape(fname) for fname in fnames) + r"):\d+\b)")
    matches = pattern.findall(text)
    result = {}
    for match in matches:
        fname, linenum = match.rsplit(":", 1)
        if fname not in result:
            result[fname] = set()
        result[fname].add(int(linenum))
    return result


def main():
    """
    Main function to parse files provided as command line arguments.
    """
    if len(sys.argv) < 2:
        print("Usage: python linter.py <file1> <file2> ...")
        sys.exit(1)

    linter = Linter(root=os.getcwd())
    for file_path in sys.argv[1:]:
        errors = linter.lint(file_path)
        if errors:
            print(errors)


if __name__ == "__main__":
    main()
