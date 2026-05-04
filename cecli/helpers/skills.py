"""
Skills helper for cecli.

This module provides functions for loading, parsing, and managing skills
according to the Skills specification.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Global state store for sticky include/exclude lists, keyed by coder.uuid
# This ensures skill state survives SkillsManager re-creation within the same coder session
_skill_state_store: Dict[str, Dict[str, Any]] = {}


@dataclass
class SkillMetadata:
    """Metadata for an skill."""

    name: str
    description: str
    path: Path
    license: Optional[str] = None
    allowed_tools: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillContent:
    """Complete skill content including metadata and instructions."""

    metadata: SkillMetadata
    frontmatter: Dict[str, Any]
    instructions: str
    references: Dict[str, Path] = field(default_factory=dict)
    scripts: Dict[str, Path] = field(default_factory=dict)
    assets: Dict[str, Path] = field(default_factory=dict)
    evals: Dict[str, Path] = field(default_factory=dict)


class SkillsManager:
    """Manager for loading and managing skills."""

    def __init__(
        self,
        directory_paths: List[str],
        include_list: Optional[List[str]] = None,
        exclude_list: Optional[List[str]] = None,
        git_root: Optional[str] = None,
        coder=None,
    ):
        """
        Initialize the skills manager.

        Args:
            directory_paths: List of directory paths to search for skills
            include_list: Optional list of skill names to include (whitelist)
            exclude_list: Optional list of skill names to exclude (blacklist)
            git_root: Optional git root directory for relative path resolution
            coder: Optional reference to the coder instance (weak reference)
        """
        self.directory_paths = [Path(p).expanduser().resolve() for p in directory_paths]
        self.include_list = set(include_list) if include_list else None
        self.exclude_list = set(exclude_list) if exclude_list else set()
        self.git_root = Path(git_root).expanduser().resolve() if git_root else None
        self.coder = coder  # Weak reference to coder instance

        # Cache for loaded skills
        self._skills_cache: Dict[str, SkillContent] = {}
        self._skill_metadata_cache: Dict[str, SkillMetadata] = {}
        self._skills_find_cache: Optional[List[SkillMetadata]] = None

        # Track which skills have been loaded via load_skill()
        self._loaded_skills: set[str] = set()

        # Restore state from global store (sticky across SkillsManager recreation)
        if not self._restore_state():
            # First time initialization - save initial state from config
            self._save_state()

    def _save_state(self):
        """Save current mutable state to the global skill state store.

        This allows state to persist across SkillsManager re-creation
        within the same coder session.
        """
        if not self.coder or not getattr(self.coder, "uuid", None):
            return

        _skill_state_store[self.coder.uuid] = {
            "include_list": self.include_list.copy() if self.include_list is not None else None,
            "exclude_list": self.exclude_list.copy(),
            "loaded_skills": self._loaded_skills.copy(),
        }

    def _restore_state(self) -> bool:
        """Restore mutable state from the global skill state store if available.

        Returns:
            True if state was restored, False otherwise.
        """

        if not self.coder or not getattr(self.coder, "uuid", None):
            return False

        state = _skill_state_store.get(self.coder.uuid)

        if state is None:
            return False

        self.include_list = (
            state["include_list"].copy() if state["include_list"] is not None else None
        )
        self.exclude_list = state["exclude_list"].copy()
        self._loaded_skills = state["loaded_skills"].copy()

        return True

    def find_skills(self, reload: bool = False) -> List[SkillMetadata]:
        """
        Find all skills in the configured directory paths.

        Args:
            reload: If True, force reload from disk instead of using cache

        Returns:
            List of skill metadata objects
        """
        # Return cached results if available and not forced to reload
        if not reload and self._skills_find_cache is not None:
            return self._skills_find_cache

        skills = []

        for directory_path in self.directory_paths:
            if not directory_path.exists():
                continue

            # Look for directories containing SKILL.md files
            for skill_dir in directory_path.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_md_path = skill_dir / "SKILL.md"
                if skill_md_path.exists():
                    try:
                        metadata = self._parse_skill_metadata(skill_md_path)
                        skill_name = metadata.name

                        # Apply include/exclude filters
                        if self.include_list and skill_name not in self.include_list:
                            continue
                        if skill_name in self.exclude_list:
                            continue

                        skills.append(metadata)
                        self._skill_metadata_cache[skill_name] = metadata
                    except Exception:
                        # Skip skills that can't be parsed
                        continue

        # Cache the results
        self._skills_find_cache = skills
        return skills

    def hot_reload(self):
        self._skills_cache = {}
        self._skill_metadata_cache = {}
        self.find_skills(reload=True)

    def _parse_skill_metadata(self, skill_md_path: Path) -> SkillMetadata:
        """
        Parse the metadata from a SKILL.md file.

        Args:
            skill_md_path: Path to the SKILL.md file

        Returns:
            SkillMetadata object
        """
        content = skill_md_path.read_text(encoding="utf-8")

        # Parse YAML frontmatter (between --- markers)
        frontmatter_match = re.search(
            r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE
        )
        if not frontmatter_match:
            raise ValueError(f"No YAML frontmatter found in {skill_md_path}")

        frontmatter = yaml.safe_load(frontmatter_match.group(1))

        # Extract required fields
        name = frontmatter.get("name")
        description = frontmatter.get("description")

        if not name or not description:
            raise ValueError(f"Missing required fields (name or description) in {skill_md_path}")

        return SkillMetadata(
            name=name,
            description=description,
            path=skill_md_path.parent,
            license=frontmatter.get("license"),
            allowed_tools=frontmatter.get("allowed-tools", []),
            metadata=frontmatter.get("metadata", {}),
        )

    def get_skill_content(self, skill_name: str) -> Optional[SkillContent]:
        """
        Get skill content by name (loads and caches if not already loaded).

        Args:
            skill_name: Name of the skill to get

        Returns:
            SkillContent object or None if not found
        """
        # Check cache first
        if skill_name in self._skills_cache:
            return self._skills_cache[skill_name]

        # Find the skill metadata
        if skill_name not in self._skill_metadata_cache:
            # Try to find it
            skills = self.find_skills()
            skill_metadata = next((s for s in skills if s.name == skill_name), None)
            if not skill_metadata:
                return None
            self._skill_metadata_cache[skill_name] = skill_metadata
        else:
            skill_metadata = self._skill_metadata_cache[skill_name]

        # Load the complete skill
        skill_content = self._load_complete_skill(skill_metadata)
        self._skills_cache[skill_name] = skill_content

        return skill_content

    def _load_complete_skill(self, metadata: SkillMetadata) -> SkillContent:
        """
        Load a complete skill including all components.

        Args:
            metadata: SkillMetadata object

        Returns:
            SkillContent object
        """
        skill_dir = metadata.path

        # Load SKILL.md content
        skill_md_path = skill_dir / "SKILL.md"
        content = skill_md_path.read_text(encoding="utf-8")

        # Parse frontmatter and instructions
        frontmatter_match = re.search(
            r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE
        )
        if not frontmatter_match:
            raise ValueError(f"No YAML frontmatter found in {skill_md_path}")

        frontmatter = yaml.safe_load(frontmatter_match.group(1))
        instructions = content[frontmatter_match.end() :].strip()

        # Load references
        references = self._load_references(skill_dir)

        # Load scripts
        scripts = self._load_scripts(skill_dir)

        # Load assets
        assets = self._load_assets(skill_dir)

        # Load evals
        evals = self._load_evals(skill_dir)

        return SkillContent(
            metadata=metadata,
            frontmatter=frontmatter,
            instructions=instructions,
            references=references,
            scripts=scripts,
            assets=assets,
            evals=evals,
        )

    def _load_references(self, skill_dir: Path) -> Dict[str, Path]:
        """Load reference files from the references/ directory."""
        references = {}
        references_dir = skill_dir / "references"

        if references_dir.exists():
            for ref_file in references_dir.glob("**/*.md"):
                try:
                    # Use relative path as key, store the Path object
                    rel_path = ref_file.relative_to(references_dir)
                    references[str(rel_path)] = ref_file
                except Exception:
                    continue

        return references

    def _load_scripts(self, skill_dir: Path) -> Dict[str, Path]:
        """Load script files from the scripts/ directory."""
        scripts = {}
        scripts_dir = skill_dir / "scripts"

        if scripts_dir.exists():
            for script_file in scripts_dir.glob("**/*"):
                if script_file.is_file():
                    try:
                        # Use relative path as key, store the Path object
                        rel_path = script_file.relative_to(scripts_dir)
                        scripts[str(rel_path)] = script_file
                    except Exception:
                        continue

        return scripts

    def _load_assets(self, skill_dir: Path) -> Dict[str, Path]:
        """Load asset files from the assets/ directory."""
        assets = {}
        assets_dir = skill_dir / "assets"

        if assets_dir.exists():
            for asset_file in assets_dir.glob("**/*"):
                if asset_file.is_file():
                    try:
                        # Use relative path as key, store the Path object
                        rel_path = asset_file.relative_to(assets_dir)
                        assets[str(rel_path)] = asset_file
                    except Exception:
                        continue

        return assets

    def _load_evals(self, skill_dir: Path) -> Dict[str, Path]:
        """Load eval files from the evals/ directory."""
        evals = {}
        evals_dir = skill_dir / "evals"

        if evals_dir.exists():
            for eval_file in evals_dir.glob("**/*"):
                if eval_file.is_file():
                    try:
                        # Use relative path as key, store the Path object
                        rel_path = eval_file.relative_to(evals_dir)
                        evals[str(rel_path)] = eval_file
                    except Exception:
                        continue

        return evals

    def get_skill_summary(self, skill_name: str) -> Optional[str]:
        """
        Get a summary of a skill for display purposes.

        Args:
            skill_name: Name of the skill

        Returns:
            Summary string or None if skill not found
        """
        skill = self.get_skill_content(skill_name)
        if not skill:
            return None

        summary = f"Skill: {skill.metadata.name}\n"
        summary += f"Description: {skill.metadata.description}\n"

        if skill.metadata.license:
            summary += f"License: {skill.metadata.license}\n"

        if skill.metadata.allowed_tools:
            summary += f"Allowed tools: {', '.join(skill.metadata.allowed_tools)}\n"

        summary += f"Path: {skill.metadata.path}\n"

        # Count resources
        ref_count = len(skill.references)
        script_count = len(skill.scripts)
        asset_count = len(skill.assets)
        eval_count = len(skill.evals)

        summary += (
            f"Resources: {ref_count} references, {script_count} scripts, {asset_count} assets,"
            f" {eval_count} evals\n"
        )

        return summary

    def get_all_skill_summaries(self) -> Dict[str, str]:
        """
        Get summaries for all available skills.

        Returns:
            Dictionary mapping skill names to summary strings
        """
        skills = self.find_skills()
        summaries = {}

        for skill_metadata in skills:
            summary = self.get_skill_summary(skill_metadata.name)
            if summary:
                summaries[skill_metadata.name] = summary

        return summaries

    def load_skill(self, skill_name: str) -> str:
        """
        Add a skill to the loaded skills set for inclusion in context.

        Returns:
            Success or error message
        """
        if not skill_name:
            return "Error: Skill name is required."

        # Check if coder is available
        if not self.coder:
            return "Error: Skills manager not connected to a coder instance."

        # Check if we're in agent mode
        if not hasattr(self.coder, "edit_format") or self.coder.edit_format != "agent":
            return "Error: Skill loading is only available in agent mode."

        # Check if skill is already loaded
        if skill_name in self._loaded_skills:
            return f"Skill '{skill_name}' is already loaded."

        # Find the skill to verify it exists
        skills = self.find_skills()
        skill_found = any(skill.name == skill_name for skill in skills)

        if skill_found:
            # Load the skill content
            skill_content = self.get_skill_content(skill_name)

            if skill_content:
                # Add to loaded skills set
                self._loaded_skills.add(skill_name)

                # Persist state to global store
                self._save_state()

                result = f"Skill '{skill_name}' loaded successfully."

                # Show skill summary
                summary = self.get_skill_summary(skill_name)
                if summary:
                    result += f"\n\n{summary}"
                return result
            else:
                return f"Error: Skill '{skill_name}' found but could not be loaded."
        else:
            return f"Error: Skill '{skill_name}' not found in configured directories."

    def remove_skill(self, skill_name: str) -> str:
        """
        Remove a skill from the loaded skills set.

        Returns:
            Success or error message
        """
        if not skill_name:
            return "Error: Skill name is required."

        # Check if coder is available
        if not self.coder:
            return "Error: Skills manager not connected to a coder instance."

        # Check if we're in agent mode
        if not hasattr(self.coder, "edit_format") or self.coder.edit_format != "agent":
            return "Error: Skill removal is only available in agent mode."

        # Check if skill is already removed
        if skill_name not in self._loaded_skills:
            return f"Skill '{skill_name}' is not loaded."

        # Remove from loaded skills set
        self._loaded_skills.remove(skill_name)

        # Persist state to global store
        self._save_state()

        return f"Skill '{skill_name}' removed successfully."

    def include_skill(self, skill_name: str) -> str:
        """
        Add a skill to the include list (whitelist), making only this skill visible.
        This method controls which skills are discoverable via find_skills().

        Args:
            skill_name: Name of the skill to include

        Returns:
            Success or error message
        """
        if not skill_name:
            return "Error: Skill name is required."

        # Check if coder is available
        if not self.coder:
            return "Error: Skills manager not connected to a coder instance."

        # Check if we're in agent mode
        if not hasattr(self.coder, "edit_format") or self.coder.edit_format != "agent":
            return "Error: Skill inclusion is only available in agent mode."

        # Find the skill to verify it exists
        skills = self.find_skills(reload=True)
        skill_found = any(skill.name == skill_name for skill in skills)

        if not skill_found:
            # The skill might already be filtered out by the include/exclude lists.
            # Check if it exists in any directory by scanning without filters.
            original_include = self.include_list
            original_exclude = self.exclude_list
            self.include_list = None
            self.exclude_list = set()
            all_skills = self.find_skills(reload=True)
            self.include_list = original_include
            self.exclude_list = original_exclude
            skill_found = any(skill.name == skill_name for skill in all_skills)

        if not skill_found:
            return f"Error: Skill '{skill_name}' not found in configured directories."

        # Ensure include_list is initialized
        if self.include_list is None:
            self.include_list = set()
        self.include_list.add(skill_name)

        # Also remove from exclude_list if present
        if skill_name in self.exclude_list:
            self.exclude_list.discard(skill_name)

        # Persist state to global store
        self._save_state()

        # Clear caches so find_skills reflects the change
        self.hot_reload()

        return f"Skill '{skill_name}' has been included (whitelisted)."

    def exclude_skill(self, skill_name: str) -> str:
        """
        Add a skill to the exclude list (blacklist), hiding it from discovery.
        This method controls which skills are hidden via find_skills().

        Args:
            skill_name: Name of the skill to exclude

        Returns:
            Success or error message
        """
        if not skill_name:
            return "Error: Skill name is required."

        # Check if coder is available
        if not self.coder:
            return "Error: Skills manager not connected to a coder instance."

        # Check if we're in agent mode
        if not hasattr(self.coder, "edit_format") or self.coder.edit_format != "agent":
            return "Error: Skill exclusion is only available in agent mode."

        # Find the skill to verify it exists
        skills = self.find_skills(reload=True)
        skill_found = any(skill.name == skill_name for skill in skills)

        if not skill_found:
            # The skill might already be filtered out by include/exclude lists.
            # Check if it exists in any directory by scanning without filters.
            original_include = self.include_list
            original_exclude = self.exclude_list
            self.include_list = None
            self.exclude_list = set()
            all_skills = self.find_skills(reload=True)
            self.include_list = original_include
            self.exclude_list = original_exclude
            skill_found = any(skill.name == skill_name for skill in all_skills)

        if not skill_found:
            return f"Error: Skill '{skill_name}' not found in configured directories."

        # Add to exclude_list
        self.exclude_list.add(skill_name)

        # Also remove from include_list if present
        if self.include_list and skill_name in self.include_list:
            self.include_list.discard(skill_name)
            # If include_list is now empty, reset to None (no whitelist filtering)
            if not self.include_list:
                self.include_list = None

        # Also remove from loaded_skills if present, since it won't be visible
        if skill_name in self._loaded_skills:
            self._loaded_skills.discard(skill_name)

        # Persist state to global store
        self._save_state()

        # Clear caches so find_skills reflects the change
        self.hot_reload()

        return f"Skill '{skill_name}' has been excluded (blacklisted)."

    def get_all_skills_info(self) -> List[Dict[str, Any]]:
        """
        Get detailed information about all skills across all directories,
        including their current state (included, excluded, loaded) and file paths.

        This bypasses include/exclude filters to give a complete picture.

        Returns:
            List of dicts with keys: name, description, path, license, allowed_tools,
            status ("included", "excluded", "visible"), loaded, has_references,
            has_scripts, has_assets, has_evals
        """
        # Save current filter state
        original_include = self.include_list
        original_exclude = self.exclude_list

        # Scan without filters to find all skills
        self.include_list = None
        self.exclude_list = set()
        all_skills = self.find_skills(reload=True)

        # Restore original filter state
        self.include_list = original_include
        self.exclude_list = original_exclude

        # Also restore the cache to reflect the actual filters
        self.hot_reload()

        result = []
        for meta in all_skills:
            skill_name = meta.name

            # Determine status
            if original_include is not None and skill_name in original_include:
                status = "included"
            elif skill_name in original_exclude:
                status = "excluded"
            else:
                status = "visible"

            # Check if loaded
            is_loaded = skill_name in self._loaded_skills

            skill_content = self._skills_cache.get(skill_name)
            has_references = bool(skill_content and skill_content.references)
            has_scripts = bool(skill_content and skill_content.scripts)
            has_assets = bool(skill_content and skill_content.assets)
            has_evals = bool(skill_content and skill_content.evals)

            info = {
                "name": skill_name,
                "description": meta.description,
                "path": str(meta.path),
                "license": meta.license,
                "allowed_tools": meta.allowed_tools,
                "status": status,
                "loaded": is_loaded,
                "has_references": has_references,
                "has_scripts": has_scripts,
                "has_assets": has_assets,
                "has_evals": has_evals,
            }
            result.append(info)

        return result

    def get_skills_list_formatted(self) -> str:
        """
        Get a human-readable table of all skills with their states and paths.

        Returns:
            Formatted string listing all skills with state and path info
        """
        all_skills = self.get_all_skills_info()

        if not all_skills:
            return "No skills found in the configured directories."

        # Calculate column widths
        name_width = max(len(s["name"]) for s in all_skills)
        name_width = max(name_width, len("Skill Name"))

        status_width = max(len(s["status"]) for s in all_skills)
        status_width = max(status_width, len("Status"))

        result = f"Found {len(all_skills)} skill(s) in configured directories:\n\n"

        # Header
        header = f"  {'Skill Name'.ljust(name_width)}  {'Status'.ljust(status_width)}  Loaded  Path"
        result += header + "\n"
        result += "-" * len(header) + "\n"

        for skill in all_skills:
            name = skill["name"].ljust(name_width)
            status = skill["status"].ljust(status_width)
            loaded = "Yes" if skill["loaded"] else "No"
            path = skill["path"]
            result += f"  {name}  {status}  {loaded:<5}  {path}\n"

        result += "\n"
        result += "Status meanings:\n"
        result += "  included  - Skill is whitelisted (skill available for discovery/loading)\n"
        result += "  excluded  - Skill is blacklisted (hidden from discovery)\n"
        result += "  loaded    - Whether the skill content has been loaded via load_skill\n"

        return result

    @classmethod
    def skill_summary_loader(
        cls,
        directory_paths: List[str],
        include_list: Optional[List[str]] = None,
        exclude_list: Optional[List[str]] = None,
        git_root: Optional[str] = None,
    ) -> str:
        """
        High-level function to load and summarize all available skills.

        Args:
            directory_paths: List of directory paths to search for skills
            include_list: Optional list of skill names to include (whitelist)
            exclude_list: Optional list of skill names to exclude (blacklist)
            git_root: Optional git root directory for relative path resolution

        Returns:
            Formatted summary of all available skills
        """
        manager = cls(directory_paths, include_list, exclude_list, git_root)
        summaries = manager.get_all_skill_summaries()

        if not summaries:
            return "No skills found in the specified directories."

        result = f"Found {len(summaries)} skill(s):\n\n"

        for i, (skill_name, summary) in enumerate(summaries.items(), 1):
            result += f"{i}. {summary}\n"

        return result

    @staticmethod
    def resolve_skill_directories(
        base_paths: List[str], git_root: Optional[str] = None
    ) -> List[Path]:
        """
        Resolve skill directory paths relative to various locations.

        Args:
            base_paths: List of base directory paths
            git_root: Optional git root directory

        Returns:
            List of resolved Path objects
        """
        resolved_paths = []

        for base_path in base_paths:
            # Try to resolve relative to git root first
            if git_root and not Path(base_path).is_absolute():
                git_path = Path(git_root) / base_path
                if git_path.exists():
                    resolved_paths.append(git_path.resolve())
                    continue

            # Try as absolute or relative to current directory
            try:
                path = Path(base_path).expanduser().resolve()
                if path.exists():
                    resolved_paths.append(path)
            except Exception:
                continue

        return resolved_paths

    def get_skills_content(self) -> Optional[str]:
        """
        Generate a context block with skill metadata and file paths for references, scripts, and assets.

        Returns:
            Formatted context block string with skill metadata and file paths or None if no skills available
        """
        try:
            # Only return skills that have been explicitly loaded via load_skill()
            if not self._loaded_skills:
                return None

            result = '<context name="loaded_skills" from="agent">\n'
            result += "## Loaded Skills Content\n\n"
            result += f"Found {len(self._loaded_skills)} skill(s) in configured directories:\n\n"

            for i, skill_name in enumerate(sorted(self._loaded_skills)):
                # Load the complete skill (should be cached)
                skill_content = self.get_skill_content(skill_name)
                if not skill_content:
                    continue

                result += f"### Skill {i}: {skill_content.metadata.name}\n\n"
                result += f"**Description**: {skill_content.metadata.description}\n\n"

                if skill_content.metadata.license:
                    result += f"**License**: {skill_content.metadata.license}\n\n"

                if skill_content.metadata.allowed_tools:
                    result += (
                        f"**Allowed Tools**: {', '.join(skill_content.metadata.allowed_tools)}\n\n"
                    )

                # Add instructions
                result += "#### Instructions\n\n"
                result += f"{skill_content.instructions}\n\n"

                # Add references file paths
                if skill_content.references:
                    result += "#### References\n\n"
                    result += f"Available reference files ({len(skill_content.references)}):\n\n"
                    for ref_name, ref_path in skill_content.references.items():
                        result += f"- **{ref_name}**: `{ref_path}`\n"
                    result += "\n"

                # Add scripts file paths
                if skill_content.scripts:
                    result += "#### Scripts\n\n"
                    result += f"Available script files ({len(skill_content.scripts)}):\n\n"
                    for script_name, script_path in skill_content.scripts.items():
                        result += f"- **{script_name}**: `{script_path}`\n"
                    result += "\n"

                # Add assets file paths
                if skill_content.assets:
                    result += f"#### Assets ({len(skill_content.assets)} file(s))\n\n"
                    result += "Available asset files:\n\n"
                    for asset_name, asset_path in skill_content.assets.items():
                        result += f"- **{asset_name}**: `{asset_path}`\n"
                    result += "\n"

                # Add evals file paths
                if skill_content.evals:
                    result += f"#### Evals ({len(skill_content.evals)} file(s))\n\n"
                    result += "Available eval files:\n\n"
                    for eval_name, eval_path in skill_content.evals.items():
                        result += f"- **{eval_name}**: `{eval_path}`\n"
                    result += "\n"

                result += "---\n\n"

            result += "</context>"
            return result
        except Exception:
            # We can't use io.tool_error here since we don't have access to io
            # The caller should handle the exception
            raise

    def get_skills_context(self) -> Optional[str]:
        """
        Generate a context block for available skills.

        Returns:
            Formatted context block string or None if no skills available
        """
        try:
            # Get skill summaries
            summaries = self.get_all_skill_summaries()
            if not summaries:
                return None

            result = '<context name="skills" from="agent">\n'
            result += "## Available Skills\n\n"
            result += f"Found {len(summaries)} skill(s) in configured directories:\n\n"

            for i, (skill_name, summary) in enumerate(summaries.items(), 1):
                result += f"### Skill {i}: {skill_name}\n\n"
                result += f"{summary}\n"

            result += (
                "Use the `LoadSkill` tool with the skill name if "
                "the skill is relevant to the current task."
            )
            result += "</context>"
            return result
        except Exception:
            # We can't use io.tool_error here since we don't have access to io
            # The caller should handle the exception
            raise
