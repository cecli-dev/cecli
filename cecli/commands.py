import asyncio
import re
import sys
from pathlib import Path

from cecli.helpers.file_searcher import handle_core_files
from cecli.repo import ANY_GIT_ERROR

from .commands.utils.registry import CommandRegistry


class SwitchCoder(Exception):
    def __init__(self, placeholder=None, **kwargs):
        self.kwargs = kwargs
        self.placeholder = placeholder


class Commands:
    scraper = None

    def clone(self):
        return Commands(
            self.io,
            None,
            voice_language=self.voice_language,
            voice_input_device=self.voice_input_device,
            voice_format=self.voice_format,
            verify_ssl=self.verify_ssl,
            args=self.args,
            parser=self.parser,
            verbose=self.verbose,
            editor=self.editor,
            original_read_only_fnames=self.original_read_only_fnames,
        )

    def __init__(
        self,
        io,
        coder,
        voice_language=None,
        voice_input_device=None,
        voice_format=None,
        verify_ssl=True,
        args=None,
        parser=None,
        verbose=False,
        editor=None,
        original_read_only_fnames=None,
    ):
        self.io = io
        self.coder = coder
        self.parser = parser
        self.args = args
        self.verbose = verbose
        self.verify_ssl = verify_ssl
        if voice_language == "auto":
            voice_language = None
        self.voice_language = voice_language
        self.voice_format = voice_format
        self.voice_input_device = voice_input_device
        self.help = None
        self.editor = editor
        self.original_read_only_fnames = set(original_read_only_fnames or [])
        self.cmd_running_event = asyncio.Event()
        self.cmd_running_event.set()

    def is_command(self, inp):
        return inp[0] in "/!"

    def is_run_command(self, inp):
        return inp and (
            inp[0] in "!" or inp[:5] == "/lint" or inp[:5] == "/test" or inp[:4] == "/run"
        )

    def is_test_command(self, inp):
        return inp and (inp[:5] == "/lint" or inp[:5] == "/test")

    def get_raw_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]
        cmd = cmd.replace("-", "_")
        raw_completer = getattr(self, f"completions_raw_{cmd}", None)
        return raw_completer

    def get_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]
        command_class = CommandRegistry.get_command(cmd)
        if command_class:
            return command_class.get_completions(self.io, self.coder, "")
        return []

    def get_commands(self):
        registry_commands = CommandRegistry.list_commands()
        commands = [f"/{cmd}" for cmd in registry_commands]
        return sorted(commands)

    async def do_run(self, cmd_name, args, **kwargs):
        command_class = CommandRegistry.get_command(cmd_name)
        if not command_class:
            self.io.tool_output(f"Error: Command {cmd_name} not found.")
            return
        self.cmd_running_event.clear()
        try:
            kwargs.update(
                {
                    "original_read_only_fnames": self.original_read_only_fnames,
                    "voice_language": self.voice_language,
                    "voice_format": self.voice_format,
                    "voice_input_device": self.voice_input_device,
                    "verify_ssl": self.verify_ssl,
                    "parser": self.parser,
                    "verbose": self.verbose,
                    "editor": self.editor,
                    "system_args": self.args,
                }
            )
            return await CommandRegistry.execute(cmd_name, self.io, self.coder, args, **kwargs)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete {cmd_name}: {err}")
            return
        except SwitchCoder as e:
            raise e
        except Exception as e:
            self.io.tool_error(f"Error executing command {cmd_name}: {str(e)}")
            return
        finally:
            self.cmd_running_event.set()
            if self.coder.tui and self.coder.tui():
                self.coder.tui().refresh()

    def matching_commands(self, inp):
        words = inp.strip().split()
        if not words:
            return
        first_word = words[0]
        rest_inp = inp[len(words[0]) :].strip()
        all_commands = self.get_commands()
        matching_commands = [cmd for cmd in all_commands if cmd.startswith(first_word)]
        return matching_commands, first_word, rest_inp

    async def run(self, inp):
        if inp.startswith("!"):
            return await self.do_run("run", inp[1:])
        res = self.matching_commands(inp)
        if res is None:
            return
        matching_commands, first_word, rest_inp = res
        if len(matching_commands) == 1:
            command = matching_commands[0][1:]
            return await self.do_run(command, rest_inp)
        elif first_word in matching_commands:
            command = first_word[1:]
            return await self.do_run(command, rest_inp)
        elif len(matching_commands) > 1:
            self.io.tool_error(f"Ambiguous command: {', '.join(matching_commands)}")
        else:
            self.io.tool_error(f"Invalid command: {first_word}")

    def get_help_md(self):
        """Show help about all commands in markdown"""
        res = "\n|Command|Description|\n|:------|:----------|\n"
        commands = sorted(self.get_commands())
        for cmd in commands:
            cmd_name = cmd[1:]
            command_class = CommandRegistry.get_command(cmd_name)
            if command_class:
                description = command_class.DESCRIPTION
                res += f"| **{cmd}** | {description} |\n"
            else:
                res += f"| **{cmd}** | |\n"
        res += "\n"
        return res

    def _get_session_directory(self):
        """Get the session storage directory, creating it if needed"""
        session_dir = handle_core_files(Path(self.coder.root) / ".cecli" / "sessions")
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _get_session_file_path(self, session_name):
        """Get the full path for a session file"""
        session_dir = self._get_session_directory()
        safe_name = re.sub("[^a-zA-Z0-9_.-]", "_", session_name)
        ext = "" if safe_name[-5:] == ".json" else ".json"
        return session_dir / f"{safe_name}{ext}"


def parse_quoted_filenames(args):
    filenames = re.findall('\\"(.+?)\\"|(\\S+)', args)
    filenames = [name for sublist in filenames for name in sublist if name]
    return filenames


def get_help_md():
    md = Commands(None, None).get_help_md()
    return md


def main():
    md = get_help_md()
    print(md)


if __name__ == "__main__":
    status = main()
    sys.exit(status)
