import json
import os
import platform
import shutil
from pathlib import Path
from typing import List

try:
    import tomllib as toml
except ImportError:
    import tomli as toml

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class TerminalSetupCommand(BaseCommand):
    NORM_NAME = "terminal-setup"
    DESCRIPTION = "Configure terminal config files to support shift+enter for newline"

    KITTY_BINDING = "\n# Added by cecli terminal-setup command\nmap shift+enter send_text all \\n\n"

    WT_ACTION = {
        "command": {"action": "sendInput", "input": "\n"},
        "id": "User.sendInput.shift_enter",
    }

    WT_KEYBINDING = {"id": "User.sendInput.shift_enter", "keys": "shift+enter"}

    VSCODE_SHIFT_ENTER_BINDING = {
        "key": "shift+enter",
        "command": "workbench.action.terminal.sendSequence",
        "when": "terminalFocus",
        "args": {"text": "\u001b[106;5u"},
    }

    # VS Code settings to configure for proper shift+enter support
    VSCODE_TERMINAL_SETTINGS = {
        "terminal.integrated.detectLocale": "off",
        "terminal.integrated.commandsToSkipShell": ["workbench.action.terminal.sendSequence"],
    }

    @staticmethod
    def _strip_json_comments(content: str) -> str:
        """Remove single-line JSON comments (// ...) from a string to allow parsing
        VS Code style JSON files that may contain comments."""
        # Remove single-line comments (// ...)
        import re

        return re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)

    @classmethod
    def _get_config_paths(cls):
        """Determine paths based on the current OS."""
        system = platform.system()
        home = Path.home()
        paths = {}

        # Check for WSL specifically
        is_wsl_env = "microsoft" in platform.uname().release.lower() and os.environ.get(
            "WSL_DISTRO_NAME"
        )

        if system == "Linux":
            # Standard Linux paths (applies to WSL instances of Kitty/Alacritty too)
            paths["alacritty"] = home / ".config" / "alacritty" / "alacritty.toml"
            paths["kitty"] = home / ".config" / "kitty" / "kitty.conf"
            paths["konsole"] = home / ".local" / "share" / "konsole" / "linux.keytab"
            paths["vscode"] = home / ".config" / "Code" / "User" / "keybindings.json"

            if is_wsl_env:
                # Try to find Windows Terminal settings from inside WSL
                # We have to guess the Windows username, usually defaults to the WSL user
                # or requires searching /mnt/c/Users/
                win_user = None
                win_home = None

                # Method 1: Try to get Windows username via cmd.exe (most accurate)
                try:
                    win_user = os.popen("cmd.exe /c 'echo %USERNAME%'").read().strip()
                except Exception:
                    pass  # cmd.exe might not be in path or accessible

                # Method 2: If cmd.exe failed, try to find a user directory in /mnt/c/Users/
                if not win_user:
                    try:
                        users_dir = Path("/mnt/c/Users")
                        if users_dir.exists():
                            # Look for directories that are likely user directories
                            # Skip system directories like "Public", "Default", etc.
                            system_dirs = {"Public", "Default", "All Users", "Default User"}
                            for item in users_dir.iterdir():
                                if item.is_dir() and item.name not in system_dirs:
                                    win_user = item.name
                                    break
                    except Exception:
                        pass

                if win_user:
                    win_home = Path(f"/mnt/c/Users/{win_user}")
                    try:
                        local_appdata = win_home / "AppData/Local"
                        wt_glob = list(
                            local_appdata.glob(
                                "Packages/Microsoft.WindowsTerminal_*/LocalState/settings.json"
                            )
                        )
                        if wt_glob:
                            paths["windows_terminal"] = wt_glob[0]

                        # Also try to find Windows host VS Code configuration
                        appdata = win_home / "AppData" / "Roaming"
                        vscode_path = appdata / "Code" / "User" / "keybindings.json"
                        paths["vscode_windows"] = vscode_path
                    except Exception:
                        pass  # Windows paths might not be accessible

        elif system == "Darwin":  # macOS
            paths["alacritty"] = home / ".config" / "alacritty" / "alacritty.toml"
            paths["kitty"] = home / ".config" / "kitty" / "kitty.conf"
            # VS Code on macOS
            paths["vscode"] = (
                home / "Library" / "Application Support" / "Code" / "User" / "keybindings.json"
            )

        elif system == "Windows":
            appdata = Path(os.getenv("APPDATA"))
            paths["alacritty"] = appdata / "alacritty" / "alacritty.toml"
            paths["kitty"] = appdata / "kitty" / "kitty.conf"
            # VS Code on Windows
            paths["vscode"] = appdata / "Code" / "User" / "keybindings.json"

            # Windows Terminal path is tricky (has a unique hash in folder name)
            # We look for the folder starting with Microsoft.WindowsTerminal
            local_appdata = Path(os.getenv("LOCALAPPDATA"))
            wt_glob = list(
                local_appdata.glob("Packages/Microsoft.WindowsTerminal_*/LocalState/settings.json")
            )
            if wt_glob:
                paths["windows_terminal"] = wt_glob[0]

        else:  # Linux
            # VS Code on Linux
            paths["vscode"] = home / ".config" / "Code" / "User" / "keybindings.json"

        return paths

    @classmethod
    def _backup_file(cls, file_path, io):
        """Creates a copy of the file with .bak extension."""
        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy(file_path, backup_path)
            io.tool_output(f"Backed up {file_path.name} to {backup_path.name}")
            return True
        return False

    @classmethod
    def _update_alacritty(cls, path, io, dry_run=False):
        """Updates Alacritty TOML configuration with shift+enter binding."""
        import tomlkit

        # Create directory if it doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            if dry_run:
                io.tool_output(f"DRY-RUN: Would create Alacritty config at {path}")
                io.tool_output(
                    'DRY-RUN: Would add binding: {"key": "Return", "mods": "Shift", "chars": "\\n"}'
                )
                return True
            else:
                io.tool_output(f"Creating Alacritty config at {path}")
                # Create minimal Alacritty config with shift+enter binding
                data = {
                    "keyboard": {"bindings": [{"key": "Return", "mods": "Shift", "chars": "\n"}]}
                }
                with open(path, "w", encoding="utf-8") as f:
                    tomlkit.dump(data, f)
                io.tool_output("Created Alacritty config with shift+enter binding.")
                return True

        # Define the binding to add
        new_binding = {"key": "Return", "mods": "Shift", "chars": "\n"}

        if dry_run:
            io.tool_output(f"DRY-RUN: Would check Alacritty config at {path}")
            io.tool_output(f"DRY-RUN: Would add binding: {new_binding}")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = tomlkit.load(f)

                # Check if binding already exists
                keyboard_section = data.get("keyboard", {})
                bindings = keyboard_section.get("bindings", [])

                already_exists = False
                for binding in bindings:
                    if (
                        binding.get("key") == "Return"
                        and binding.get("mods") == "Shift"
                        and binding.get("chars") == "\n"
                    ):
                        already_exists = True
                        break

                if already_exists:
                    io.tool_output("DRY-RUN: Alacritty already configured.")
                    return False
                else:
                    io.tool_output("DRY-RUN: Would update Alacritty config.")
                    return True
            except toml.TOMLDecodeError:
                io.tool_output("DRY-RUN: Error: Could not parse Alacritty TOML file.")
                return False
            except Exception as e:
                io.tool_output(f"DRY-RUN: Error reading file: {e}")
                return False

        cls._backup_file(path, io)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = tomlkit.load(f)

            # Ensure keyboard section exists
            if "keyboard" not in data:
                data["keyboard"] = {}

            # Ensure bindings array exists
            if "bindings" not in data["keyboard"]:
                data["keyboard"]["bindings"] = []

            # Check if binding already exists
            bindings = data["keyboard"]["bindings"]
            already_exists = False
            for binding in bindings:
                if (
                    binding.get("key") == "Return"
                    and binding.get("mods") == "Shift"
                    and binding.get("chars") == "\n"
                ):
                    already_exists = True
                    break

            if already_exists:
                io.tool_output("Alacritty already configured.")
                return False

            # Add the new binding
            data["keyboard"]["bindings"].append(new_binding)

            # Write back to file
            with open(path, "w", encoding="utf-8") as f:
                tomlkit.dump(data, f)

            io.tool_output("Updated Alacritty config.")
            return True

        except toml.TOMLDecodeError:
            io.tool_output("Error: Could not parse Alacritty TOML file. Is it valid TOML?")
            return False
        except Exception as e:
            io.tool_output(f"Error updating Alacritty config: {e}")
            return False

    @classmethod
    def _update_kitty(cls, path, io, dry_run=False):
        """Appends the Kitty mapping if not present."""
        # Create directory if it doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            if dry_run:
                io.tool_output(f"DRY-RUN: Would create Kitty config at {path}")
                io.tool_output(f"DRY-RUN: Would add binding:\n{cls.KITTY_BINDING.strip()}")
                return True
            else:
                io.tool_output(f"Creating Kitty config at {path}")
                # Create Kitty config with shift+enter binding
                with open(path, "w", encoding="utf-8") as f:
                    f.write(cls.KITTY_BINDING)
                io.tool_output("Created Kitty config with shift+enter binding.")
                return True

        if dry_run:
            io.tool_output(f"DRY-RUN: Would check Kitty config at {path}")
            io.tool_output(f"DRY-RUN: Would append binding:\n{cls.KITTY_BINDING.strip()}")
            # Simulate checking for duplicates
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "map shift+enter send_text all \\n" in content:
                    io.tool_output("DRY-RUN: Kitty already configured.")
                    return False
                else:
                    io.tool_output("DRY-RUN: Would update Kitty config.")
                    return True
            except Exception as e:
                io.tool_output(f"DRY-RUN: Error reading file: {e}")
                return False

        cls._backup_file(path, io)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if "map shift+enter send_text all \\n" in content:
            io.tool_output("Kitty already configured.")
            return False

        with open(path, "a", encoding="utf-8") as f:
            f.write(cls.KITTY_BINDING)
        io.tool_output("Updated Kitty config.")
        return True

    @classmethod
    def _update_konsole(cls, path, io, dry_run=False):
        """Updates Konsole keytab configuration with shift+enter binding."""
        default_keytab_path = Path(__file__).parent / "terminal_data" / "linux.keytab"

        if not path.exists():
            if dry_run:
                io.tool_output(f"DRY-RUN: Would create Konsole keytab at {path}")
                return True

            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(default_keytab_path, path)
                io.tool_output(f"Created Konsole keytab at {path}")
                return True
            except Exception as e:
                io.tool_output(f"Error creating Konsole keytab: {e}")
                return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            import re

            # Pattern to find Return+Shift rule
            pattern = r"^\s*key\s+Return\s*\+\s*Shift\s*:\s*(.*)$"
            match = re.search(pattern, content, re.MULTILINE)

            new_rule = 'key Return+Shift : "\\n"'

            if match:
                current_val = match.group(1).strip()
                if current_val == '"\\n"':
                    io.tool_output("Konsole already configured.")
                    return False

                if dry_run:
                    io.tool_output(f"DRY-RUN: Would update Konsole Return+Shift rule in {path}")
                    return True

                cls._backup_file(path, io)
                new_content = re.sub(pattern, new_rule, content, flags=re.MULTILINE)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                io.tool_output("Updated Konsole keytab rule.")
                return True
            else:
                if dry_run:
                    io.tool_output(f"DRY-RUN: Would add Konsole Return+Shift rule to {path}")
                    return True

                cls._backup_file(path, io)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"\n{new_rule}\n")
                io.tool_output("Added Konsole Return+Shift rule.")
                return True
        except Exception as e:
            io.tool_output(f"Error updating Konsole keytab: {e}")
            return False

    @classmethod
    def _update_windows_terminal(cls, path, io, dry_run=False):
        """Parses JSON, adds action to 'actions' list and keybinding to 'keybindings' list."""
        if not path:
            io.tool_output("Skipping Windows Terminal: No path available.")
            return False

        # Create directory if it doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            if dry_run:
                io.tool_output(f"DRY-RUN: Would create Windows Terminal config at {path}")
                io.tool_output(f"DRY-RUN: Would add action: {json.dumps(cls.WT_ACTION, indent=2)}")
                io.tool_output(
                    f"DRY-RUN: Would add keybinding: {json.dumps(cls.WT_KEYBINDING, indent=2)}"
                )
                return True
            else:
                io.tool_output(f"Creating Windows Terminal config at {path}")
                # Create minimal Windows Terminal config with shift+enter binding
                data = {"actions": [cls.WT_ACTION], "keybindings": [cls.WT_KEYBINDING]}
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                io.tool_output("Created Windows Terminal config with shift+enter binding.")
                return True

        if dry_run:
            io.tool_output(f"DRY-RUN: Would check Windows Terminal config at {path}")
            io.tool_output(f"DRY-RUN: Would add action: {json.dumps(cls.WT_ACTION, indent=2)}")
            io.tool_output(
                f"DRY-RUN: Would add keybinding: {json.dumps(cls.WT_KEYBINDING, indent=2)}"
            )
            # Simulate checking for duplicates
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Check if already configured
                already_configured = False

                # Check actions array for our action ID
                actions_list = data.get("actions", [])
                if isinstance(actions_list, list):
                    for action in actions_list:
                        if isinstance(action, dict) and action.get("id") == cls.WT_ACTION["id"]:
                            already_configured = True
                            break

                # Check keybindings array for shift+enter
                keybindings_list = data.get("keybindings", [])
                if isinstance(keybindings_list, list):
                    for binding in keybindings_list:
                        if isinstance(binding, dict) and binding.get("keys") == "shift+enter":
                            already_configured = True
                            break

                if already_configured:
                    io.tool_output("DRY-RUN: Windows Terminal already configured.")
                    return False
                else:
                    io.tool_output("DRY-RUN: Would update Windows Terminal config.")
                    return True
            except json.JSONDecodeError:
                io.tool_output(
                    "DRY-RUN: Error: Could not parse Windows Terminal settings.json. Is it valid"
                    " JSON?"
                )
                return False
            except Exception as e:
                io.tool_output(f"DRY-RUN: Error reading file: {e}")
                return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check if already configured
            already_configured = False

            # Check actions array for our action ID
            actions_list = data.get("actions", [])
            if not isinstance(actions_list, list):
                actions_list = []
                data["actions"] = actions_list

            for action in actions_list:
                if isinstance(action, dict) and action.get("id") == cls.WT_ACTION["id"]:
                    already_configured = True
                    break

            # Check keybindings array for shift+enter
            keybindings_list = data.get("keybindings", [])
            if not isinstance(keybindings_list, list):
                keybindings_list = []
                data["keybindings"] = keybindings_list

            for binding in keybindings_list:
                if isinstance(binding, dict) and binding.get("keys") == "shift+enter":
                    already_configured = True
                    break

            if already_configured:
                io.tool_output("Windows Terminal already configured.")
                return False

            # Add our action to actions array
            actions_list.append(cls.WT_ACTION)
            data["actions"] = actions_list

            # Add our keybinding to keybindings array
            keybindings_list.append(cls.WT_KEYBINDING)
            data["keybindings"] = keybindings_list

            cls._backup_file(path, io)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            io.tool_output("Updated Windows Terminal config.")
            return True

        except json.JSONDecodeError:
            io.tool_output(
                "Error: Could not parse Windows Terminal settings.json. Is it valid JSON?"
            )
            return False

    @classmethod
    def _update_vscode(cls, path, io, dry_run=False):
        """Updates VS Code keybindings.json with shift+enter binding."""
        # Create directory if it doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            if dry_run:
                io.tool_output(f"DRY-RUN: VS Code keybindings.json doesn't exist at {path}")
                io.tool_output(
                    "DRY-RUN: Would create file with binding:"
                    f" {json.dumps(cls.VSCODE_SHIFT_ENTER_BINDING, indent=2)}"
                )
                return True
            else:
                io.tool_output(f"Creating VS Code keybindings.json at {path}")
                # Create file with our binding
                data = [cls.VSCODE_SHIFT_ENTER_BINDING]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                io.tool_output("Created VS Code config with shift+enter binding.")
                return True

        if dry_run:
            io.tool_output(f"DRY-RUN: Would check VS Code keybindings at {path}")
            io.tool_output(
                "DRY-RUN: Would add binding:"
                f" {json.dumps(cls.VSCODE_SHIFT_ENTER_BINDING, indent=2)}"
            )
            # Simulate checking for duplicates
            try:
                content = ""
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Strip comments before parsing
                content_no_comments = cls._strip_json_comments(content)
                if content_no_comments.strip():
                    data = json.loads(content_no_comments)
                else:
                    data = []

                # Check if binding already exists
                already_exists = False
                if isinstance(data, list):
                    for binding in data:
                        if isinstance(binding, dict):
                            # Check if this is our shift+enter binding
                            if (
                                binding.get("key") == "shift+enter"
                                and binding.get("command")
                                == "workbench.action.terminal.sendSequence"
                                and binding.get("when") == "terminalFocus"
                            ):
                                already_exists = True
                                break

                if already_exists:
                    io.tool_output("DRY-RUN: VS Code already configured.")
                    return False
                else:
                    io.tool_output("DRY-RUN: Would update VS Code config.")
                    return True
            except json.JSONDecodeError:
                io.tool_output(
                    "DRY-RUN: Error: Could not parse VS Code keybindings.json. Is it valid JSON?"
                )
                return False
            except Exception as e:
                io.tool_output(f"DRY-RUN: Error reading file: {e}")
                return False

        cls._backup_file(path, io)

        try:
            content = ""
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Strip comments before parsing
            content_no_comments = cls._strip_json_comments(content)
            if content_no_comments.strip():
                data = json.loads(content_no_comments)
            else:
                data = []

            # Ensure data is a list
            if not isinstance(data, list):
                io.tool_output(
                    "Error: VS Code keybindings.json should contain an array of keybindings."
                )
                return False

            # Check if binding already exists
            already_exists = False
            for binding in data:
                if isinstance(binding, dict):
                    # Check if this is our shift+enter binding
                    if (
                        binding.get("key") == "shift+enter"
                        and binding.get("command") == "workbench.action.terminal.sendSequence"
                        and binding.get("when") == "terminalFocus"
                    ):
                        already_exists = True
                        break

            if already_exists:
                io.tool_output("VS Code already configured.")
                return False

            # Add our binding
            data.append(cls.VSCODE_SHIFT_ENTER_BINDING)

            # Write back to file
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            io.tool_output("Updated VS Code config.")
            return True

        except json.JSONDecodeError:
            io.tool_output("Error: Could not parse VS Code keybindings.json. Is it valid JSON?")
            return False
        except Exception as e:
            io.tool_output(f"Error updating VS Code config: {e}")
            return False

    @classmethod
    def _update_vscode_settings(cls, keybindings_path, io, dry_run=False):
        """Updates VS Code settings.json with terminal configuration for proper shift+enter support."""
        # settings.json is in the same directory as keybindings.json
        settings_path = keybindings_path.parent / "settings.json"

        if dry_run:
            io.tool_output(f"DRY-RUN: Would check VS Code settings at {settings_path}")
            io.tool_output(
                "DRY-RUN: Would update settings with:"
                f" {json.dumps(cls.VSCODE_TERMINAL_SETTINGS, indent=2)}"
            )
            # Simulate checking for existing settings
            try:
                if settings_path.exists():
                    content = ""
                    with open(settings_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    content_no_comments = cls._strip_json_comments(content)
                    if content_no_comments.strip():
                        data = json.loads(content_no_comments)
                    else:
                        data = {}

                    # Check if settings are already configured
                    settings_configured = True

                    # Check terminal.integrated.detectLocale
                    if (
                        "terminal.integrated.detectLocale" not in data
                        or data.get("terminal.integrated.detectLocale") != "off"
                    ):
                        settings_configured = False

                    # Check terminal.integrated.commandsToSkipShell
                    if "terminal.integrated.commandsToSkipShell" in data:
                        commands_list = data["terminal.integrated.commandsToSkipShell"]
                        if (
                            isinstance(commands_list, list)
                            and "workbench.action.terminal.sendSequence" in commands_list
                        ):
                            # Command is already in the list
                            pass
                        else:
                            settings_configured = False
                    else:
                        settings_configured = False

                    if settings_configured:
                        io.tool_output("DRY-RUN: VS Code settings already configured.")
                        return False
                    else:
                        io.tool_output("DRY-RUN: Would update VS Code settings.")
                        return True
                else:
                    io.tool_output(
                        "DRY-RUN: Would create VS Code settings.json with required settings."
                    )
                    return True
            except Exception as e:
                io.tool_output(f"DRY-RUN: Error checking settings: {e}")
                return False

        # Create directory if it doesn't exist
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = {}
            if settings_path.exists():
                cls._backup_file(settings_path, io)
                content = ""
                with open(settings_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Strip comments before parsing
                content_no_comments = cls._strip_json_comments(content)
                if content_no_comments.strip():
                    data = json.loads(content_no_comments)
                else:
                    data = {}

            # Ensure data is a dictionary
            if not isinstance(data, dict):
                io.tool_output("Error: VS Code settings.json should be a JSON object.")
                return False

            # Check if settings are already configured
            settings_configured = True

            # Check terminal.integrated.detectLocale
            if (
                "terminal.integrated.detectLocale" not in data
                or data.get("terminal.integrated.detectLocale") != "off"
            ):
                settings_configured = False

            # Check terminal.integrated.commandsToSkipShell
            if "terminal.integrated.commandsToSkipShell" in data:
                commands_list = data["terminal.integrated.commandsToSkipShell"]
                if (
                    isinstance(commands_list, list)
                    and "workbench.action.terminal.sendSequence" in commands_list
                ):
                    # Command is already in the list
                    pass
                else:
                    settings_configured = False
            else:
                settings_configured = False

            if settings_configured:
                io.tool_output("VS Code settings already configured.")
                return False

            # Update settings with our configuration
            # Set terminal.integrated.detectLocale
            data["terminal.integrated.detectLocale"] = "off"

            # Handle terminal.integrated.commandsToSkipShell
            if "terminal.integrated.commandsToSkipShell" in data:
                commands_list = data["terminal.integrated.commandsToSkipShell"]
                if isinstance(commands_list, list):
                    # Add our command if not already present
                    if "workbench.action.terminal.sendSequence" not in commands_list:
                        commands_list.append("workbench.action.terminal.sendSequence")
                        data["terminal.integrated.commandsToSkipShell"] = commands_list
                else:
                    # If it's not a list, replace with our list
                    data["terminal.integrated.commandsToSkipShell"] = [
                        "workbench.action.terminal.sendSequence"
                    ]
            else:
                # Create new list with our command
                data["terminal.integrated.commandsToSkipShell"] = [
                    "workbench.action.terminal.sendSequence"
                ]

            # Write back to file
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            io.tool_output("Updated VS Code settings.")
            return True

        except json.JSONDecodeError:
            io.tool_output("Error: Could not parse VS Code settings.json. Is it valid JSON?")
            return False
        except Exception as e:
            io.tool_output(f"Error updating VS Code settings: {e}")
            return False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Configure terminal config files to support shift+enter for newline."""
        io.tool_output(f"Detecting OS: {platform.system()}")
        paths = cls._get_config_paths()

        # Check for dry-run mode
        dry_run = args == "dry_run" or (hasattr(args, "dry_run") and args.dry_run)
        if dry_run:
            io.tool_output("DRY-RUN MODE: Showing what would be changed without modifying files\n")

        # Explicit yes required should always be true for terminal setup
        explicit_yes_required = True

        updated = False

        if "alacritty" in paths:
            path = paths["alacritty"]
            if path.exists():
                question = f"Update Alacritty config at {path} to add shift+enter binding?"
            else:
                question = f"Create new Alacritty config at {path} with shift+enter binding?"

            if dry_run or await coder.io.confirm_ask(
                question, default="y", explicit_yes_required=explicit_yes_required
            ):
                if cls._update_alacritty(path, io, dry_run=dry_run):
                    updated = True

        if "kitty" in paths:
            path = paths["kitty"]
            if path.exists():
                question = f"Update Kitty config at {path} to add shift+enter binding?"
            else:
                question = f"Create new Kitty config at {path} with shift+enter binding?"

            if dry_run or await coder.io.confirm_ask(
                question, default="y", explicit_yes_required=explicit_yes_required
            ):
                if cls._update_kitty(path, io, dry_run=dry_run):
                    updated = True

        if "konsole" in paths:
            path = paths["konsole"]
            if path.exists():
                question = f"Update Konsole keytab at {path} to add shift+enter binding?"
            else:
                question = f"Create new Konsole keytab at {path} with shift+enter binding?"

            if dry_run or await coder.io.confirm_ask(
                question, default="y", explicit_yes_required=explicit_yes_required
            ):
                if cls._update_konsole(path, io, dry_run=dry_run):
                    updated = True

        if "windows_terminal" in paths:
            path = paths["windows_terminal"]
            if path.exists():
                question = f"Update Windows Terminal config at {path} to add shift+enter binding?"
            else:
                question = f"Create new Windows Terminal config at {path} with shift+enter binding?"

            if dry_run or await coder.io.confirm_ask(
                question, default="y", explicit_yes_required=explicit_yes_required
            ):
                if cls._update_windows_terminal(path, io, dry_run=dry_run):
                    updated = True

        if "vscode" in paths:
            path = paths["vscode"]
            if path.exists():
                question = f"Update VS Code keybindings at {path} to add shift+enter binding?"
            else:
                question = f"Create new VS Code keybindings at {path} with shift+enter binding?"

            if dry_run or await coder.io.confirm_ask(
                question, default="y", explicit_yes_required=explicit_yes_required
            ):
                if cls._update_vscode(path, io, dry_run=dry_run):
                    updated = True
                # Also update VS Code settings.json for proper shift+enter support
                settings_question = (
                    f"Update VS Code settings at {path.parent}/settings.json for proper shift+enter"
                    " support?"
                )
                if dry_run or await coder.io.confirm_ask(
                    settings_question, default="y", explicit_yes_required=explicit_yes_required
                ):
                    if cls._update_vscode_settings(path, io, dry_run=dry_run):
                        updated = True

        if "vscode_windows" in paths:
            path = paths["vscode_windows"]
            io.tool_output("Found Windows host VS Code configuration (running in WSL)")
            if path.exists():
                question = (
                    f"Update Windows host VS Code keybindings at {path} to add shift+enter binding?"
                )
            else:
                question = (
                    f"Create new Windows host VS Code keybindings at {path} with shift+enter"
                    " binding?"
                )

            if dry_run or await coder.io.confirm_ask(
                question, default="y", explicit_yes_required=explicit_yes_required
            ):
                if cls._update_vscode(path, io, dry_run=dry_run):
                    updated = True
                # Also update Windows host VS Code settings.json
                settings_question = (
                    f"Update Windows host VS Code settings at {path.parent}/settings.json for"
                    " proper shift+enter support?"
                )
                if dry_run or await coder.io.confirm_ask(
                    settings_question, default="y", explicit_yes_required=explicit_yes_required
                ):
                    if cls._update_vscode_settings(path, io, dry_run=dry_run):
                        updated = True

        if dry_run:
            if updated:
                io.tool_output(
                    "\nDRY-RUN: Would make changes (restart terminals for changes to take effect)."
                )
            else:
                io.tool_output(
                    "\nDRY-RUN: No changes would be made (configurations already present or files"
                    " not found)."
                )
            return format_command_result(
                io, "terminal-setup", "Dry-run completed - showing what would be changed"
            )
        elif updated:
            io.tool_output("\nDone! Please restart your terminals for changes to take effect.")
            return format_command_result(
                io, "terminal-setup", "Successfully configured terminal settings"
            )
        else:
            io.tool_output(
                "\nNo changes were made (configurations already present or files not found)."
            )
            return format_command_result(
                io, "terminal-setup", "No changes needed - configurations already present"
            )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for terminal-setup command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the terminal-setup command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /terminal-setup  # Configure terminal to support shift+enter for newline\n"
        help_text += (
            "  /terminal-setup --dry-run  # Show what would be changed without modifying files\n"
        )
        help_text += (
            "\nNote: This command modifies terminal configuration files (Alacritty, Kitty, Konsole,"
            " Windows Terminal, VS Code)\n"
        )
        help_text += (
            "to add a key binding that sends a newline character when shift+enter is pressed.\n"
        )
        help_text += "Backup copies are created with .bak extension before any modifications.\n"
        help_text += "Use --dry-run to preview changes before applying them.\n"
        return help_text
