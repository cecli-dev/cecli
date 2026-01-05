# Custom System Prompts

Cecli allows you to create and use custom system prompts to tailor the AI's behavior for specific use cases. Custom system prompts are YAML files that can override or extend the default system prompts used by cecli.

## How Custom System Prompts Work

### Prompt Inheritance System

Cecli uses a flexible prompt inheritance system that allows you to customize prompts:

- **Base Prompts**: Default prompts built into cecli
- **Custom Prompts**: User-defined prompts loaded from specified files
- **Prompt Mapping**: Map specific prompt types to custom YAML files

### Configuration

Custom system prompts can be configured using the `prompt_map` configuration option in your YAML configuration file:

```yaml
custom:
    prompt_map:
      agent: .cecli/custom/prompts/agent.yml
      base: .cecli/custom/prompts/base.yml
      all: .cecli/custom/prompts/all.yml
```

The `prompt_map` configuration option allows you to specify which custom prompt files to use for different prompt types.

The `prompt_map` can include:
- **Base Prompts**: Custom base prompts that apply to all interactions
- **All Prompts**: A special `all` key can be used to override all prompts used across the cecli modes (e.g. `/agent`, `/ask`, `architect`, `code`, etc.)
- **Other Prompt Types**: Any prompt type supported by cecli

When cecli starts, it:
1. **Parses configuration**: Reads `prompt_map` from config files
2. **Loads prompt files**: Loads the specified YAML files
3. **Merges prompts**: Custom prompts inherit from and override base prompts
4. **Applies prompts**: Uses the customized prompts for AI interactions

### Creating Custom System Prompts

Custom system prompts are created by writing YAML files that follow this structure:

```yaml
# Custom prompt file - inherits from base.yaml
_inherits: [base]

main_system: |
  <context name="role_and_directives">
  ## Core Directives
  - **Role**: Act as an expert software engineer.
  - **Act Proactively**: Autonomously use file discovery and context management tools to gather information and fulfill the user's request.
  - **Be Decisive**: Trust that your initial findings are valid.
  - **Be Concise**: Keep all responses brief and direct (1-3 sentences).
  - **Be Careful**: Break updates down into smaller, more manageable chunks.
  </context>
  Always reply to the user in spanish please.
```

### Important Features

1. **Inheritance**: Use `_inherits` to specify which base prompts to inherit from
2. **Overrides**: Define specific prompt sections to override base prompts
3. **Multiline Strings**: Use `|` for multiline prompt content
4. **Context Blocks**: Organize prompts with named context sections

### Example: Custom Agent Prompt

Here's a complete example of a custom agent prompt that changes the language and adds specific directives:

```yaml
# .cecli/custom/prompts/agent.yml
# Agent prompts - inherits from base.yaml
# Overrides specific prompts
_inherits: [agent, base]

main_system: |
  <context name="role_and_directives">
  ## Core Directives
  - **Role**: Act as an expert software engineer.
  - **Act Proactively**: Autonomously use file discovery and context management tools (`ViewFilesAtGlob`, `ViewFilesMatching`, `Ls`, `ContextManager`) to gather information and fulfill the user's request. Chain tool calls across multiple turns to continue exploration.
  - **Be Decisive**: Trust that your initial findings are valid. Refrain from asking the same question or searching for the same term in multiple similar ways.
  - **Be Concise**: Keep all responses brief and direct (1-3 sentences). Avoid preamble, postamble, and unnecessary explanations. Do not repeat yourself.
  - **Be Careful**: Break updates down into smaller, more manageable chunks. Focus on one thing at a time.
  </context>
  Always reply to the user in spanish please.
```

### Complete Configuration Example

Complete configuration example in YAML configuration file (`.cecli.conf.yml` or `~/.cecli.conf.yml`):

```yaml
# Model configuration
model: gemini/gemini-3-pro-preview
weak-model: gemini/gemini-3-flash-preview

# Custom prompts configuration
custom:
    prompt_map:
      agent: .cecli/custom/prompts/agent.yml
      base: .cecli/custom/prompts/my-base.yml

# Custom commands configuration
custom:
    command-paths: [".cecli/custom/commands/"]

# Other cecli options
agent: true
auto-commits: false
auto-save: true
```

### Best Practices

1. **Start simple**: Begin by overriding just one prompt section
2. **Use inheritance**: Leverage the `_inherits` feature to build on existing prompts
3. **Test prompts**: Verify prompts work as expected before adding to production config
4. **Version control**: Keep custom prompts in version control alongside your project
5. **Document changes**: Add comments to explain why specific prompts were customized

### Integration with Other Features

Custom system prompts work seamlessly with other cecli features:

- **Agent Mode**: Custom prompts can tailor agent behavior
- **Model selection**: Prompts work with any model
- **Custom commands**: Can be used alongside custom commands

### Benefits

- **Customization**: Tailor AI behavior to your specific workflow
- **Consistency**: Ensure the AI follows your preferred patterns
- **Specialization**: Create prompts optimized for specific tasks (code review, documentation, etc.)
- **Team alignment**: Share custom prompts across team members for consistent results

### Available Prompt Types

Cecli supports several prompt types that can be customized:

- **agent**: Prompts for agent mode operations
- **base**: Base prompts that apply to all interactions
- **chat**: Prompts for standard chat interactions
- **edit**: Prompts for code editing tasks

### Prompt Structure

Custom prompt files support the following structure:

```yaml
_inherits: [base, agent]  # Optional: inherit from other prompts

# Main system prompt (required for some prompt types)
main_system: |
  Your custom system prompt here...

# ...other message blocks to override
```

For the full listing of possible override targets, you really have to just read the code in the `cecli/prompts/` directory homeboy, good luck

Custom system prompts provide a powerful way to tailor cecli's AI interactions, allowing you to create specialized behavior for your specific needs while maintaining the core functionality.