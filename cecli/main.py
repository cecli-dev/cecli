import os

from cecli.helpers.file_searcher import handle_core_files

try:
    if not os.getenv("CECLIDEFAULT_TLS"):
        import truststore

        truststore.inject_into_ssl()
except Exception as e:
    print(e)
    pass
import asyncio
import json
import os
import re
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import fields
from pathlib import Path

try:
    import git
except ImportError:
    git = None
import importlib_resources
import shtab
from dotenv import load_dotenv

if sys.platform == "win32":
    if hasattr(asyncio, "set_event_loop_policy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from prompt_toolkit.enums import EditingMode

from cecli import __version__, models, urls, utils
from cecli.args import get_parser
from cecli.coders import Coder
from cecli.coders.base_coder import UnknownEditFormat
from cecli.commands import Commands, SwitchCoder
from cecli.deprecated_args import handle_deprecated_model_args
from cecli.format_settings import format_settings, scrub_sensitive_info
from cecli.helpers.copypaste import ClipboardWatcher
from cecli.helpers.file_searcher import generate_search_path_list
from cecli.history import ChatSummary
from cecli.io import InputOutput
from cecli.llm import litellm
from cecli.mcp import load_mcp_servers
from cecli.models import ModelSettings
from cecli.onboarding import offer_openrouter_oauth, select_default_model
from cecli.repo import ANY_GIT_ERROR, GitRepo
from cecli.report import report_uncaught_exceptions, set_args_error_data
from cecli.versioncheck import check_version, install_from_main_branch, install_upgrade
from cecli.watch import FileWatcher

from .dump import dump  # noqa


def convert_yaml_to_json_string(value):
    """
    Convert YAML dict/list values to JSON strings for compatibility.

    configargparse.YAMLConfigFileParser converts YAML to Python objects,
    but some arguments expect JSON strings. This function handles:
    - Direct dict/list objects
    - String representations of dicts/lists (Python literals)
    - Already JSON strings (passed through unchanged)

    Args:
        value: The value to convert

    Returns:
        str: JSON string if value is a dict/list, otherwise the original value
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, str):
        try:
            import ast

            parsed = ast.literal_eval(value)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed)
        except (SyntaxError, ValueError):
            pass
    return value


def check_config_files_for_yes(config_files):
    found = False
    for config_file in config_files:
        if Path(config_file).exists():
            try:
                with open(config_file, "r") as f:
                    for line in f:
                        if line.strip().startswith("yes:"):
                            print("Configuration error detected.")
                            print(f"The file {config_file} contains a line starting with 'yes:'")
                            print("Please replace 'yes:' with 'yes-always:' in this file.")
                            found = True
            except Exception:
                pass
    return found


def get_git_root():
    """Try and guess the git repo, since the conf.yml can be at the repo root"""
    try:
        repo = git.Repo(search_parent_directories=True)
        return repo.working_tree_dir
    except (git.InvalidGitRepositoryError, FileNotFoundError):
        return None


def guessed_wrong_repo(io, git_root, fnames, git_dname):
    """After we parse the args, we can determine the real repo. Did we guess wrong?"""
    try:
        check_repo = Path(GitRepo(io, fnames, git_dname).root).resolve()
    except (OSError,) + ANY_GIT_ERROR:
        return
    if not git_root:
        return str(check_repo)
    git_root = Path(git_root).resolve()
    if check_repo == git_root:
        return
    return str(check_repo)


def validate_tui_args(args):
    """Validate that incompatible flags aren't used with --tui"""
    if not args.tui:
        return
    incompatible = []
    if args.vim:
        incompatible.append("--vim")
    if not args.fancy_input:
        incompatible.append("--no-fancy-input")
    if incompatible:
        print(f"Error: --tui is incompatible with: {', '.join(incompatible)}")
        print("Remove these flags or use standard CLI mode.")
        sys.exit(1)


async def make_new_repo(git_root, io):
    try:
        repo = git.Repo.init(git_root)
        await check_gitignore(git_root, io, False)
    except ANY_GIT_ERROR as err:
        io.tool_error(f"Unable to create git repo in {git_root}")
        io.tool_output(str(err))
        return
    io.tool_output(f"Git repository created in {git_root}")
    return repo


async def setup_git(git_root, io):
    if git is None:
        return
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None
    repo = None
    if git_root:
        try:
            repo = git.Repo(git_root)
        except ANY_GIT_ERROR:
            pass
    elif cwd == Path.home():
        io.tool_warning(
            "You should probably run cecli in your project's directory, not your home dir."
        )
        return
    elif cwd and await io.confirm_ask(
        "No git repo found, create one to track cecli's changes (recommended)?", acknowledge=True
    ):
        git_root = str(cwd.resolve())
        repo = await make_new_repo(git_root, io)
    if not repo:
        return
    try:
        user_name = repo.git.config("--get", "user.name") or None
    except git.exc.GitCommandError:
        user_name = None
    try:
        user_email = repo.git.config("--get", "user.email") or None
    except git.exc.GitCommandError:
        user_email = None
    if user_name and user_email:
        return repo.working_tree_dir
    with repo.config_writer() as git_config:
        if not user_name:
            git_config.set_value("user", "name", "Your Name")
            io.tool_warning('Update git name with: git config user.name "Your Name"')
        if not user_email:
            git_config.set_value("user", "email", "you@example.com")
            io.tool_warning('Update git email with: git config user.email "you@example.com"')
    return repo.working_tree_dir


async def check_gitignore(git_root, io, ask=True):
    if not git_root:
        return
    try:
        repo = git.Repo(git_root)
        patterns_to_add = []
        if not repo.ignored(".cecli"):
            patterns_to_add.append(".cecli*")
        env_path = Path(git_root) / ".env"
        if env_path.exists() and not repo.ignored(".env"):
            patterns_to_add.append(".env")
        if not patterns_to_add:
            return
        gitignore_file = Path(git_root) / ".gitignore"
        if gitignore_file.exists():
            try:
                content = io.read_text(gitignore_file)
                if content is None:
                    return
                if not content.endswith("\n"):
                    content += "\n"
            except OSError as e:
                io.tool_error(f"Error when trying to read {gitignore_file}: {e}")
                return
        else:
            content = ""
    except ANY_GIT_ERROR:
        return
    if ask:
        io.tool_output("You can skip this check with --no-gitignore")
        if not await io.confirm_ask(
            f"Add {', '.join(patterns_to_add)} to .gitignore (recommended)?", acknowledge=True
        ):
            return
    content += "\n".join(patterns_to_add) + "\n"
    try:
        io.write_text(gitignore_file, content)
        io.tool_output(f"Added {', '.join(patterns_to_add)} to .gitignore")
    except OSError as e:
        io.tool_error(f"Error when trying to write to {gitignore_file}: {e}")
        io.tool_output(
            "Try running with appropriate permissions or manually add these patterns to .gitignore:"
        )
        for pattern in patterns_to_add:
            io.tool_output(f"  {pattern}")


def parse_lint_cmds(lint_cmds, io):
    err = False
    res = dict()
    for lint_cmd in lint_cmds:
        if re.match("^[a-z]+:.*", lint_cmd):
            pieces = lint_cmd.split(":")
            lang = pieces[0]
            cmd = lint_cmd[len(lang) + 1 :]
            lang = lang.strip()
        else:
            lang = None
            cmd = lint_cmd
        cmd = cmd.strip()
        if cmd:
            res[lang] = cmd
        else:
            io.tool_error(f'Unable to parse --lint-cmd "{lint_cmd}"')
            io.tool_output('The arg should be "language: cmd --args ..."')
            io.tool_output('For example: --lint-cmd "python: flake8 --select=E9"')
            err = True
    if err:
        return
    return res


def register_models(git_root, model_settings_fname, io, verbose=False):
    model_settings_files = generate_search_path_list(
        ".cecli.model.settings.yml", git_root, model_settings_fname
    )
    try:
        files_loaded = models.register_models(model_settings_files)
        if len(files_loaded) > 0:
            if verbose:
                io.tool_output("Loaded model settings from:")
                for file_loaded in files_loaded:
                    io.tool_output(f"  - {file_loaded}")
        elif verbose:
            io.tool_output("No model settings files loaded")
        if (
            model_settings_fname
            and model_settings_fname not in files_loaded
            and model_settings_fname != ".cecli.model.settings.yml"
        ):
            io.tool_warning(f"Model Settings File Not Found: {model_settings_fname}")
    except Exception as e:
        io.tool_error(f"Error loading cecli model settings: {e}")
        return 1
    if verbose:
        io.tool_output("Searched for model settings files:")
        for file in model_settings_files:
            io.tool_output(f"  - {file}")
    return None


def load_dotenv_files(git_root, dotenv_fname, encoding="utf-8"):
    dotenv_files = generate_search_path_list(".env", git_root, dotenv_fname)
    oauth_keys_file = handle_core_files(Path.home() / ".cecli" / "oauth-keys.env")
    if oauth_keys_file.exists():
        dotenv_files.insert(0, str(oauth_keys_file.resolve()))
        dotenv_files = list(dict.fromkeys(dotenv_files))
    loaded = []
    for fname in dotenv_files:
        try:
            if Path(fname).exists():
                load_dotenv(fname, override=True, encoding=encoding)
                loaded.append(fname)
        except OSError as e:
            print(f"OSError loading {fname}: {e}")
        except Exception as e:
            print(f"Error loading {fname}: {e}")
    return loaded


def register_litellm_models(git_root, model_metadata_fname, io, verbose=False):
    model_metadata_files = []
    resource_metadata = importlib_resources.files("cecli.resources").joinpath("model-metadata.json")
    model_metadata_files.append(str(resource_metadata))
    model_metadata_files += generate_search_path_list(
        ".cecli.model.metadata.json", git_root, model_metadata_fname
    )
    try:
        model_metadata_files_loaded = models.register_litellm_models(model_metadata_files)
        if len(model_metadata_files_loaded) > 0 and verbose:
            io.tool_output("Loaded model metadata from:")
            for model_metadata_file in model_metadata_files_loaded:
                io.tool_output(f"  - {model_metadata_file}")
        if (
            model_metadata_fname
            and model_metadata_fname not in model_metadata_files_loaded
            and model_metadata_fname != ".cecli.model.metadata.json"
        ):
            io.tool_warning(f"Model Metadata File Not Found: {model_metadata_fname}")
    except Exception as e:
        io.tool_error(f"Error loading model metadata models: {e}")
        return 1


def load_model_overrides(git_root, model_overrides_fname, io, verbose=False):
    """Load model tag overrides from a YAML file."""
    from pathlib import Path

    import yaml

    model_overrides_files = generate_search_path_list(
        ".cecli.model.overrides.yml", git_root, model_overrides_fname
    )
    overrides = {}
    files_loaded = []
    for fname in model_overrides_files:
        try:
            if Path(fname).exists():
                with open(fname, "r") as f:
                    content = yaml.safe_load(f)
                    if content:
                        for model_name, tags in content.items():
                            if model_name not in overrides:
                                overrides[model_name] = {}
                            overrides[model_name].update(tags)
                        files_loaded.append(fname)
        except Exception as e:
            io.tool_error(f"Error loading model overrides from {fname}: {e}")
    if len(files_loaded) > 0 and verbose:
        io.tool_output("Loaded model overrides from:")
        for file_loaded in files_loaded:
            io.tool_output(f"  - {file_loaded}")
    if (
        model_overrides_fname
        and model_overrides_fname not in files_loaded
        and model_overrides_fname != ".cecli.model.overrides.yml"
    ):
        io.tool_warning(f"Model Overrides File Not Found: {model_overrides_fname}")
    return overrides


def load_model_overrides_from_string(model_overrides_str, io):
    """Load model tag overrides from a JSON/YAML string."""
    import json

    import yaml

    overrides = {}
    if not model_overrides_str:
        return overrides
    try:
        try:
            content = json.loads(model_overrides_str)
        except json.JSONDecodeError:
            content = yaml.safe_load(model_overrides_str)
        if content and isinstance(content, dict):
            for model_name, tags in content.items():
                if model_name not in overrides:
                    overrides[model_name] = {}
                overrides[model_name].update(tags)
        return overrides
    except Exception as e:
        io.tool_error(f"Error parsing model overrides string: {e}")
        return {}


async def sanity_check_repo(repo, io):
    if not repo:
        return True
    if not repo.repo.working_tree_dir:
        io.tool_error("The git repo does not seem to have a working tree?")
        return False
    bad_ver = False
    try:
        repo.get_tracked_files()
        if not repo.git_repo_error:
            return True
        error_msg = str(repo.git_repo_error)
    except UnicodeDecodeError as exc:
        error_msg = (
            "Failed to read the Git repository. "
            "This issue is likely caused by a path encoded in a format different from "
            f'the expected encoding "{sys.getfilesystemencoding()}"\n'
            f"Internal error: {str(exc)}"
        )
    except ANY_GIT_ERROR as exc:
        error_msg = str(exc)
        bad_ver = "version in (1, 2)" in error_msg
    except AssertionError as exc:
        error_msg = str(exc)
        bad_ver = True
    if bad_ver:
        io.tool_error("cecli only works with git repos with version number 1 or 2.")
        io.tool_output("You may be able to convert your repo: git update-index --index-version=2")
        io.tool_output("Or run cecli --no-git to proceed without using git.")
        await io.offer_url(
            urls.git_index_version, "Open documentation url for more info?", acknowledge=True
        )
        return False
    io.tool_error("Unable to read git repository, it may be corrupt?")
    io.tool_output(error_msg)
    return False


PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
log_file = None
file_excludelist = {
    "get_bottom_toolbar": True,
    "<genexpr>": True,
    "is_active": True,
    "auto_save_session": True,
    "input_task": True,
    "output_task": True,
    "check_output_queue": True,
    "_animate_spinner": True,
    "handle_output_message": True,
    "update_spinner": True,
}


def custom_tracer(frame, event, arg):
    try:
        import os
    except Exception:
        return None
    global log_file
    if not log_file:
        os.makedirs(".cecli/logs/", exist_ok=True)
        log_file = open(".cecli/logs/debug.log", "w", buffering=1)
    filename = os.path.abspath(frame.f_code.co_filename)
    if not filename.startswith(PROJECT_ROOT):
        return None
    if filename.endswith("repo.py"):
        return None
    if event == "call":
        func_name = frame.f_code.co_name
        line_no = frame.f_lineno
        if func_name not in file_excludelist:
            log_file.write(
                f"""-> CALL: {func_name}() in {os.path.basename(filename)}:{line_no} - {time.time()}
"""
            )
    if event == "return":
        func_name = frame.f_code.co_name
        line_no = frame.f_lineno
        if func_name not in file_excludelist:
            log_file.write(
                f"""<- RETURN: {func_name}() in {os.path.basename(filename)}:{line_no} - {time.time()}
"""
            )
    return custom_tracer


def main(argv=None, input=None, output=None, force_git_root=None, return_coder=False):
    if sys.platform == "win32":
        if sys.version_info >= (3, 12) and hasattr(asyncio, "SelectorEventLoop"):
            return asyncio.run(
                main_async(argv, input, output, force_git_root, return_coder),
                loop_factory=asyncio.SelectorEventLoop,
            )
    return asyncio.run(main_async(argv, input, output, force_git_root, return_coder))


async def main_async(argv=None, input=None, output=None, force_git_root=None, return_coder=False):
    report_uncaught_exceptions()
    if argv is None:
        argv = sys.argv[1:]
    if git is None:
        git_root = None
    elif force_git_root:
        git_root = force_git_root
    else:
        git_root = get_git_root()
    conf_fname = handle_core_files(Path(".cecli.conf.yml"))
    default_config_files = []
    try:
        default_config_files += [conf_fname.resolve()]
    except OSError:
        pass
    if git_root:
        git_conf = Path(git_root) / conf_fname
        if git_conf not in default_config_files:
            default_config_files.append(git_conf)
    default_config_files.append(Path.home() / conf_fname)
    default_config_files = list(map(str, default_config_files))
    parser = get_parser(default_config_files, git_root)
    try:
        args, unknown = parser.parse_known_args(argv)
    except AttributeError as e:
        if all(word in str(e) for word in ["bool", "object", "has", "no", "attribute", "strip"]):
            if check_config_files_for_yes(default_config_files):
                return await graceful_exit(None, 1)
        raise e
    if args.verbose:
        print("Config files search order, if no --config:")
        for file in default_config_files:
            exists = "(exists)" if Path(file).exists() else ""
            print(f"  - {file} {exists}")
    default_config_files.reverse()
    parser = get_parser(default_config_files, git_root)
    args, unknown = parser.parse_known_args(argv)
    loaded_dotenvs = load_dotenv_files(git_root, args.env_file, args.encoding)
    args, unknown = parser.parse_known_args(argv)
    set_args_error_data(args)
    if len(unknown):
        print("Unknown Args: ", unknown)
    if hasattr(args, "agent_config") and args.agent_config is not None:
        args.agent_config = convert_yaml_to_json_string(args.agent_config)
    if hasattr(args, "tui_config") and args.tui_config is not None:
        args.tui_config = convert_yaml_to_json_string(args.tui_config)
    if hasattr(args, "mcp_servers") and args.mcp_servers is not None:
        args.mcp_servers = convert_yaml_to_json_string(args.mcp_servers)
    if args.debug:
        global log_file
        os.makedirs(".cecli/logs/", exist_ok=True)
        log_file = open(".cecli/logs/debug.log", "w", buffering=1)
        sys.settrace(custom_tracer)
    if args.shell_completions:
        parser.prog = "cecli"
        print(shtab.complete(parser, shell=args.shell_completions))
        return await graceful_exit(None, 0)
    if git is None:
        args.git = False
    if not args.verify_ssl:
        import httpx

        os.environ["SSL_VERIFY"] = ""
        litellm._load_litellm()
        litellm._lazy_module.client_session = httpx.Client(verify=False)
        litellm._lazy_module.aclient_session = httpx.AsyncClient(verify=False)
        models.model_info_manager.set_verify_ssl(False)
    if args.timeout:
        models.request_timeout = args.timeout
    if args.dark_mode:
        args.user_input_color = "#32FF32"
        args.tool_error_color = "#FF3333"
        args.tool_warning_color = "#FFFF00"
        args.assistant_output_color = "#00FFFF"
        args.code_theme = "monokai"
    if args.light_mode:
        args.user_input_color = "green"
        args.tool_error_color = "red"
        args.tool_warning_color = "#FFA500"
        args.assistant_output_color = "blue"
        args.code_theme = "default"
    if return_coder and args.yes_always is None:
        args.yes_always = True
    if args.yes_always_commands:
        args.yes_always = True
    editing_mode = EditingMode.VI if args.vim else EditingMode.EMACS

    def get_io(pretty):
        return InputOutput(
            pretty,
            args.yes_always,
            args.input_history_file,
            args.chat_history_file,
            input=input,
            output=output,
            user_input_color=args.user_input_color,
            tool_output_color=args.tool_output_color,
            tool_warning_color=args.tool_warning_color,
            tool_error_color=args.tool_error_color,
            completion_menu_color=args.completion_menu_color,
            completion_menu_bg_color=args.completion_menu_bg_color,
            completion_menu_current_color=args.completion_menu_current_color,
            completion_menu_current_bg_color=args.completion_menu_current_bg_color,
            assistant_output_color=args.assistant_output_color,
            code_theme=args.code_theme,
            dry_run=args.dry_run,
            encoding=args.encoding,
            line_endings=args.line_endings,
            editingmode=editing_mode,
            fancy_input=args.fancy_input,
            multiline_mode=args.multiline,
            notifications=args.notifications,
            notifications_command=args.notifications_command,
            verbose=args.verbose,
        )

    validate_tui_args(args)
    output_queue = None
    input_queue = None
    pre_init_io = get_io(args.pretty)
    if args.tui or args.tui is None and not args.linear_output:
        try:
            from cecli.tui import create_tui_io

            args.tui = True
            args.linear_output = True
            print("Starting cecli TUI...", flush=True)
            io, output_queue, input_queue = create_tui_io(args, editing_mode)
        except ImportError as e:
            print("Error: --tui requires 'textual' package")
            print("Install with: pip install cecli[tui]")
            print(f"Import error: {e}")
            sys.exit(1)
    else:
        io = pre_init_io
    if not args.tui:
        try:
            io.rule()
        except UnicodeEncodeError as err:
            if not io.pretty:
                raise err
            io = get_io(False)
            io.tool_warning("Terminal does not support pretty output (UnicodeDecodeError)")
    if args.set_env:
        for env_setting in args.set_env:
            try:
                name, value = env_setting.split("=", 1)
                os.environ[name.strip()] = value.strip()
            except ValueError:
                io.tool_error(f"Invalid --set-env format: {env_setting}")
                io.tool_output("Format should be: ENV_VAR_NAME=value")
                return await graceful_exit(None, 1)
    if args.api_key:
        for api_setting in args.api_key:
            try:
                provider, key = api_setting.split("=", 1)
                env_var = f"{provider.strip().upper()}_API_KEY"
                os.environ[env_var] = key.strip()
            except ValueError:
                io.tool_error(f"Invalid --api-key format: {api_setting}")
                io.tool_output("Format should be: provider=key")
                return await graceful_exit(None, 1)
    if args.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.anthropic_api_key
    if args.openai_api_key:
        os.environ["OPENAI_API_KEY"] = args.openai_api_key
    handle_deprecated_model_args(args, io)
    if args.openai_api_base:
        os.environ["OPENAI_API_BASE"] = args.openai_api_base
    if args.openai_api_version:
        io.tool_warning(
            "--openai-api-version is deprecated, use --set-env OPENAI_API_VERSION=<value>"
        )
        os.environ["OPENAI_API_VERSION"] = args.openai_api_version
    if args.openai_api_type:
        io.tool_warning("--openai-api-type is deprecated, use --set-env OPENAI_API_TYPE=<value>")
        os.environ["OPENAI_API_TYPE"] = args.openai_api_type
    if args.openai_organization_id:
        io.tool_warning(
            "--openai-organization-id is deprecated, use --set-env OPENAI_ORGANIZATION=<value>"
        )
        os.environ["OPENAI_ORGANIZATION"] = args.openai_organization_id
    if args.verbose:
        for fname in loaded_dotenvs:
            io.tool_output(f"Loaded {fname}")
    all_files = args.files + (args.file or [])
    all_files = utils.expand_glob_patterns(all_files)
    fnames = [str(Path(fn).resolve()) for fn in all_files]
    read_patterns = args.read or []
    read_expanded = utils.expand_glob_patterns(read_patterns)
    read_only_fnames = []
    for fn in read_expanded:
        path = Path(fn).expanduser().resolve()
        if path.is_dir():
            read_only_fnames.extend(str(f) for f in path.rglob("*") if f.is_file())
        else:
            read_only_fnames.append(str(path))
    if len(all_files) > 1:
        good = True
        for fname in all_files:
            if Path(fname).is_dir():
                io.tool_error(f"{fname} is a directory, not provided alone.")
                good = False
        if not good:
            io.tool_output(
                "Provide either a single directory of a git repo, or a list of one or more files."
            )
            return await graceful_exit(None, 1)
    git_dname = None
    if len(all_files) == 1:
        if Path(all_files[0]).is_dir():
            if args.git:
                git_dname = str(Path(all_files[0]).resolve())
                fnames = []
            else:
                io.tool_error(f"{all_files[0]} is a directory, but --no-git selected.")
                return await graceful_exit(None, 1)
    if args.git and not force_git_root and git is not None:
        right_repo_root = guessed_wrong_repo(io, git_root, fnames, git_dname)
        if right_repo_root:
            return await main_async(argv, input, output, right_repo_root, return_coder=return_coder)
    if args.just_check_update:
        update_available = await check_version(io, just_check=True, verbose=args.verbose)
        return await graceful_exit(None, 0 if not update_available else 1)
    if args.install_main_branch:
        success = await install_from_main_branch(io)
        return await graceful_exit(None, 0 if success else 1)
    if args.upgrade:
        success = await install_upgrade(io)
        return await graceful_exit(None, 0 if success else 1)
    if args.check_update:
        await check_version(io, verbose=args.verbose)
    if args.verbose:
        show = format_settings(parser, args)
        io.tool_output(show)
    cmd_line = " ".join(sys.argv)
    cmd_line = scrub_sensitive_info(args, cmd_line)
    io.tool_output(cmd_line, log_only=True)
    is_first_run = is_first_run_of_new_version(io, verbose=args.verbose)
    await check_and_load_imports(io, is_first_run, verbose=args.verbose)
    register_models(git_root, args.model_settings_file, io, verbose=args.verbose)
    register_litellm_models(git_root, args.model_metadata_file, io, verbose=args.verbose)
    if args.list_models:
        models.print_matching_models(io, args.list_models)
        return await graceful_exit(None)
    if args.alias:
        for alias_def in args.alias:
            parts = alias_def.split(":", 1)
            if len(parts) != 2:
                io.tool_error(f"Invalid alias format: {alias_def}")
                io.tool_output("Format should be: alias:model-name")
                return await graceful_exit(None, 1)
            alias, model = parts
            models.MODEL_ALIASES[alias.strip()] = model.strip()
    selected_model_name = await select_default_model(args, io)
    if not selected_model_name:
        return await graceful_exit(None, 1)
    args.model = selected_model_name
    model_overrides = {}
    if args.model_overrides_file:
        model_overrides = load_model_overrides(
            git_root, args.model_overrides_file, io, verbose=args.verbose
        )
    if args.model_overrides:
        direct_overrides = load_model_overrides_from_string(args.model_overrides, io)
        for model_name, tags in direct_overrides.items():
            if model_name not in model_overrides:
                model_overrides[model_name] = {}
            model_overrides[model_name].update(tags)
    override_index = {}
    for base_model, suffixes in model_overrides.items():
        if not isinstance(suffixes, dict):
            continue
        for suffix, cfg in suffixes.items():
            if not isinstance(cfg, dict):
                continue
            full_name = f"{base_model}:{suffix}"
            override_index[full_name] = base_model, cfg

    def apply_model_overrides(model_name):
        """Return (effective_model_name, override_kwargs) for a given model_name.

        If model_name exactly matches a configured "base:suffix" override, we
        switch to the base model and apply that override dict. Otherwise we
        leave the name unchanged and return empty overrides.
        """
        if not model_name:
            return model_name, {}
        prefix = ""
        if model_name.startswith(models.COPY_PASTE_PREFIX):
            prefix = models.COPY_PASTE_PREFIX
            model_name = model_name[len(prefix) :]
        entry = override_index.get(model_name)
        if not entry:
            model_name = prefix + model_name
            return model_name, {}
        base_model, cfg = entry
        model_name = prefix + base_model
        return model_name, cfg.copy()

    main_model_name, main_model_overrides = apply_model_overrides(args.model)
    weak_model_name, weak_model_overrides = apply_model_overrides(args.weak_model)
    editor_model_name, editor_model_overrides = apply_model_overrides(args.editor_model)
    weak_model_obj = None
    if weak_model_name:
        weak_model_obj = models.Model(
            weak_model_name,
            weak_model=False,
            verbose=args.verbose,
            io=io,
            override_kwargs=weak_model_overrides,
        )
    editor_model_obj = None
    if editor_model_name:
        editor_model_obj = models.Model(
            editor_model_name,
            editor_model=False,
            verbose=args.verbose,
            io=io,
            override_kwargs=editor_model_overrides,
        )
    if main_model_name.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
        io.tool_warning(
            f"The specified model '{main_model_name}' requires an OpenRouter API key, which was not"
            " found."
        )
        if await offer_openrouter_oauth(io):
            if os.environ.get("OPENROUTER_API_KEY"):
                io.tool_output("OpenRouter successfully connected.")
            else:
                io.tool_error(
                    "OpenRouter authentication seemed successful, but the key is still missing."
                )
                return await graceful_exit(None, 1)
        else:
            io.tool_error(
                f"Unable to proceed without an OpenRouter API key for model '{main_model_name}'."
            )
            await io.offer_url(
                urls.models_and_keys, "Open documentation URL for more info?", acknowledge=True
            )
            return await graceful_exit(None, 1)
    main_model = models.Model(
        main_model_name,
        weak_model=weak_model_obj,
        editor_model=editor_model_obj,
        editor_edit_format=args.editor_edit_format,
        verbose=args.verbose,
        io=io,
        override_kwargs=main_model_overrides,
    )
    if args.copy_paste and main_model.copy_paste_transport == "api":
        main_model.enable_copy_paste_mode()
    if main_model.remove_reasoning is not None:
        io.tool_warning(
            "Model setting 'remove_reasoning' is deprecated, please use 'reasoning_tag' instead."
        )
    if args.reasoning_effort is not None:
        if (
            not args.check_model_accepts_settings
            or main_model.accepts_settings
            and "reasoning_effort" in main_model.accepts_settings
        ):
            main_model.set_reasoning_effort(args.reasoning_effort)
    if args.thinking_tokens is not None:
        if (
            not args.check_model_accepts_settings
            or main_model.accepts_settings
            and "thinking_tokens" in main_model.accepts_settings
        ):
            main_model.set_thinking_tokens(args.thinking_tokens)
    if args.check_model_accepts_settings:
        settings_to_check = [
            {"arg": args.reasoning_effort, "name": "reasoning_effort"},
            {"arg": args.thinking_tokens, "name": "thinking_tokens"},
        ]
        for setting in settings_to_check:
            if setting["arg"] is not None and (
                not main_model.accepts_settings
                or setting["name"] not in main_model.accepts_settings
            ):
                io.tool_warning(
                    f"Warning: {main_model.name} does not support '{setting['name']}', ignoring."
                )
                io.tool_output(
                    f"Use --no-check-model-accepts-settings to force the '{setting['name']}'"
                    " setting."
                )
    if args.copy_paste and args.edit_format is None:
        if main_model.edit_format in ("diff", "whole", "diff-fenced"):
            main_model.edit_format = "editor-" + main_model.edit_format
    if args.verbose:
        io.tool_output("Model metadata:")
        io.tool_output(json.dumps(main_model.info, indent=4))
        io.tool_output("Model settings:")
        for attr in sorted(fields(ModelSettings), key=lambda x: x.name):
            val = getattr(main_model, attr.name)
            val = json.dumps(val, indent=4)
            io.tool_output(f"{attr.name}: {val}")
    lint_cmds = parse_lint_cmds(args.lint_cmd, io)
    if lint_cmds is None:
        return await graceful_exit(None, 1)
    repo = None
    if args.git:
        try:
            repo = GitRepo(
                io,
                fnames,
                git_dname,
                args.cecli_ignore,
                models=main_model.commit_message_models(),
                attribute_author=args.attribute_author,
                attribute_committer=args.attribute_committer,
                attribute_commit_message_author=args.attribute_commit_message_author,
                attribute_commit_message_committer=args.attribute_commit_message_committer,
                commit_prompt=args.commit_prompt,
                subtree_only=args.subtree_only,
                git_commit_verify=args.git_commit_verify,
                attribute_co_authored_by=args.attribute_co_authored_by,
            )
        except FileNotFoundError:
            pass
    if not args.skip_sanity_check_repo:
        if not await sanity_check_repo(repo, io):
            return await graceful_exit(None, 1)
    commands = Commands(
        io,
        None,
        voice_language=args.voice_language,
        voice_input_device=args.voice_input_device,
        voice_format=args.voice_format,
        verify_ssl=args.verify_ssl,
        args=args,
        parser=parser,
        verbose=args.verbose,
        editor=args.editor,
        original_read_only_fnames=read_only_fnames,
    )
    summarizer = ChatSummary(
        [main_model.weak_model, main_model],
        args.max_chat_history_tokens or main_model.max_chat_history_tokens,
    )
    if args.cache_prompts and args.map_refresh == "auto":
        args.map_refresh = "files"
    if not main_model.streaming:
        if args.stream:
            io.tool_warning(
                f"Warning: Streaming is not supported by {main_model.name}. Disabling streaming."
                " Set stream: false in config file or use --no-stream to skip this warning."
            )
        args.stream = False
    if args.map_tokens is None:
        map_tokens = main_model.get_repo_map_tokens()
    else:
        map_tokens = args.map_tokens
    if args.enable_context_compaction and (
        args.context_compaction_max_tokens is None or args.context_compaction_max_tokens < 1
    ):
        max_input_tokens = main_model.info.get("max_input_tokens")
        ratio = 0.8
        if args.context_compaction_max_tokens:
            ratio = args.context_compaction_max_tokens
        if max_input_tokens:
            args.context_compaction_max_tokens = int(max_input_tokens * ratio)
    try:
        mcp_servers = load_mcp_servers(
            args.mcp_servers, args.mcp_servers_file, io, args.verbose, args.mcp_transport
        )
        if not mcp_servers:
            mcp_servers = []
        coder = await Coder.create(
            main_model=main_model,
            edit_format=args.edit_format,
            io=io,
            args=args,
            repo=repo,
            fnames=fnames,
            read_only_fnames=read_only_fnames,
            read_only_stubs_fnames=[],
            show_diffs=args.show_diffs,
            auto_commits=args.auto_commits,
            dirty_commits=args.dirty_commits,
            dry_run=args.dry_run,
            map_tokens=map_tokens,
            verbose=args.verbose,
            stream=args.stream,
            use_git=args.git,
            restore_chat_history=args.restore_chat_history,
            auto_lint=args.auto_lint,
            auto_test=args.auto_test,
            lint_cmds=lint_cmds,
            test_cmd=args.test_cmd,
            commands=commands,
            summarizer=summarizer,
            map_refresh=args.map_refresh,
            cache_prompts=args.cache_prompts,
            map_mul_no_files=args.map_multiplier_no_files,
            map_max_line_length=args.map_max_line_length,
            num_cache_warming_pings=args.cache_keepalive_pings,
            suggest_shell_commands=args.suggest_shell_commands,
            chat_language=args.chat_language,
            commit_language=args.commit_language,
            detect_urls=args.detect_urls,
            auto_copy_context=args.copy_paste,
            auto_accept_architect=args.auto_accept_architect,
            mcp_servers=mcp_servers,
            add_gitignore_files=args.add_gitignore_files,
            enable_context_compaction=args.enable_context_compaction,
            context_compaction_max_tokens=args.context_compaction_max_tokens,
            context_compaction_summary_tokens=args.context_compaction_summary_tokens,
            map_cache_dir=args.map_cache_dir,
            repomap_in_memory=args.map_memory_cache,
            linear_output=args.linear_output,
        )
        if args.show_model_warnings:
            problem = await models.sanity_check_models(pre_init_io, main_model)
            if problem:
                pre_init_io.tool_output("You can skip this check with --no-show-model-warnings")
                try:
                    await pre_init_io.offer_url(
                        urls.model_warnings,
                        "Open documentation url for more info?",
                        acknowledge=True,
                    )
                    pre_init_io.tool_output()
                except KeyboardInterrupt:
                    return await graceful_exit(coder, 1)
        if args.git:
            git_root = await setup_git(git_root, pre_init_io)
            if args.gitignore:
                await check_gitignore(git_root, pre_init_io)
    except UnknownEditFormat as err:
        pre_init_io.tool_error(str(err))
        await pre_init_io.offer_url(
            urls.edit_formats, "Open documentation about edit formats?", acknowledge=True
        )
        return await graceful_exit(None, 1)
    except ValueError as err:
        pre_init_io.tool_error(str(err))
        return await graceful_exit(None, 1)
    if return_coder:
        return coder
    ignores = []
    if git_root:
        ignores.append(str(Path(git_root) / ".gitignore"))
    if args.cecli_ignore:
        ignores.append(args.cecli_ignore)
    if args.watch_files:
        file_watcher = FileWatcher(
            coder,
            gitignores=ignores,
            verbose=args.verbose,
            root=str(Path.cwd()) if args.subtree_only else None,
        )
        coder.file_watcher = file_watcher
    if args.copy_paste:
        ClipboardWatcher(coder.io, verbose=args.verbose)
    if args.show_prompts:
        coder.cur_messages += [dict(role="user", content="Hello!")]
        messages = coder.format_messages().all_messages()
        utils.show_messages(messages)
        return await graceful_exit(coder)
    if args.lint:
        await coder.commands.do_run("lint", "")
    if args.test:
        if not args.test_cmd:
            io.tool_error("No --test-cmd provided.")
            return await graceful_exit(coder, 1)
        await coder.commands.cmd_test(args.test_cmd)
        if io.placeholder:
            await coder.run(io.placeholder)
    if args.commit:
        if args.dry_run:
            io.tool_output("Dry run enabled, skipping commit.")
        else:
            await coder.commands.cmd_commit()
    if args.lint or args.test or args.commit:
        return await graceful_exit(coder)
    if args.show_repo_map:
        repo_map = coder.get_repo_map()
        if repo_map:
            io.tool_output(repo_map)
        return await graceful_exit(coder)
    if args.apply:
        content = io.read_text(args.apply)
        if content is None:
            return await graceful_exit(coder)
        coder.partial_response_content = content
        await coder.apply_updates()
        return await graceful_exit(coder)
    if args.apply_clipboard_edits:
        args.edit_format = main_model.editor_edit_format
        args.message = "/paste"
    if args.show_release_notes is True:
        io.tool_output(f"Opening release notes: {urls.release_notes}")
        io.tool_output()
        webbrowser.open(urls.release_notes)
    elif args.show_release_notes is None and is_first_run:
        io.tool_output()
        await io.offer_url(
            urls.release_notes,
            "Would you like to see what's new in this version?",
            allow_never=False,
            acknowledge=True,
        )
    if git_root and Path.cwd().resolve() != Path(git_root).resolve():
        io.tool_warning(
            "Note: in-chat filenames are always relative to the git working dir, not the current"
            " working dir."
        )
        io.tool_output(f"Cur working dir: {Path.cwd()}")
        io.tool_output(f"Git working dir: {git_root}")
    if args.stream and args.cache_prompts:
        io.tool_warning("Cost estimates may be inaccurate when using streaming and caching.")
    if args.load:
        await commands.cmd_load(args.load)
    if args.message:
        io.add_to_input_history(args.message)
        io.tool_output()
        try:
            await coder.run(with_message=args.message)
        except (SwitchCoder, KeyboardInterrupt, SystemExit):
            pass
        return await graceful_exit(coder)
    if args.message_file:
        try:
            message_from_file = io.read_text(args.message_file)
            io.tool_output()
            await coder.run(with_message=message_from_file)
        except (SwitchCoder, KeyboardInterrupt, SystemExit):
            pass
        except FileNotFoundError:
            io.tool_error(f"Message file not found: {args.message_file}")
            return await graceful_exit(coder, 1)
        except IOError as e:
            io.tool_error(f"Error reading message file: {e}")
            return await graceful_exit(coder, 1)
        return await graceful_exit(coder)
    if args.exit:
        return await graceful_exit(coder)
    if args.auto_load:
        try:
            from cecli.sessions import SessionManager

            session_manager = SessionManager(coder, io)
            session_manager.load_session(
                args.auto_save_session_name if args.auto_save_session_name else "auto-save"
            )
        except Exception:
            pass
    if args.tui:
        from cecli.tui import launch_tui

        del pre_init_io
        return_code = await launch_tui(coder, output_queue, input_queue, args)
        return await graceful_exit(coder, return_code)
    while True:
        try:
            coder.ok_to_warm_cache = bool(args.cache_keepalive_pings)
            await coder.run()
            return await graceful_exit(coder)
        except SwitchCoder as switch:
            coder.ok_to_warm_cache = False
            if hasattr(switch, "placeholder") and switch.placeholder is not None:
                io.placeholder = switch.placeholder
            kwargs = dict(io=io, from_coder=coder)
            kwargs.update(switch.kwargs)
            if "show_announcements" in kwargs:
                del kwargs["show_announcements"]
            kwargs["num_cache_warming_pings"] = 0
            kwargs["args"] = coder.args
            coder = await Coder.create(**kwargs)
            if switch.kwargs.get("show_announcements") is False:
                coder.suppress_announcements_for_next_prompt = True
        except SystemExit:
            sys.settrace(None)
            return await graceful_exit(coder)


def is_first_run_of_new_version(io, verbose=False):
    """Check if this is the first run of a new version/executable combination"""
    installs_file = handle_core_files(Path.home() / ".cecli" / "installs.json")
    key = __version__, sys.executable
    if ".dev" in __version__:
        return False
    if verbose:
        io.tool_output(
            f"Checking imports for version {__version__} and executable {sys.executable}"
        )
        io.tool_output(f"Installs file: {installs_file}")
    try:
        if installs_file.exists():
            with open(installs_file, "r") as f:
                installs = json.load(f)
            if verbose:
                io.tool_output("Installs file exists and loaded")
        else:
            installs = {}
            if verbose:
                io.tool_output("Installs file does not exist, creating new dictionary")
        is_first_run = str(key) not in installs
        if is_first_run:
            installs[str(key)] = True
            installs_file.parent.mkdir(parents=True, exist_ok=True)
            with open(installs_file, "w") as f:
                json.dump(installs, f, indent=4)
        return is_first_run
    except Exception as e:
        io.tool_warning(f"Error checking version: {e}")
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")
        return True


async def check_and_load_imports(io, is_first_run, verbose=False):
    try:
        if is_first_run:
            if verbose:
                io.tool_output(
                    "First run for this version and executable, loading imports synchronously"
                )
            try:
                load_slow_imports(swallow=False)
            except Exception as err:
                io.tool_error(str(err))
                io.tool_output("Error loading required imports. Did you install cecli properly?")
                await io.offer_url(
                    urls.install_properly, "Open documentation url for more info?", acknowledge=True
                )
                sys.exit(1)
            if verbose:
                io.tool_output("Imports loaded and installs file updated")
        else:
            if verbose:
                io.tool_output("Not first run, loading imports in background thread")
            thread = threading.Thread(target=load_slow_imports)
            thread.daemon = True
            thread.start()
    except Exception as e:
        io.tool_warning(f"Error in loading imports: {e}")
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")


def load_slow_imports(swallow=True):
    try:
        import httpx  # noqa
        import litellm  # noqa
        import numpy  # noqa
    except Exception as e:
        if not swallow:
            raise e


async def graceful_exit(coder=None, exit_code=0):
    sys.settrace(None)
    if coder:
        if hasattr(coder, "_autosave_future"):
            await coder._autosave_future
        for server in coder.mcp_servers:
            try:
                await server.exit_stack.aclose()
            except Exception:
                pass
    return exit_code


if __name__ == "__main__":
    status = main()
    sys.exit(status)
