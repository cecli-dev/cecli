---
parent: Configuration
nav_order: 35
description: Extend AI capabilities with custom instructions, reference materials, scripts, and assets through the skills system.
---

# Skills

Agent Mode includes a powerful skills system that allows you to extend the AI's capabilities with custom instructions, reference materials, scripts, and assets. Skills are organized collections of knowledge and tools that help the AI perform specific tasks more effectively.

## Skill Directory Structure

Skills follow a standardized directory structure:

```
skill-name/
├── SKILL.md              # Main skill definition with YAML frontmatter and instructions
├── references/           # Reference materials (markdown files)
│   └── example-api.md           # API documentation
│   └── example-guide.md         # Usage guide
├── scripts/             # Executable scripts
│   └── example-setup.sh         # Setup script
│   └── example-deploy.py        # Deployment script
├── assets/              # Binary assets (images, config files, etc.)
│   └── example-diagram.png      # Architecture diagram
│   └── example-config.json      # Configuration file
└── evals/
    └── evals.json        # Evaluation tests
```

## SKILL\.md Format

The `SKILL.md` file contains YAML frontmatter followed by markdown instructions:

```yaml
---
name: python-refactoring
description: Tools and techniques for Python code refactoring
license: MIT
metadata:
  version: 1.0.0
  author: AI Team
  tags: [python, refactoring, code-quality]
---

# Python Refactoring Skill

This skill provides tools and techniques for refactoring Python code...

## Common Refactoring Patterns

1. **Extract Method** - Break down large functions...
2. **Rename Variable** - Improve code readability...
3. **Simplify Conditionals** - Reduce complexity...

## Usage Examples

```python
# Before refactoring
def process_data(data):
    # Complex logic here
    pass

# After refactoring  
def process_data(data):
    validate_input(data)
    cleaned = clean_data(data)
    result = analyze_data(cleaned)
    return result
```

## Skill Configuration

Skills are configured through the `agent-config` parameter in the YAML configuration file. The following options are available:

- **`skills_paths`**: Array of directory paths to search for skills
- **`skills_includelist`**: Array of skill names to include (whitelist)
- **`skills_excludelist`**: Array of skill names to exclude (blacklist)

> **Duplicate skill names**: When the same skill name is found in more than
> one configured directory, only one copy is loaded. Directories are scanned
> in priority order: local project directories (e.g. `./.cecli/skills`) first,
> then other configured directories in the order they are listed, with home
> directories (e.g. `~/skills` and the implicit `~/.cecli/skills` default)
> last. If no `skills_paths` are configured, the only directory searched is
> `~/.cecli/skills`.

Complete configuration example in YAML configuration file (`.cecli.conf.yml` or `~/.cecli.conf.yml`):

```yaml
# Enable Agent Mode
agent: true

# Agent Mode configuration
agent-config: |
  {
    # Skills configuration
    "skills_paths": ["~/my-skills", "./project-skills"],  # Directories to search for skills
    "skills_includelist": ["python-refactoring", "react-components"],  # Optional: Whitelist of skills to include
    "skills_excludelist": ["legacy-tools"],  # Optional: Blacklist of skills to exclude
    
    # Other Agent Mode settings
    ...
  }
```

## Creating Custom Skills

To create a custom skill:

1. Create a skill directory with the skill name
2. Add `SKILL.md` with YAML frontmatter and instructions
3. Add reference materials in `references/` directory
4. Add executable scripts in `scripts/` directory
5. Add binary assets in `assets/` directory
6. Add evaluation tests in `evals/` directory to test skill performance
7. Test the skill by adding it to your configuration file:

## Best Practices for Skills

1. **Keep skills focused**: Each skill should address a specific domain or task
2. **Provide clear instructions**: Write comprehensive, well-structured documentation
3. **Include examples**: Show practical usage examples
4. **Test scripts**: Ensure scripts work correctly and handle errors
5. **Version skills**: Use metadata to track skill versions
6. **License appropriately**: Specify licenses for reusable skills
7. **Organize references**: Structure reference materials logically

## Skills in Action

With skills enabled, the LLM can:
- Reference specific techniques from skill instructions
- Use provided scripts to automate tasks
- Consult reference materials for API details
- Follow established patterns and best practices
- Combine multiple skills for complex tasks

Skills transform Agent Mode from a general-purpose coding assistant into a domain-specific expert with access to curated knowledge and tools.
