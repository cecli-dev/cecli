import os
import sys

try:
    if sys.platform == "win32":
        if sys.stdout is not None:
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except AttributeError:
                pass

        if sys.stderr is not None:
            try:
                sys.stderr.reconfigure(encoding="utf-8")
            except AttributeError:
                pass

        if sys.stdin is not None:
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except AttributeError:
                pass
except AttributeError:
    # Happens if streams were overridden by a test framework or GUI (e.g., pythonw.exe)
    pass
except sys.UnsupportedOperation:
    # Happens in certain edge-case piping scenarios
    pass

try:
    if not os.getenv("CECLI_DEFAULT_TLS"):
        from truststore import inject_into_ssl

        inject_into_ssl()
except Exception as e:
    print(e)
    pass

import asyncio
import json
import re
import shutil
import time
import traceback
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
elif sys.platform == "darwin":
    # The default KqueueSelector cannot handle pipe-based stdin
    # (e.g. when running inside Emacs comint-mode). Fall back to
    # SelectSelector which works with any file descriptor that supports select().
    import selectors

    if not sys.stdin.isatty():
        _original_event_loop_policy = asyncio.DefaultEventLoopPolicy

        class _SelectSelectorPolicy(asyncio.DefaultEventLoopPolicy):
            def new_event_loop(self):
                return asyncio.SelectorEventLoop(selectors.SelectSelector())

        asyncio.set_event_loop_policy(_SelectSelectorPolicy())

from .dump import dump  # noqa


def convert_yaml_to_json_string(value, config_file_value=None):
    """
    Convert YAML dict/list values to JSON strings for compatibility.

    configargparse.YAMLConfigFileParser converts YAML to Python objects,
    but some arguments expect JSON strings. This function handles:
    - Direct dict/list objects
    - String representations of dicts/lists (JSON or Python literals)
    - Already JSON strings (passed through unchanged)

    When config_file_value is provided (the value for the same option from the
    merged config files), the CLI value is deep-merged on top of it so CLI keys
    win per-key while keys provided only by the config files (e.g.
    skills_paths, skills_init) are preserved instead of being discarded
    wholesale. configargparse discards config-file values for options that are
    also given on the command line, so without this merge a CLI --agent-config
    silently drops every agent-config key that lives only in .cecli.conf.yml.

    Args:
        value: The value to convert
        config_file_value: Optional config-file value to deep-merge underneath
            the CLI value

    Returns:
        str: JSON string if value is a dict/list, otherwise the original value
    """
    if value is None:
        return None

    parsed = value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            try:
                import ast

                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return value

    if isinstance(parsed, (dict, list)):
        if isinstance(parsed, dict) and config_file_value is not None:
            from cecli.helpers.config_utils import deep_merge

            try:
                file_value = config_file_value

                if isinstance(file_value, str):
                    file_value = json.loads(file_value)

                if isinstance(file_value, dict) and file_value:
                    parsed = deep_merge(file_value, parsed, deep_merge_arrays=False)
            except Exception:
                pass

        return json.dumps(parsed)

    return value


# yaml-to-json args: argparse dest -> config-file key (hyphenated).
# CLI values for these args deep-merge with the merged config-file value for
# the same option, so CLI keys win per-key while file-only keys are preserved.
YAML_TO_JSON_ARG_KEYS = {
    "agent_config": "agent-config",
    "tui_config": "tui-config",
    "mcp_servers": "mcp-servers",
    "custom": "custom",
    "security_config": "security-config",
    "retries": "retries",
    "hooks": "hooks",
    "workspaces": "workspaces",
    "model_providers": "model-providers",
    "server_config": "server-config",
}


def check_config_files_for_yes(config_files):
    from cecli.decoding import safe_open

    found = False
    for config_file in config_files:
        if Path(config_file).exists():
            try:
                with safe_open(config_file, "r") as f:
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
        repo = git.Repo(search_parent_directories=True, odbt=git.GitCmdObjectDB)
        return repo.working_tree_dir
    except (git.InvalidGitRepositoryError, FileNotFoundError):
        return None


def guessed_wrong_repo(io, git_root, fnames, git_dname):
    """After we parse the args, we can determine the real repo. Did we guess wrong?"""
    from cecli.repo import ANY_GIT_ERROR, GitRepo

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
    from cecli.repo import ANY_GIT_ERROR

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
    from cecli.repo import ANY_GIT_ERROR

    if git is None:
        return
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None
    repo = None
    if git_root:
        try:
            repo = git.Repo(git_root, odbt=git.GitCmdObjectDB)
        except ANY_GIT_ERROR:
            pass
    elif cwd == Path.home():
        io.tool_warning(
            "You should probably run cecli in your project's directory, not your home dir."
        )
        return
    elif cwd and await io.confirm_ask(
        "No git repo found, create one to track cecli's changes (recommended)?",
        acknowledge=True,
        explicit_yes_required=True,
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
    from cecli.repo import ANY_GIT_ERROR

    if not git_root:
        return
    try:
        repo = git.Repo(git_root, odbt=git.GitCmdObjectDB)
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
    from cecli import models
    from cecli.helpers.file_searcher import generate_search_path_list, handle_core_files

    model_settings_files = generate_search_path_list(
        handle_core_files(".cecli.model.settings.yml"), git_root, model_settings_fname
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
    from cecli.helpers.file_searcher import generate_search_path_list, handle_core_files

    dotenv_files = generate_search_path_list(".env", git_root, dotenv_fname)
    oauth_keys_file = handle_core_files(Path.home() / ".cecli" / "oauth-keys.env")
    if oauth_keys_file.exists():
        dotenv_files.insert(0, str(oauth_keys_file.resolve()))
        dotenv_files = list(dict.fromkeys(dotenv_files))

    # Also check ~/.cecli/.env as a default dotenv file (lowest priority)
    cecli_env_file = Path.home() / ".cecli" / ".env"
    if cecli_env_file.exists():
        dotenv_files.insert(0, str(cecli_env_file.resolve()))
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
    from cecli import models
    from cecli.helpers.file_searcher import generate_search_path_list, handle_core_files

    model_metadata_files = []
    resource_metadata = importlib_resources.files("cecli.resources").joinpath("model-metadata.json")
    model_metadata_files.append(str(resource_metadata))
    model_metadata_files += generate_search_path_list(
        handle_core_files(".cecli.model.metadata.json"), git_root, model_metadata_fname
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
    from cecli import models

    models.ModelOverrides.load_from_file(git_root, model_overrides_fname, io, verbose=verbose)


def load_model_overrides_from_string(model_overrides_str, io):
    """Load model tag overrides from a JSON/YAML string."""
    from cecli import models

    models.ModelOverrides.load_from_string(model_overrides_str, io)


async def sanity_check_repo(repo, io):
    from cecli import urls
    from cecli.repo import ANY_GIT_ERROR

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


def interpolate_env_vars(value):
    """Interpolate environment variables in the form ${VAR} or $VAR."""
    if not isinstance(value, str):
        return value

    def replace_var(match):
        var_name = match.group(1) or match.group(2)
        return os.getenv(var_name, match.group(0))

    # Matches ${VAR} or $VAR
    pattern = r"\$\{([\w_]+)\}|\$([\w_]+)"
    return re.sub(pattern, replace_var, value)


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
    from cecli.signals import ReloadProgramSignal

    # Tracks the coder instance from a ReloadProgramSignal so the new
    # main_async() can pass it as from_coder to Coder.create(), preserving
    # UUID, edit_format, and other state across the reload cycle.
    reload_from_coder = None

    while True:
        try:
            if sys.platform == "win32":
                if sys.version_info >= (3, 12) and hasattr(asyncio, "SelectorEventLoop"):
                    return asyncio.run(
                        main_async(
                            argv,
                            input,
                            output,
                            force_git_root,
                            return_coder,
                            from_coder=reload_from_coder,
                        ),
                        loop_factory=asyncio.SelectorEventLoop,
                    )
            return asyncio.run(
                main_async(
                    argv,
                    input,
                    output,
                    force_git_root,
                    return_coder,
                    from_coder=reload_from_coder,
                )
            )
        except ReloadProgramSignal as sig:
            reload_from_coder = sig.kwargs.get("from_coder")
            # Clear hook registries to prevent 'already exists' warnings on reload.
            # The old HookManager and HookRegistry instances are cached by UUID and
            # would be reused by the new coder, causing hook registration failures.
            if reload_from_coder:
                from cecli.hooks import HookService

                HookService.destroy_instances(reload_from_coder.uuid)
            continue


async def main_async(
    argv=None,
    input=None,
    output=None,
    force_git_root=None,
    return_coder=False,
    from_coder=None,
):
    import logging

    import yaml

    from cecli import models, urls, utils
    from cecli.args import DEEP_MERGE_JSON_FIELDS, DEEP_MERGE_LIST_FIELDS, get_parser
    from cecli.coders import Coder
    from cecli.coders.base_coder import UnknownEditFormat
    from cecli.commands import Commands, ReloadProgramSignal, SwitchCoderSignal
    from cecli.decoding import DEFAULT_ENCODING, safe_open  # noqa
    from cecli.deprecated_args import handle_deprecated_model_args
    from cecli.format_settings import format_settings, scrub_sensitive_info
    from cecli.helpers import config_utils
    from cecli.helpers.conversation import ConversationService, MessageTag
    from cecli.helpers.copypaste import ClipboardWatcher
    from cecli.helpers.file_searcher import handle_core_files
    from cecli.history import ChatSummary
    from cecli.hooks import HookService
    from cecli.io import InputOutput
    from cecli.mcp import McpServerManager, load_mcp_servers
    from cecli.models import ModelSettings
    from cecli.onboarding import offer_openrouter_oauth, select_default_model
    from cecli.repo import GitRepoProxy
    from cecli.report import report_uncaught_exceptions, set_args_error_data
    from cecli.versioncheck import check_version
    from cecli.watch import FileWatcher

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
    # Split config files into two groups:
    #   - conf_yml_files:  .cecli/conf.yml  (shallow merge via configargparse)
    #   - cecli_conf_yml_files: .cecli.conf.yml (deep merge handled by us)
    # configargparse must NOT see .cecli.conf.yml files because it would
    # shallow-merge (overwrite) them, destroying values from earlier files
    # before our deep-merge code can run.
    all_config_paths = [
        str(Path.home() / ".cecli" / "conf.yml"),
        str(Path.home() / ".cecli.conf.yml"),
        str(Path(".cecli.conf.yml")),
    ]
    if git_root:
        all_config_paths.append(str(Path(git_root) / ".cecli.conf.yml"))

    conf_yml_files = [
        p for p in all_config_paths if p.endswith("conf.yml") and not p.endswith(".cecli.conf.yml")
    ]
    cecli_conf_yml_files = [p for p in all_config_paths if p.endswith(".cecli.conf.yml")]

    # ── Read and merge ALL config files as YAML upfront ─────────────────
    # Decode all files as YAML, shallow-merge .cecli/conf.yml, then
    # deep-merge .cecli.conf.yml on top for a fully resolved config dict.
    merged_config = config_utils.read_and_merge_all_configs(
        all_config_paths, conf_yml_files, cecli_conf_yml_files
    )

    # Write merged config to a temp YAML file so configargparse can
    # consume it as a single, already-merged config source. CLI args
    # parsed on top will correctly override config-file values.
    import tempfile

    _tmp_fd, _tmp_cfg = tempfile.mkstemp(suffix=".yml", prefix="cecli_merged_")
    os.close(_tmp_fd)

    with safe_open(_tmp_cfg, "w") as f:
        yaml.dump(merged_config, f)

    parser = get_parser([_tmp_cfg], git_root)
    args, unknown = parser.parse_known_args(argv)

    # ── Load dotenv files ──────────────────────────────────────────────
    # env_file is now fully resolved from the merged config (including
    # values from .cecli.conf.yml which were previously ignored).
    loaded_dotenvs = load_dotenv_files(git_root, args.env_file, args.encoding)
    args, unknown = parser.parse_known_args(argv)
    os.unlink(_tmp_cfg)

    if args.workspaces or args.workspace_name:
        from cecli.helpers.workspaces.config import (
            find_active_workspace_name,
            load_workspace_config,
            workspace_layout,
        )
        from cecli.helpers.workspaces.subagents import register_workspace_subagents
        from cecli.helpers.workspaces.workspace import WorkspaceManager

        # Interpolate environment variables in the workspaces argument
        if args.workspaces:
            args.workspaces = interpolate_env_vars(args.workspaces)

        ws_config_arg = convert_yaml_to_json_string(args.workspaces) if args.workspaces else None
        ws_name = args.workspace_name or find_active_workspace_name(ws_config_arg)
        if ws_name:
            config = load_workspace_config(ws_config_arg, name=ws_name)

            # Clone workspaces must be materialised so the implicit ws:{name}
            # sub-agents can point their roots at the cloned checkouts. The
            # primary agent's root is left unchanged: workspaces are just
            # sub-agents with overridden roots.
            if workspace_layout(config) == "clone":
                wm = WorkspaceManager(ws_name, config)
                if not wm.exists():
                    wm.initialize()

            register_workspace_subagents(config)

    if git_root:
        git_conf = Path(git_root) / conf_fname
        if git_conf not in all_config_paths:
            all_config_paths.append(str(git_conf))
            cecli_conf_yml_files.append(str(git_conf))

    set_args_error_data(args)

    # Override the module-level default encoding with the resolved config value
    DEFAULT_ENCODING = args.encoding  # noqa

    # ── Normalize array fields ─────────────────────────────────────────
    # (previously done inside load_and_apply_cecli_conf_files)
    for key in DEEP_MERGE_LIST_FIELDS:
        if hasattr(args, key):
            val = getattr(args, key)

            if val is None or (isinstance(val, str) and val.strip() == ""):
                setattr(args, key, [])

            elif isinstance(val, str):
                setattr(args, key, [val])

            elif not isinstance(val, list):
                logging.warning(
                    "args.%s is not a list (type: %s), coercing to empty list",
                    key,
                    type(val).__name__,
                )
                setattr(args, key, [])

    for key in DEEP_MERGE_JSON_FIELDS:
        if hasattr(args, key):
            val = getattr(args, key)

            if val is None or (isinstance(val, str) and val.strip() == ""):
                setattr(args, key, "{}")

    if len(unknown):
        print("Unknown Args: ", unknown)

    # ── Convert yaml-to-json arguments, deep-merging CLI values with ──────
    # the merged config-file values so CLI keys win per-key while file-only
    # keys are preserved.
    for arg_name, config_key in YAML_TO_JSON_ARG_KEYS.items():
        if hasattr(args, arg_name) and getattr(args, arg_name) is not None:
            config_file_value = merged_config.get(config_key)

            setattr(
                args,
                arg_name,
                convert_yaml_to_json_string(getattr(args, arg_name), config_file_value),
            )

    # Interpolate environment variables in all string arguments
    for key, value in vars(args).items():
        if isinstance(value, str):
            setattr(args, key, interpolate_env_vars(value))
        elif isinstance(value, list):
            setattr(
                args, key, [interpolate_env_vars(v) if isinstance(v, str) else v for v in value]
            )

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
        from cecli.helpers.llms import set_verify_ssl

        set_verify_ssl(False)
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
    editing_mode = "VI" if args.vim else "EMACS"

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
            notification_bell=args.notification_bell,
            verbose=args.verbose,
            show_spinner=args.spinner,
        )

    validate_tui_args(args)
    output_queue = None
    input_queue = None
    pre_init_io = get_io(args.pretty)
    # Check if we're in "send message and exit" mode to skip non-essential initialization
    suppress_pre_init = (
        args.message or args.message_file or args.apply_clipboard_edits or args.terminal_setup
    )
    supress_tui = True

    if not suppress_pre_init:
        if args.tui or (args.tui is None and not args.linear_output):
            try:
                from cecli.tui import create_tui_io

                args.tui = True
                args.linear_output = True
                io, output_queue, input_queue = create_tui_io(args, editing_mode)
                supress_tui = False
            except ImportError as e:
                print("Error: --tui requires 'textual' package")
                print("Install with: pip install cecli-dev[tui]")
                print(f"Import error: {e}")
                sys.exit(1)

    if supress_tui:
        io = pre_init_io
        if args.linear_output is None:
            args.linear_output = True

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

    # Check for arguments starting with '--' that are likely
    # unrecognized or misspelled parameters, not file arguments
    filtered_files = []
    for f in all_files:
        if f.startswith("--"):
            # Extract the parameter name: everything between '--' and '=' or end
            param = f[2:].split("=")[0].split()[0]
            io.tool_warning(f"The parameter --{param} does not exist.")
        else:
            filtered_files.append(f)

    all_files = filtered_files
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
    rules_patterns = args.rules or []
    rules_expanded = utils.expand_glob_patterns(rules_patterns)
    rules_fnames = []
    for fn in rules_expanded:
        path = Path(fn).expanduser().resolve()
        if path.is_dir():
            rules_fnames.extend(str(f) for f in path.rglob("*") if f.is_file())
        else:
            rules_fnames.append(str(path))
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
    if args.git and not force_git_root and git is not None and not suppress_pre_init:
        right_repo_root = guessed_wrong_repo(pre_init_io, git_root, fnames, git_dname)
        if right_repo_root:
            return await main_async(argv, input, output, right_repo_root, return_coder=return_coder)

    if (args.check_update or args.upgrade) and not args.just_check_update and not suppress_pre_init:
        await check_version(pre_init_io, verbose=args.verbose, upgrade=args.upgrade)
    elif args.just_check_update:
        update_available = await check_version(pre_init_io, just_check=True, verbose=args.verbose)
        return await graceful_exit(None, 0 if not update_available else 1)
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

    # Release transient garbage from the (heavy) model/litellm imports now that
    # registration is done, so import-time bloat doesn't carry into the session.
    from cecli.helpers.memory_control import trim_memory

    trim_memory()
    if args.model_providers:
        try:
            user_providers = json.loads(args.model_providers)
            if isinstance(user_providers, dict):
                models.model_info_manager.provider_manager.merge_provider_configs(user_providers)
                if args.verbose:
                    io.tool_output(f"Loaded {len(user_providers)} custom model provider(s):")
                    for slug in user_providers:
                        io.tool_output(f"  - {slug}")
        except json.JSONDecodeError as e:
            io.tool_error(f"Failed to parse --model-providers JSON: {e}")

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
    selected_model_name = await select_default_model(args, pre_init_io)
    if not selected_model_name:
        return await graceful_exit(None, 1)
    args.model = selected_model_name

    # Load model tag overrides (stored in ModelOverrides class-level state)
    if args.model_overrides_file:
        models.ModelOverrides.load_from_file(
            git_root, args.model_overrides_file, io, verbose=args.verbose
        )

    if args.model_overrides:
        models.ModelOverrides.load_from_string(args.model_overrides, io)

    weak_model_obj = None
    if args.weak_model:
        weak_model_obj = models.Model(
            args.weak_model,
            weak_model=False,
            verbose=args.verbose,
            io=io,
            retries=args.retries,
            debug=args.debug,
        )

    editor_model_obj = None
    if args.editor_model:
        editor_model_obj = models.Model(
            args.editor_model,
            editor_model=False,
            verbose=args.verbose,
            io=io,
            retries=args.retries,
            debug=args.debug,
        )

    agent_model_obj = None
    if args.agent_model:
        agent_model_obj = models.Model(
            args.agent_model,
            agent_model=False,
            verbose=args.verbose,
            io=io,
            retries=args.retries,
            debug=args.debug,
        )

    if args.model.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
        io.tool_warning(
            f"The specified model '{args.model}' requires an OpenRouter API key, which was not"
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
                f"Unable to proceed without an OpenRouter API key for model '{args.model}'."
            )
            await io.offer_url(
                urls.models_and_keys, "Open documentation URL for more info?", acknowledge=True
            )
            return await graceful_exit(None, 1)

    main_model = models.Model(
        args.model,
        weak_model=weak_model_obj,
        editor_model=editor_model_obj,
        agent_model=agent_model_obj,
        editor_edit_format=args.editor_edit_format,
        verbose=args.verbose,
        io=io,
        retries=args.retries,
        debug=args.debug,
    )

    if args.copy_paste and main_model.copy_paste_transport == "api":
        main_model.enable_copy_paste_mode()
    if main_model.remove_reasoning is not None:
        io.tool_warning(
            "Model setting 'remove_reasoning' is deprecated, please use 'reasoning_tag' instead."
        )
    if args.reasoning_effort is not None:
        main_model.set_reasoning_effort(args.reasoning_effort)
        if agent_model_obj:
            agent_model_obj.set_reasoning_effort(args.reasoning_effort)
        if weak_model_obj:
            weak_model_obj.set_reasoning_effort(args.reasoning_effort)
        if editor_model_obj:
            editor_model_obj.set_reasoning_effort(args.reasoning_effort)
    if args.thinking_tokens is not None:
        main_model.set_thinking_tokens(args.thinking_tokens)
        if agent_model_obj:
            agent_model_obj.set_thinking_tokens(args.thinking_tokens)
        if weak_model_obj:
            weak_model_obj.set_thinking_tokens(args.thinking_tokens)
        if editor_model_obj:
            editor_model_obj.set_thinking_tokens(args.thinking_tokens)
    if args.copy_paste and args.edit_format is None:
        if main_model.edit_format in ("diff", "whole", "diff-fenced"):
            main_model.edit_format = "editor-" + main_model.edit_format
    if args.verbose:
        from dataclasses import fields

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
            repo = GitRepoProxy.for_root(
                None,
                io,
                fnames=fnames,
                git_dname=git_dname,
                cecli_ignore_file=args.cecli_ignore,
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
    if not args.skip_sanity_check_repo and not suppress_pre_init:
        if not await sanity_check_repo(repo, pre_init_io):
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
        else:
            # Default since some models do not have max_input_tokens specified somehow
            args.context_compaction_max_tokens = 65536
    try:
        if getattr(args, "mcp_servers_file_deprecated", None):
            io.tool_warning(
                "The --mcp-servers-file argument is deprecated and will be removed in a future"
                " version. Please use --mcp-servers-files instead."
            )
            if not args.mcp_servers_files:
                args.mcp_servers_files = []
            args.mcp_servers_files.extend(args.mcp_servers_file_deprecated)

        mcp_servers = load_mcp_servers(
            args.mcp_servers, args.mcp_servers_files, io, args.verbose, args.mcp_transport
        )
        # Create the manager without connecting. Connections are established
        # later on the coder's event loop (connect_all below for CLI mode, or
        # CoderWorker._async_run for TUI mode) so loop-bound MCP state stays
        # on the loop the coder actually runs on.
        mcp_manager = McpServerManager(mcp_servers, io=io, verbose=args.verbose)

        if from_coder:
            from_coder.tui = None
            from_coder.io = None

        coder = await Coder.create(
            from_coder=from_coder,
            main_model=main_model,
            edit_format=args.edit_format,
            io=io,
            args=args,
            repo=repo,
            fnames=fnames,
            read_only_fnames=read_only_fnames,
            read_only_stubs_fnames=[],
            rules_fnames=rules_fnames,
            show_diffs=args.show_diffs,
            auto_commits=args.auto_commits,
            dirty_commits=args.dirty_commits,
            dry_run=args.dry_run,
            map_tokens=map_tokens,
            verbose=args.verbose,
            stream=args.stream,
            use_git=args.git,
            auto_lint=args.auto_lint,
            auto_test=args.auto_test,
            auto_memory=args.auto_memory,
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
            mcp_manager=mcp_manager,
            add_gitignore_files=args.add_gitignore_files,
            enable_context_compaction=args.enable_context_compaction,
            context_compaction_max_tokens=args.context_compaction_max_tokens,
            context_compaction_summary_tokens=args.context_compaction_summary_tokens,
            map_cache_dir=args.map_cache_dir,
            repomap_in_memory=args.map_memory_cache,
            linear_output=args.linear_output,
            security_config=args.security_config,
        )

        # Load hooks if specified (after coder creation so they register
        # on the primary agent's per-coder HookManager)
        if args.hooks:
            hook_registry = HookService.get_registry(coder)
            loaded_hooks = hook_registry.load_hooks_from_json(args.hooks)

            if args.verbose and loaded_hooks:
                io.tool_output(
                    f"Loaded {len(loaded_hooks)} hooks from --hooks config:"
                    f" {', '.join(loaded_hooks)}"
                )

        # Connect MCP servers on the coder's event loop so loop-bound MCP
        # state (sessions, locks, keepalive tasks) is created where the coder
        # runs. In TUI mode the coder runs on the worker thread's loop and
        # CoderWorker connects there; connecting here on the main loop would
        # migrate the connections across loops on first use.
        if not args.tui:
            await mcp_manager.connect_all()

        if args.show_model_warnings and not suppress_pre_init:
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
        if args.git and not (suppress_pre_init or args.workspaces or args.workspace_name):
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

    # The coder owns the MCP manager so graceful_exit can disconnect servers.
    # If the coder never adopted it (e.g. mocked coders in tests), keep the
    # reference so disconnect_all() still runs and MCP client tasks don't
    # leak into asyncio.run() shutdown (which hangs with mcp 2.x stdio tasks).
    coder.mcp_manager = mcp_manager

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
        messages = coder.format_messages()
        utils.show_messages(messages)
        return await graceful_exit(coder)
    if args.lint:
        await coder.commands.execute("lint", "")
    if args.test:
        if not args.test_cmd:
            io.tool_error("No --test-cmd provided.")
            return await graceful_exit(coder, 1)
        await coder.commands.execute("test", args.test_cmd)
        if io.placeholder:
            await coder.run(io.placeholder)
    if args.commit:
        if args.dry_run:
            io.tool_output("Dry run enabled, skipping commit.")
        else:
            await coder.commands.execute("commit", "")
    if args.terminal_setup:
        if args.dry_run:
            await coder.commands.execute("terminal-setup", "dry_run")
        else:
            await coder.commands.execute("terminal-setup", "")
        return await graceful_exit(coder)

    if args.lint or args.test or args.commit:
        return await graceful_exit(coder)
    if args.show_repo_map:
        repo_map = coder.get_repo_map()
        if repo_map:
            repo_string = ConversationService.get_chunks(coder).get_repo_map_string(repo_map)
            pre_init_io.tool_output(repo_string)
        return await graceful_exit(coder)
    if args.apply:
        content = pre_init_io.read_text(args.apply)
        if content is None:
            return await graceful_exit(coder)
        coder.partial_response_content = content
        await coder.apply_updates()
        return await graceful_exit(coder)
    if args.apply_clipboard_edits:
        args.edit_format = main_model.editor_edit_format
        args.message = "/paste"
    if args.show_release_notes is True:
        import webbrowser

        pre_init_io.tool_output(f"Opening release notes: {urls.release_notes}")
        pre_init_io.tool_output()
        webbrowser.open(urls.release_notes)
        return await graceful_exit(coder)
    elif args.show_release_notes is None and is_first_run and not args.yes_always:
        # Suppress the first-run release-notes prompt when --yes-always is set,
        # so automated/headless runs don't have the browser hijacked by an
        # auto-confirmed offer_url. Explicit --show-release-notes still opens.
        pre_init_io.tool_output()
        await pre_init_io.offer_url(
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
    if args.stream and args.cache_prompts and args.verbose:
        io.tool_warning("Cost estimates may be inaccurate when using streaming and caching.")
    if args.load:
        await commands.execute("load", args.load)
    if args.message:
        io.add_to_input_history(args.message)
        io.tool_output()
        try:
            await coder.run(with_message=args.message)
        except (SwitchCoderSignal, KeyboardInterrupt, SystemExit):
            pass
        return await graceful_exit(coder)
    if args.message_file:
        try:
            message_from_file = io.read_text(args.message_file)
            io.tool_output()
            await coder.run(with_message=message_from_file)
        except (SwitchCoderSignal, KeyboardInterrupt, SystemExit):
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
        if await pre_init_io.confirm_ask(
            "Do you want to load your previous session?",
            acknowledge=True,
            explicit_yes_required=True,
        ):
            try:
                from cecli.sessions import SessionManager

                session_manager = SessionManager(coder, io)
                await session_manager.load_session(
                    args.auto_save_session_name if args.auto_save_session_name else "auto-save",
                    switch=False,
                )
            except Exception:
                pass

    if suppress_pre_init:
        await graceful_exit(coder)

    # ── WebSocket server ────────────────────────────────────────────
    # The WebSocket server only starts if --server-config is explicitly provided.
    ws_bridge = None
    if hasattr(args, "server_config") and args.server_config:
        _server_cfg = {}
        try:
            parsed = json.loads(args.server_config)
            if isinstance(parsed, dict):
                _server_cfg = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        ws_port = _server_cfg.get("port", 23254)
        ws_host = _server_cfg.get("host", "127.0.0.1")
        headless = _server_cfg.get("headless", False)

        # Set args.headless for TUI / other consumers
        args.headless = headless

        if ws_port and ws_port > 0:
            try:
                from cecli.helpers.server.ws_server import run_ws_server

                ws_bridge = await run_ws_server(port=ws_port, host=ws_host)
                if args.verbose:
                    io.tool_output(f"WebSocket server started on ws://{ws_host}:{ws_bridge.port}")
            except Exception as e:
                io.tool_warning(f"Failed to start WebSocket server: {e}")
    else:
        args.headless = False

    if args.tui:
        from cecli.tui import launch_tui

        del pre_init_io
        try:
            return_code = await launch_tui(coder, output_queue, input_queue, args)
        except ReloadProgramSignal:
            # Clean up before full program reload (mirrors while True loop below)
            sys.settrace(None)
            await coder.auto_save_session(force=True)
            if coder.mcp_manager and coder.mcp_manager.is_connected:
                await coder.mcp_manager.disconnect_all()

            # Clean up stale TUI per-coder queues from previous sessions
            # to prevent stale queue entries from accumulating across
            # reload cycles.
            from cecli.helpers import queues

            queues._per_coder_queues.clear()

            raise
        # Stop WebSocket server
        if ws_bridge is not None:
            try:
                await ws_bridge.stop()
            except Exception:
                pass
        return await graceful_exit(coder, return_code)
    while True:
        try:
            coder.ok_to_warm_cache = bool(args.cache_keepalive_pings)
            await coder.run()
            return await graceful_exit(coder)
        except SwitchCoderSignal as switch:
            coder.ok_to_warm_cache = False
            await coder.auto_save_session(force=True)

            if hasattr(switch, "placeholder") and switch.placeholder is not None:
                io.placeholder = switch.placeholder
            kwargs = dict(io=io, from_coder=coder)
            kwargs.update(switch.kwargs)

            if "show_announcements" in kwargs:
                del kwargs["show_announcements"]
            kwargs["num_cache_warming_pings"] = 0
            kwargs["args"] = coder.args

            for tag in [MessageTag.SYSTEM, MessageTag.EXAMPLES, MessageTag.STATIC]:
                ConversationService.get_manager(coder).clear_tag(tag)

            old_coder = coder
            coder = await Coder.create(**kwargs)

            if old_coder.edit_format in ("agent", "subagent") and coder.edit_format not in (
                "agent",
                "subagent",
            ):
                if coder.mcp_manager and coder.mcp_manager.get_server("Local"):
                    await coder.mcp_manager.disconnect_server("Local")

            if switch.kwargs.get("show_announcements") is False:
                coder.suppress_announcements_for_next_prompt = True

        except KeyboardInterrupt:
            coder.keyboard_interrupt()
            continue
        except SystemExit:
            sys.settrace(None)
            await coder.auto_save_session(force=True)
            return await graceful_exit(coder)
        except ReloadProgramSignal:
            # Clean up before full program reload
            sys.settrace(None)
            await coder.auto_save_session(force=True)
            if coder.mcp_manager and coder.mcp_manager.is_connected:
                await coder.mcp_manager.disconnect_all()
            raise


def is_first_run_of_new_version(io, verbose=False):
    """Check if this is the first run of a new version/executable combination"""
    from cecli import __version__
    from cecli.decoding import safe_open
    from cecli.helpers.file_searcher import handle_core_files

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
            with safe_open(installs_file, "r") as f:
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
            with safe_open(installs_file, "w") as f:
                json.dump(installs, f, indent=4)
        return is_first_run
    except Exception as e:
        io.tool_warning(f"Error checking version: {e}")
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")
        return True


async def check_and_load_imports(io, is_first_run, verbose=False):
    from cecli import urls

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
            import threading

            thread = threading.Thread(target=load_slow_imports)
            thread.daemon = True
            thread.start()
    except Exception as e:
        io.tool_warning(f"Error in loading imports: {e}")
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")


def load_slow_imports(swallow=True):
    try:
        import cecli.llm  # noqa
    except Exception as e:
        if not swallow:
            raise e


async def task(message, setting=None, env=None, force_git_root=None, return_coder=True):
    """
    Programmatically run cecli with a message and optional settings.

    Args:
        message: The message/command to send to cecli (e.g., "Add a function to process data")
        setting: Optional YAML string of settings to override configuration
        env: Optional dict of environment variables to set
        force_git_root: Optional path to force as git root
        return_coder: Whether to return the coder object (default: True)

    Returns:
        The coder object if return_coder=True, otherwise exit code
    """
    import json
    import os
    import tempfile

    import yaml

    # Set environment variables if provided
    if env:
        for key, value in env.items():
            os.environ[key] = str(value)

    # Build argv with message as --message flag
    argv = ["--message", message]

    # Handle settings via temporary config file
    if setting:
        # Parse YAML to validate
        settings_dict = yaml.safe_load(setting)

        # Add yes-always: True to ensure automatic confirmation
        settings_dict["pretty"] = False
        settings_dict["tui"] = False
        settings_dict["yes-always"] = True

        # Add agent-config with skip_cli_confirmations: true as JSON string
        # Merge with existing agent-config if present
        agent_config = {"skip_cli_confirmations": True}
        if "agent-config" in settings_dict:
            try:
                existing_config = json.loads(settings_dict["agent-config"])
                agent_config.update(existing_config)
            except (json.JSONDecodeError, TypeError):
                # If existing agent-config is not valid JSON, overwrite it
                pass
        settings_dict["agent-config"] = json.dumps(agent_config)

        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(settings_dict, f)
            config_file = f.name

        # Add config file argument
        argv = ["--config", config_file] + argv
    else:
        config_file = None

    try:
        # Run main_async with constructed arguments
        result = await main_async(
            argv=argv, force_git_root=force_git_root, return_coder=return_coder
        )
        return result
    finally:
        # Clean up temporary config file
        if config_file and os.path.exists(config_file):
            os.unlink(config_file)


async def graceful_exit(coder=None, exit_code=0):
    sys.settrace(None)

    if getattr(coder, "error_code", None) is not None:
        exit_code = coder.error_code

    if coder:
        if hasattr(coder, "_autosave_future"):
            await coder._autosave_future

        if coder.mcp_manager and coder.mcp_manager.is_connected:
            await coder.mcp_manager.disconnect_all()
    # Cleanup old agent directories
    try:
        git_root = get_git_root()
        if git_root:
            agents_dir = Path(git_root) / ".cecli" / "agents"
        else:
            agents_dir = Path(".cecli") / "agents"

        if agents_dir.exists():
            now = time.time()
            week_seconds = 7 * 24 * 60 * 60

            for agent_folder in agents_dir.iterdir():
                if agent_folder.is_dir():
                    try:
                        mtime = agent_folder.stat().st_mtime
                        if (now - mtime) > week_seconds:
                            shutil.rmtree(agent_folder, ignore_errors=True)
                        else:
                            # Find all nested subdirectories inside this agent folder
                            all_subdirs = [d for d in agent_folder.rglob("*") if d.is_dir()]

                            # Sort them by depth (deepest first) so child dirs are processed before parents
                            all_subdirs.sort(key=lambda x: len(x.parts), reverse=True)

                            for sub_folder in all_subdirs:
                                try:
                                    # rmdir() safely fails if a file is present
                                    # any() checks if the directory has any files or remaining folders
                                    if not any(sub_folder.iterdir()):
                                        sub_folder.rmdir()
                                except OSError:
                                    pass

                    except (OSError, PermissionError):
                        pass
    except Exception:
        pass

    return exit_code


if __name__ == "__main__":
    status = main()
    sys.exit(status)
