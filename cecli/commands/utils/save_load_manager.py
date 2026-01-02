import os
from pathlib import Path
from typing import List


class SaveLoadManager:
    """Manager for saving and loading command files."""

    def __init__(self, coder, io):
        self.coder = coder
        self.io = io

    def get_saves_directory(self) -> Path:
        """Get the saves directory, creating it if necessary."""
        saves_dir = Path(self.coder.abs_root_path(".cecli/saves"))
        os.makedirs(saves_dir, exist_ok=True)
        return saves_dir

    def resolve_filepath(self, filename: str) -> Path:
        """Resolve a filename to an absolute path, using saves directory if needed."""
        filepath = Path(filename)

        # If it's a simple filename (no directory separators), save to .cecli/saves/
        if not filepath.is_absolute() and str(filepath) == filepath.name:
            saves_dir = self.get_saves_directory()
            filepath = saves_dir / filepath

        return filepath

    def save_commands(self, filename: str) -> Path:
        """Save commands to reconstruct the current chat session to a file."""
        filepath = self.resolve_filepath(filename)

        try:
            # Ensure parent directory exists
            os.makedirs(filepath.parent, exist_ok=True)

            with open(filepath, "w", encoding=self.io.encoding) as f:
                f.write("/drop\n")
                # Write commands to add editable files
                for fname in sorted(self.coder.abs_fnames):
                    rel_fname = self.coder.get_rel_fname(fname)
                    f.write(f"/add {rel_fname}\n")

                # Write commands to add read-only files
                for fname in sorted(self.coder.abs_read_only_fnames):
                    # Use absolute path for files outside repo root, relative path for files inside
                    if Path(fname).is_relative_to(self.coder.root):
                        rel_fname = self.coder.get_rel_fname(fname)
                        f.write(f"/read-only {rel_fname}\n")
                    else:
                        f.write(f"/read-only {fname}\n")
                # Write commands to add read-only stubs files
                for fname in sorted(self.coder.abs_read_only_stubs_fnames):
                    # Use absolute path for files outside repo root, relative path for files inside
                    if Path(fname).is_relative_to(self.coder.root):
                        rel_fname = self.coder.get_rel_fname(fname)
                        f.write(f"/read-only-stub {rel_fname}\n")
                    else:
                        f.write(f"/read-only-stub {fname}\n")

            return filepath
        except Exception as e:
            raise IOError(f"Error saving commands to file: {e}")

    def load_commands(self, filename: str) -> List[str]:
        """Load commands from a file."""
        filepath = self.resolve_filepath(filename)

        try:
            with open(filepath, "r", encoding=self.io.encoding, errors="replace") as f:
                commands = f.readlines()
            return [
                cmd.strip() for cmd in commands if cmd.strip() and not cmd.strip().startswith("#")
            ]
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {filepath}")
        except Exception as e:
            raise IOError(f"Error reading file: {e}")

    def list_files(self) -> List[str]:
        """Return a list of all filenames (without extensions) in the saves directory.

        Returns:
            List[str]: List of filenames without extensions, sorted alphabetically
        """
        try:
            saves_dir = self.get_saves_directory()

            if not saves_dir.exists():
                return []

            # Get all files (not directories) in the saves directory
            save_files = [f.name for f in saves_dir.iterdir() if f.is_file()]
            return sorted(save_files)
        except Exception:
            # Return empty list on any error
            return []
