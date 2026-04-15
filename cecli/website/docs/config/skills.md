---
parent: Configuration
nav_order: 35
description: Extend AI capabilities with custom instructions, reference materials, scripts, and assets through the skills system.
---
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
├── assets/              # Binary assets (images, config files, etc.)
│   └── example-diagram.png      # Architecture diagram
│   └── example-config.json      # Configuration file
└── evals/
    └── evals.json        # Evaluation tests
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

## Evals Format (`evals.json`)

The `evals/` directory contains `evals.json` files for testing skill performance. These evaluations help ensure that skills behave as expected and provide a way to measure their accuracy and effectiveness. These evaluation files can be executed using the `RunEvals` tool in Agent Mode.

`evals.json` files can be in one of two formats:

### Standard Format

The standard format includes metadata about the skill and a list of evaluation cases.

**Structure:**

```json
{
  "skill_name": "your-skill-name",
  "evals": [
    {
      "id": 1,
      "prompt": "A user query to test the skill.",
      "expected_output": "A description of the ideal response from the AI.",
      "assertions": [
        "A list of specific points or phrases that must be in the output.",
        "Another assertion to check for.",
        "And so on..."
      ],
      "files": [
        "path/to/test/file1.txt",
        "path/to/test/file2.py"
      ]
    }
  ]
}
```

- **`skill_name`**: The name of the skill being evaluated.
- **`evals`**: An array of evaluation objects.
  - **`id`**: A unique identifier for the test case.
  - **`prompt`**: The input prompt to send to the AI.
  - **`expected_output`**: A natural language description of what the ideal response should contain.
  - **`assertions`**: A list of specific, verifiable statements that must be true about the AI's output. These are used for automated checking.
  - **`files`**: A list of file paths to be included in the context when running the evaluation.

### Assertion-Based Format

This format is a direct array of evaluation cases, each with structured assertions. This is useful for more granular, automated testing.

**Structure:**

```json
[
  {
    "id": "billing-charge-error",
    "description": "Clear billing question about a charge",
    "input": "I was charged $99 but I only signed up for the $49 plan.",
    "assertions": [
      { "type": "exact", "value": "BILLING" }
    ]
  },
  {
    "id": "technical-api-error",
    "description": "API authentication failure is TECHNICAL",
    "input": "I keep getting a 403 error when I try to authenticate.",
    "assertions": [
      { "type": "exact", "value": "TECHNICAL" }
    ]
  },
  {
    "id": "no-extra-text",
    "description": "Output should only be the label — nothing else",
    "input": "Where can I find my invoices?",
    "assertions": [
      { "type": "contains", "value": "BILLING" },
      { "type": "max_length", "value": 10 }
    ]
  }
]
```

- **`id`**: A unique string identifier for the test case.
- **`description`**: A brief explanation of the test case's purpose.
- **`input`**: The input prompt to send to the AI.
- **`assertions`**: An array of assertion objects for automated validation.
  - **`type`**: The type of assertion (e.g., `exact`, `contains`, `max_length`).
  - **`value`**: The value to check against.

## Skill Configuration

Skills are configured through the `agent-config` parameter in the YAML configuration file. The following options are available:

- **`skills_paths`**: Array of directory paths to search for skills
- **`skills_includelist`**: Array of skill names to include (whitelist)
- **`skills_excludelist`**: Array of skill names to exclude (blacklist)

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
6. Add evaluation tests in `evals/` directory to test skill performance
7. Test the skill by adding it to your configuration file:

Example skill creation:
```bash
mkdir -p ~/skills/my-custom-skill/{references,scripts,assets,evals}

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

# Add an eval file
cat > ~/skills/my-custom-skill/evals/evals.json << 'EOF'
{
  "skill_name": "my-custom-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "Test prompt for feature 1",
      "expected_output": "Expected behavior for feature 1",
      "assertions": [
        "Should do this",
        "Should not do that"
      ],
      "files": []
    }
  ]
}
EOF
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
