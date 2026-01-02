"""
Tests for cecli/helpers/skills.py
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cecli.helpers.skills import SkillsManager


class TestSkills:
    """Test suite for skills helper module."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        import shutil

        self.temp_dir = tempfile.mkdtemp()

        yield

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_skills_manager_initialization(self):
        """Test that SkillsManager initializes correctly."""
        # Test with empty directory paths
        manager = SkillsManager([])
        assert manager.directory_paths == []
        assert manager.include_list is None
        assert manager.exclude_list == set()
        assert manager.git_root is None
        # Test _loaded_skills is initialized as empty set
        assert manager._loaded_skills == set()

        # Test with directory paths
        manager = SkillsManager(["/tmp/test"])
        assert len(manager.directory_paths) == 1
        assert isinstance(manager.directory_paths[0], Path)
        assert manager._loaded_skills == set()

        # Test with include/exclude lists
        manager = SkillsManager(
            ["/tmp/test"],
            include_list=["skill1", "skill2"],
            exclude_list=["skill3"],
            git_root="/tmp",
        )
        assert manager.include_list == {"skill1", "skill2"}
        assert manager.exclude_list == {"skill3"}
        assert manager.git_root == Path("/tmp").expanduser().resolve()
        assert manager._loaded_skills == set()

    def test_create_and_parse_skill(self):
        """Test creating a skill and parsing its metadata."""
        # Create a skill directory structure
        skill_dir = Path(self.temp_dir) / "test-skill"
        skill_dir.mkdir()

        # Create SKILL.md with proper format
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

These are the main instructions.
""")

        # Create references directory
        ref_dir = skill_dir / "references"
        ref_dir.mkdir()
        (ref_dir / "api.md").write_text("# API Documentation")

        # Create scripts directory
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "setup.sh").write_text("#!/bin/bash\necho 'Setup script'")

        # Create assets directory
        assets_dir = skill_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "icon.png").write_bytes(b"fake_png_data")

        # Test loading the complete skill
        manager = SkillsManager([self.temp_dir])
        skill_content = manager.get_skill_content("test-skill")

        assert skill_content is not None
        assert skill_content.metadata.name == "test-skill"
        assert skill_content.metadata.description == "A test skill"
        assert skill_content.instructions == "# Test Skill\n\nThese are the main instructions."

        # Check references - should be Path objects
        assert len(skill_content.references) == 1
        assert "api.md" in skill_content.references
        assert isinstance(skill_content.references["api.md"], Path)
        assert skill_content.references["api.md"].name == "api.md"

        # Check scripts - should be Path objects
        assert len(skill_content.scripts) == 1
        assert "setup.sh" in skill_content.scripts
        assert isinstance(skill_content.scripts["setup.sh"], Path)
        assert skill_content.scripts["setup.sh"].name == "setup.sh"

        # Check assets - should be Path objects
        assert len(skill_content.assets) == 1
        assert "icon.png" in skill_content.assets
        assert isinstance(skill_content.assets["icon.png"], Path)
        assert skill_content.assets["icon.png"].name == "icon.png"

        # Test that skill was NOT added to _loaded_skills (only load_skill() does that)
        assert "test-skill" not in manager._loaded_skills
        assert manager._loaded_skills == set()

    def test_skill_summary_loader(self):
        """Test the skill_summary_loader function."""
        # Create a skill directory structure
        skill_dir = Path(self.temp_dir) / "test-skill"
        skill_dir.mkdir()

        # Create SKILL.md
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill for validation
---

# Test Skill

Test content.
""")
        # Test the skill summary loader (class method)
        summary = SkillsManager.skill_summary_loader([self.temp_dir])

        # Check that the summary contains expected information
        assert "Found 1 skill(s)" in summary
        assert "Skill: test-skill" in summary
        assert "Description: A test skill for validation" in summary

        # Test with include list
        summary = SkillsManager.skill_summary_loader([self.temp_dir], include_list=["test-skill"])
        assert "Found 1 skill(s)" in summary

        # Test with exclude list
        summary = SkillsManager.skill_summary_loader([self.temp_dir], exclude_list=["test-skill"])
        assert "No skills found" in summary

    def test_resolve_skill_directories(self):
        """Test the resolve_skill_directories function."""
        # Test with absolute path
        paths = SkillsManager.resolve_skill_directories([self.temp_dir])
        assert len(paths) == 1
        assert paths[0] == Path(self.temp_dir).resolve()

        # Test with relative path and git root
        paths = SkillsManager.resolve_skill_directories(["./test-dir"], git_root=self.temp_dir)
        # Should not resolve because directory doesn't exist
        assert len(paths) == 0

        # Create the directory and test again
        test_dir = Path(self.temp_dir) / "test-dir"
        test_dir.mkdir()
        paths = SkillsManager.resolve_skill_directories(["./test-dir"], git_root=self.temp_dir)
        assert len(paths) == 1
        assert paths[0] == test_dir.resolve()

        # Test with non-existent path
        paths = SkillsManager.resolve_skill_directories(["/non-existent/path"])
        assert len(paths) == 0

    def test_remove_skill(self):
        """Test the remove_skill instance method."""
        # Create a skill directory structure
        skill_dir = Path(self.temp_dir) / "test-skill"
        skill_dir.mkdir()

        # Create SKILL.md
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

Test content.
""")

        # Create a mock coder with agent mode
        mock_coder = MagicMock()
        mock_coder.edit_format = "agent"
        mock_coder.skills_includelist = []
        mock_coder.skills_excludelist = []

        # Create skills manager with coder reference
        manager = SkillsManager([self.temp_dir], coder=mock_coder)

        # First add the skill
        result = manager.load_skill("test-skill")
        assert "Skill 'test-skill' loaded successfully" in result
        assert "test-skill" in manager._loaded_skills

        # Test removing a skill that exists
        result = manager.remove_skill("test-skill")
        assert result == "Skill 'test-skill' removed successfully."
        assert "test-skill" not in manager._loaded_skills

        # Test removing the same skill again (should say not loaded)
        result = manager.remove_skill("test-skill")
        assert result == "Skill 'test-skill' is not loaded."

        # Test removing a skill not in include list (but not loaded)
        mock_coder2 = MagicMock()
        mock_coder2.edit_format = "agent"
        mock_coder2.skills_includelist = []
        mock_coder2.skills_excludelist = []

        manager2 = SkillsManager([self.temp_dir], coder=mock_coder2)
        result = manager2.remove_skill("test-skill")
        assert result == "Skill 'test-skill' is not loaded."

        # Test without coder reference
        manager_no_coder = SkillsManager([self.temp_dir])
        result = manager_no_coder.remove_skill("test-skill")
        assert result == "Error: Skills manager not connected to a coder instance."

        # Test not in agent mode
        mock_coder3 = MagicMock()
        mock_coder3.edit_format = "other-mode"
        mock_coder3.skills_includelist = ["test-skill"]
        mock_coder3.skills_excludelist = []

        manager3 = SkillsManager([self.temp_dir], coder=mock_coder3)
        result = manager3.remove_skill("test-skill")
        assert result == "Error: Skill removal is only available in agent mode."

        # Test with empty skill name
        mock_coder4 = MagicMock()
        mock_coder4.edit_format = "agent"
        mock_coder4.skills_includelist = []
        mock_coder4.skills_excludelist = []

        manager4 = SkillsManager([self.temp_dir], coder=mock_coder4)
        result = manager4.remove_skill("")
        assert result == "Error: Skill name is required."

    def test_load_skill(self):
        """Test the add_skill instance method."""
        # Create a skill directory structure
        skill_dir = Path(self.temp_dir) / "test-skill"
        skill_dir.mkdir()

        # Create SKILL.md
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

Test content.
""")

        # Create a mock coder with agent mode
        mock_coder = MagicMock()
        mock_coder.edit_format = "agent"
        mock_coder.skills_includelist = []
        mock_coder.skills_excludelist = []

        # Create skills manager with coder reference
        manager = SkillsManager([self.temp_dir], coder=mock_coder)

        # Test adding a skill that exists
        result = manager.load_skill("test-skill")
        assert "Skill 'test-skill' loaded successfully" in result
        assert "test-skill" in manager._loaded_skills

        # Test adding the same skill again (should say already loaded)
        result = manager.load_skill("test-skill")
        assert "Skill 'test-skill' is already loaded" in result

        # Test adding a non-existent skill
        result = manager.load_skill("non-existent-skill")
        assert "Error: Skill 'non-existent-skill' not found in configured directories." in result
        assert "non-existent-skill" not in manager._loaded_skills

        # Test with skill in exclude list (should still work since add_skill doesn't check exclude list)
        mock_coder2 = MagicMock()
        mock_coder2.edit_format = "agent"
        mock_coder2.skills_includelist = []
        mock_coder2.skills_excludelist = ["test-skill"]

        manager2 = SkillsManager([self.temp_dir], coder=mock_coder2)
        result = manager2.load_skill("test-skill")
        assert "Skill 'test-skill' loaded successfully" in result
        assert "test-skill" in manager2._loaded_skills

        # Test without coder reference
        manager_no_coder = SkillsManager([self.temp_dir])
        result = manager_no_coder.load_skill("test-skill")
        assert result == "Error: Skills manager not connected to a coder instance."

        # Test not in agent mode
        mock_coder3 = MagicMock()
        mock_coder3.edit_format = "other-mode"
        mock_coder3.skills_includelist = []
        mock_coder3.skills_excludelist = []

        manager3 = SkillsManager([self.temp_dir], coder=mock_coder3)
        result = manager3.load_skill("test-skill")
        assert result == "Error: Skill loading is only available in agent mode."

    def test_get_skill_content_does_not_add_to_loaded_skills(self):
        """Test that get_skill_content() does NOT add to _loaded_skills."""
        # Create two skill directory structures
        skill_dir1 = Path(self.temp_dir) / "skill1"
        skill_dir1.mkdir()
        skill_md1 = skill_dir1 / "SKILL.md"
        skill_md1.write_text("""---
name: skill1
description: First test skill
---

# Skill 1

Test content.
""")

        skill_dir2 = Path(self.temp_dir) / "skill2"
        skill_dir2.mkdir()
        skill_md2 = skill_dir2 / "SKILL.md"
        skill_md2.write_text("""---
name: skill2
description: Second test skill
---

# Skill 2

Test content.
""")

        # Create skills manager
        manager = SkillsManager([self.temp_dir])

        # Test initial state
        assert manager._loaded_skills == set()

        # Get first skill content
        skill1 = manager.get_skill_content("skill1")
        assert skill1 is not None
        assert manager._loaded_skills == set()  # Should NOT be added

        # Get second skill content
        skill2 = manager.get_skill_content("skill2")
        assert skill2 is not None
        assert manager._loaded_skills == set()  # Should NOT be added

        # Get non-existent skill (should not add to _loaded_skills)
        skill3 = manager.get_skill_content("nonexistent")
        assert skill3 is None
        assert manager._loaded_skills == set()

        # Get same skill again (should not add to _loaded_skills)
        skill1_again = manager.get_skill_content("skill1")
        assert skill1_again is not None
        assert manager._loaded_skills == set()

    def test_get_skills_content_only_returns_loaded_skills(self):
        """Test that get_skills_content() only returns skills in _loaded_skills."""
        # Create two skill directory structures
        skill_dir1 = Path(self.temp_dir) / "skill1"
        skill_dir1.mkdir()
        skill_md1 = skill_dir1 / "SKILL.md"
        skill_md1.write_text("""---
name: skill1
description: First test skill
---

# Skill 1

Test content.
""")

        skill_dir2 = Path(self.temp_dir) / "skill2"
        skill_dir2.mkdir()
        skill_md2 = skill_dir2 / "SKILL.md"
        skill_md2.write_text("""---
name: skill2
description: Second test skill
---

# Skill 2

Test content.
""")

        # Create skills manager
        manager = SkillsManager([self.temp_dir])

        # Test with no loaded skills
        content = manager.get_skills_content()
        assert content is None

        # Load only skill1 via load_skill() (requires mock coder)
        mock_coder = MagicMock()
        mock_coder.edit_format = "agent"
        mock_coder.skills_includelist = []
        mock_coder.skills_excludelist = []
        manager.coder = mock_coder

        result = manager.load_skill("skill1")
        assert "Skill 'skill1' loaded successfully" in result
        content = manager.get_skills_content()
        assert content is not None
        assert "skill1" in content
        assert "skill2" not in content

        # Load skill2 as well
        result = manager.load_skill("skill2")
        assert "Skill 'skill2' loaded successfully" in result
        content = manager.get_skills_content()
        assert content is not None
        assert "skill1" in content
        assert "skill2" in content

    def test_add_skill_updates_loaded_skills(self):
        """Test that load_skill() updates _loaded_skills."""
        # Create a skill directory structure
        skill_dir = Path(self.temp_dir) / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

Test content.
""")

        # Create a mock coder with agent mode
        mock_coder = MagicMock()
        mock_coder.edit_format = "agent"
        mock_coder.skills_includelist = []
        mock_coder.skills_excludelist = []

        # Create skills manager
        manager = SkillsManager([self.temp_dir], coder=mock_coder)

        # Test initial state
        assert manager._loaded_skills == set()

        # Add skill via load_skill() (simulating /load-skill command)
        result = manager.load_skill("test-skill")
        assert "Skill 'test-skill' loaded successfully" in result
        assert "test-skill" in manager._loaded_skills

        # Test get_skills_content returns the skill
        content = manager.get_skills_content()
        assert content is not None
        assert "test-skill" in content

    def test_remove_skill_updates_loaded_skills(self):
        """Test that remove_skill() updates _loaded_skills."""
        # Create a skill directory structure
        skill_dir = Path(self.temp_dir) / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

Test content.
""")

        # Create a mock coder with agent mode
        mock_coder = MagicMock()
        mock_coder.edit_format = "agent"
        mock_coder.skills_includelist = []
        mock_coder.skills_excludelist = []

        # Create skills manager and load the skill first via load_skill()
        manager = SkillsManager([self.temp_dir], coder=mock_coder)
        result = manager.load_skill("test-skill")
        assert "Skill 'test-skill' loaded successfully" in result
        assert "test-skill" in manager._loaded_skills

        # Remove the skill
        result = manager.remove_skill("test-skill")
        assert result == "Skill 'test-skill' removed successfully."
        assert "test-skill" not in manager._loaded_skills

        # Test get_skills_content returns None
        content = manager.get_skills_content()
        assert content is None

    def test_skill_not_loaded_when_get_skill_content_fails(self):
        """Test that skill is not added to _loaded_skills when get_skill_content() fails."""
        # Create a skill directory structure with invalid SKILL.md (no frontmatter)
        skill_dir = Path(self.temp_dir) / "invalid-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""# Invalid Skill

No frontmatter, so get_skill_content() should fail.
""")

        # Create skills manager
        manager = SkillsManager([self.temp_dir])

        # Try to get invalid skill content
        skill = manager.get_skill_content("invalid-skill")
        assert skill is None
        assert manager._loaded_skills == set()

        # Test get_skills_content returns None
        content = manager.get_skills_content()
        assert content is None
