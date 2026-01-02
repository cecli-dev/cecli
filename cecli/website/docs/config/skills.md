# Skills System

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
└── assets/              # Binary assets (images, config files, etc.)
    └── example-diagram.png      # Architecture diagram
    └── example-config.json      # Configuration file
```

## SKILL.md Format

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
```

## Skill Configuration

Skills are configured through the `agent-config` parameter in the YAML configuration file. The following options are available:

- **`skills_paths`**: Array of directory paths to search for skills
- **`skills_includelist`**: Array of skill names to include (whitelist)
- **`skills_excludelist`**: Array of skill names to exclude (blacklist)

Complete configuration example in YAML configuration file (`.aider.conf.yml` or `~/.aider.conf.yml`):

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
    "large_file_token_threshold": 12500,  # Token threshold for large file warnings
    "skip_cli_confirmations": false,  # YOLO mode - be brave and let the LLM cook
    "tools_includelist": ["view", "makeeditable", "replacetext", "finished"],  # Optional: Whitelist of tools
    "tools_excludelist": ["command", "commandinteractive"],  # Optional: Blacklist of tools
    "include_context_blocks": ["todo_list", "git_status"],  # Optional: Context blocks to include
    "exclude_context_blocks": ["symbol_outline", "directory_structure"]  # Optional: Context blocks to exclude
  }
```

## Creating Custom Skills

To create a custom skill:

1. Create a skill directory with the skill name
2. Add `SKILL.md` with YAML frontmatter and instructions
3. Add reference materials in `references/` directory
4. Add executable scripts in `scripts/` directory  
5. Add binary assets in `assets/` directory
6. Test the skill by adding it to your configuration file:

Example skill creation:
```bash
mkdir -p ~/skills/my-custom-skill/{references,scripts,assets}

cat > ~/skills/my-custom-skill/SKILL.md << 'EOF'
---
name: my-custom-skill
description: My custom skill for specific tasks
license: MIT
metadata:
  version: 1.0.0
  author: Your Name
---

# My Custom Skill

This skill helps with...

## Features
- Feature 1
- Feature 2

## Usage
1. Step 1
2. Step 2
EOF

# Add a reference
cat > ~/skills/my-custom-skill/references/api.md << 'EOF'
# API Reference

## Endpoints
- GET /api/data
- POST /api/process
EOF

# Add a script  
cat > ~/skills/my-custom-skill/scripts/setup.sh << 'EOF'
#!/bin/bash
echo "Setting up my custom skill..."
# Setup commands here
EOF
chmod +x ~/skills/my-custom-skill/scripts/setup.sh
```

## Best Practices for Skills

1. **Keep skills focused**: Each skill should address a specific domain or task
2. **Provide clear instructions**: Write comprehensive, well-structured documentation
3. **Include examples**: Show practical usage examples
4. **Test scripts**: Ensure scripts work correctly and handle errors
5. **Version skills**: Use metadata to track skill versions
6. **License appropriately**: Specify licenses for reusable skills
7. **Organize references**: Structure reference materials logically

## Skills in Action

With skills enabled, the AI can:
- Reference specific techniques from skill instructions
- Use provided scripts to automate tasks
- Consult reference materials for API details
- Follow established patterns and best practices
- Combine multiple skills for complex tasks

Skills transform Agent Mode from a general-purpose coding assistant into a domain-specific expert with access to curated knowledge and tools.
