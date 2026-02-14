import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import oslex

from cecli.dump import dump  # noqa: F401
from cecli.waiting import Spinner

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".pdf"}


def expand_glob_patterns(patterns):
    """Expand glob patterns in a list of file paths."""
    expanded_files = []
    for pattern in patterns:
        # Check if the pattern contains glob characters
        if any(c in pattern for c in "*?[]"):
            # Use glob to expand the pattern
            matches = glob.glob(pattern, recursive=True)
            if matches:
                expanded_files.extend(matches)
            else:
                # If no matches, keep the original pattern
                expanded_files.append(pattern)
        else:
            # Not a glob pattern, keep as is
            expanded_files.append(pattern)
    return expanded_files


def _execute_fzf(input_data, multi=False):
    """
    Runs fzf as a subprocess, feeding it input_data.
    Returns the selected items.
    """
    if not shutil.which("fzf"):
        return []  # fzf not available

    fzf_command = ["fzf", "--read0"]
    if multi:
        fzf_command.append("--multi")

    # Recommended flags for a good experience
    fzf_command.extend(["--height", "80%", "--reverse"])

    process = subprocess.Popen(
        fzf_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=False,  # Use binary mode for null character handling
    )
    # fzf expects a null-separated list of strings for multi-line items
    # Join with null character instead of newline
    input_bytes = "\0".join(input_data).encode("utf-8")
    stdout, _ = process.communicate(input_bytes)

    if process.returncode == 0:
        # fzf returns selected items null-separated when using --read0
        output = stdout.decode("utf-8").rstrip("\0\n")
        return output.split("\0") if output else []
    else:
        # User cancelled (e.g., pressed Esc)
        return []


def run_fzf(input_data, multi=False, coder=None):
    """
    Runs fzf as a subprocess, feeding it input_data.
    Returns the selected items.
    """
    if not shutil.which("fzf"):
        return []  # fzf not available

    tui = None
    if coder is not None and coder.tui:
        tui = coder.tui()

    result = []

    if tui:
        result = tui.run_obstructive(_execute_fzf, input_data, multi=multi)

    else:
        result = _execute_fzf(input_data, multi=multi)

    return result


class IgnorantTemporaryDirectory:
    def __init__(self):
        if sys.version_info >= (3, 10):
            self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        else:
            self.temp_dir = tempfile.TemporaryDirectory()

    def __enter__(self):
        return self.temp_dir.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self):
        try:
            self.temp_dir.cleanup()
        except (OSError, PermissionError, RecursionError):
            pass  # Ignore errors (Windows and potential recursion)

    def __getattr__(self, item):
        return getattr(self.temp_dir, item)


class ChdirTemporaryDirectory(IgnorantTemporaryDirectory):
    def __init__(self):
        try:
            self.cwd = os.getcwd()
        except FileNotFoundError:
            self.cwd = None

        super().__init__()

    def __enter__(self):
        res = super().__enter__()
        os.chdir(Path(self.temp_dir.name).resolve())
        return res

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cwd:
            try:
                os.chdir(self.cwd)
            except FileNotFoundError:
                pass
        super().__exit__(exc_type, exc_val, exc_tb)


class GitTemporaryDirectory(ChdirTemporaryDirectory):
    def __enter__(self):
        dname = super().__enter__()
        self.repo = make_repo(dname)
        return dname

    def __exit__(self, exc_type, exc_val, exc_tb):
        del self.repo
        super().__exit__(exc_type, exc_val, exc_tb)


def make_repo(path=None):
    import git

    if not path:
        path = "."
    repo = git.Repo.init(path)
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "testuser@example.com").release()

    return repo


def is_image_file(file_name):
    """
    Check if the given file name has an image file extension.

    :param file_name: The name of the file to check.
    :return: True if the file is an image, False otherwise.
    """
    file_name = str(file_name)  # Convert file_name to string
    return any(file_name.endswith(ext) for ext in IMAGE_EXTENSIONS)


def safe_abs_path(res):
    "Gives an abs path, which safely returns a full (not 8.3) windows path"
    res = Path(res).resolve()
    return str(res)


def format_content(role, content):
    formatted_lines = []
    for line in content.splitlines():
        formatted_lines.append(f"{role} {line}")
    return "\n".join(formatted_lines)


def format_messages(messages, title=None):
    output = []
    if title:
        output.append(f"{title.upper()} {'*' * 50}")

    for msg in messages:
        output.append("-------")
        role = msg["role"].upper()
        content = msg.get("content")
        if isinstance(content, list):  # Handle list content (e.g., image messages)
            for item in content:
                if isinstance(item, dict):
                    for key, value in item.items():
                        if isinstance(value, dict) and "url" in value:
                            output.append(f"{role} {key.capitalize()} URL: {value['url']}")
                        else:
                            output.append(f"{role} {key}: {value}")
                else:
                    output.append(f"{role} {item}")
        elif isinstance(content, str):  # Handle string content
            # For large content, especially with many files, use a truncated display approach
            if len(content) > 5000:
                # Count the number of code blocks (approximation)
                fence_count = content.count("```") // 2
                if fence_count > 5:
                    # Show truncated content with file count for large files to improve performance
                    first_line = content.split("\n", 1)[0]
                    output.append(
                        f"{role} {first_line} [content with ~{fence_count} files truncated]"
                    )
                else:
                    output.append(format_content(role, content))
            else:
                output.append(format_content(role, content))
        function_call = msg.get("function_call")
        if function_call:
            output.append(f"{role} Function Call: {function_call}")

    return "\n".join(output)


def show_messages(messages, title=None, functions=None):
    formatted_output = format_messages(messages, title)
    print(formatted_output)

    if functions:
        dump(functions)


def split_chat_history_markdown(text, include_tool=False):
    messages = []
    user = []
    assistant = []
    tool = []
    lines = text.splitlines(keepends=True)

    def append_msg(role, lines):
        lines = "".join(lines)
        if lines.strip():
            messages.append(dict(role=role, content=lines))

    for line in lines:
        if line.startswith("# "):
            continue
        if line.startswith("> "):
            append_msg("assistant", assistant)
            assistant = []
            append_msg("user", user)
            user = []
            tool.append(line[2:])
            continue
        # if line.startswith("#### /"):
        #    continue

        if line.startswith("#### "):
            append_msg("assistant", assistant)
            assistant = []
            append_msg("tool", tool)
            tool = []

            content = line[5:]
            user.append(content)
            continue

        append_msg("user", user)
        user = []
        append_msg("tool", tool)
        tool = []

        assistant.append(line)

    append_msg("assistant", assistant)
    append_msg("user", user)

    if not include_tool:
        messages = [m for m in messages if m["role"] != "tool"]

    return messages


def get_pip_install(args):
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--upgrade-strategy",
        "only-if-needed",
    ]
    cmd += args
    return cmd


def run_install(cmd):
    print()
    print("Installing:", printable_shell_command(cmd))

    # First ensure pip is available
    ensurepip_cmd = [sys.executable, "-m", "ensurepip", "--upgrade"]
    try:
        subprocess.run(ensurepip_cmd, capture_output=True, check=False)
    except Exception:
        pass  # Continue even if ensurepip fails

    try:
        output = []
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            encoding=sys.stdout.encoding,
            errors="replace",
        )
        spinner = Spinner("Installing...")

        while True:
            char = process.stdout.read(1)
            if not char:
                break

            output.append(char)
            spinner.step()

        spinner.end()
        return_code = process.wait()
        output = "".join(output)

        if return_code == 0:
            print("Installation complete.")
            print()
            return True, output

    except subprocess.CalledProcessError as e:
        print(f"\nError running pip install: {e}")

    print("\nInstallation failed.\n")

    return False, output


def find_common_root(abs_fnames):
    try:
        if len(abs_fnames) == 1:
            return safe_abs_path(os.path.dirname(list(abs_fnames)[0]))
        elif abs_fnames:
            return safe_abs_path(os.path.commonpath(list(abs_fnames)))
    except OSError:
        pass

    try:
        return safe_abs_path(os.getcwd())
    except FileNotFoundError:
        # Fallback if cwd is deleted
        return "."


def format_tokens(count):
    if count < 1000:
        return f"{count}"
    elif count < 10000:
        return f"{count / 1000:.1f}k"
    else:
        return f"{round(count / 1000)}k"


def touch_file(fname):
    fname = Path(fname)
    try:
        fname.parent.mkdir(parents=True, exist_ok=True)
        fname.touch()
        return True
    except OSError:
        return False


async def check_pip_install_extra(io, module, prompt, pip_install_cmd, self_update=False):
    if module:
        try:
            __import__(module)
            return True
        except (ImportError, ModuleNotFoundError, RuntimeError):
            pass

    cmd = get_pip_install(pip_install_cmd)

    if prompt:
        io.tool_warning(prompt)

    if self_update and platform.system() == "Windows":
        io.tool_output("Run this command to update:")
        print()
        print(printable_shell_command(cmd))  # plain print so it doesn't line-wrap
        return

    if not await io.confirm_ask(
        "Run pip install?", default="y", subject=printable_shell_command(cmd)
    ):
        return

    success, output = run_install(cmd)
    if success:
        if not module:
            return True
        try:
            __import__(module)
            return True
        except (ImportError, ModuleNotFoundError, RuntimeError) as err:
            io.tool_error(str(err))
            pass

    io.tool_error(output)

    print()
    print("Install failed, try running this command manually:")
    print(printable_shell_command(cmd))


def printable_shell_command(cmd_list):
    """
    Convert a list of command arguments to a properly shell-escaped string.

    Args:
        cmd_list (list): List of command arguments.

    Returns:
        str: Shell-escaped command string.
    """
    return oslex.join(cmd_list)


def split_concatenated_json(s: str) -> list[str]:
    """
    Splits a string containing one or more concatenated JSON objects
    and returns them as a list of raw strings.
    """
    res = []
    decoder = json.JSONDecoder()
    idx = 0
    s_len = len(s)

    while idx < s_len:
        # 1. Use Regex-free "find" to jump to the next potential JSON start
        # This replaces your manual 'while s[i].isspace()' loop
        brace_idx = s.find("{", idx)
        bracket_idx = s.find("[", idx)

        # Determine the earliest starting point
        if brace_idx == -1 and bracket_idx == -1:
            # No more JSON documents found, but check for trailing text
            remainder = s[idx:].strip()
            if remainder:
                res.append(s[idx:])
            break

        # Set idx to the first '{' or '[' found
        start_index = (
            min(brace_idx, bracket_idx)
            if (brace_idx != -1 and bracket_idx != -1)
            else max(brace_idx, bracket_idx)
        )

        try:
            # 2. Let the C-optimized parser find the end of the object
            _, end_idx = decoder.raw_decode(s, start_index)

            # 3. Slice the original string and add to results
            res.append(s[start_index:end_idx])

            # Move our pointer to the end of the last document
            idx = end_idx

        except json.JSONDecodeError:
            # If it looks like JSON but fails (e.g. malformed),
            # we skip this character and try to find the next valid start
            idx = start_index + 1

    return res


def parse_concatenated_json(s: str) -> list:
    objs = []
    decoder = json.JSONDecoder()
    idx = 0
    s_len = len(s)

    while idx < s_len:
        # Jump to the next potential start of a JSON object or array
        # This skips whitespace, commas, or "noise" between documents instantly
        brace_idx = s.find("{", idx)
        bracket_idx = s.find("[", idx)

        # Determine which one comes first
        if brace_idx == -1 and bracket_idx == -1:
            break
        elif brace_idx == -1:
            idx = bracket_idx
        elif bracket_idx == -1:
            idx = brace_idx
        else:
            idx = min(brace_idx, bracket_idx)

        try:
            # raw_decode attempts to parse starting exactly at idx
            obj, end_idx = decoder.raw_decode(s, idx)
            objs.append(obj)
            idx = end_idx
        except json.JSONDecodeError:
            # If it's a false start (like a { inside a non-JSON string),
            # skip it and keep looking
            idx += 1

    return objs


def copy_tool_call(tool_call):
    """
    Copies a tool call whether it's a Pydantic model, SimpleNamespace, or dict.
    """
    from types import SimpleNamespace

    if hasattr(tool_call, "model_copy"):
        return tool_call.model_copy(deep=True)
    if isinstance(tool_call, SimpleNamespace):
        import copy

        return copy.deepcopy(tool_call)
    if isinstance(tool_call, dict):
        import copy

        return copy.deepcopy(tool_call)
    return tool_call


def tool_call_to_dict(tool_call):
    """
    Converts any tool-call representation to a dict.
    """
    if hasattr(tool_call, "model_dump"):
        return tool_call.model_dump()
    if hasattr(tool_call, "__dict__"):
        res = dict(tool_call.__dict__)
        if "function" in res and hasattr(res["function"], "__dict__"):
            res["function"] = dict(res["function"].__dict__)
        return res
    if isinstance(tool_call, dict):
        return tool_call
    return {}
