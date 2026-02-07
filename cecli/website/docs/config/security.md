# Security Configuration

Security Configuration in cecli provides a framework for controlling access to external resources and implementing security policies. The initial implementation includes website whitelisting for URL access control, with the architecture designed to support additional security features in the future.

## Overview

The security configuration system allows you to define security policies that control how cecli interacts with external resources. The first component of this system is website whitelisting, which controls which domains can be accessed when URLs are detected in AI responses or user input.

This feature helps prevent accidental or unauthorized access to external websites while providing a foundation for future security enhancements.

## Usage

Security Configuration can be activated in the following ways:

In the command line:

```
cecli ... --security-config '{"allowed-domains": ["github.com", "example.com"]}'
```

In the configuration files:

```yaml
security-config:
  allowed-domains:
    - github.com
    - example.com
```

## Security Settings Format

The security configuration accepts a JSON object that can contain multiple security policies. The initial implementation includes website whitelisting, with the architecture designed to support additional security features in future releases.

### `allowed-domains` (array of strings, optional)

**Website Whitelisting** - This is the first security policy implemented in the security configuration system. It controls which domains can be accessed when URLs are detected:

A list of domains that are allowed to be accessed. When this property is set:

- **If empty or not provided**: All domains are allowed (default behavior)
- **If provided**: Only domains matching the list are allowed

Domain matching supports:
- **Exact matches**: `"github.com"` matches exactly `github.com`
- **Subdomain matches**: `"github.com"` also matches `api.github.com`, `docs.github.com`, etc.
- **Case-insensitive**: Matching is case-insensitive

### Example Configuration

```json
{
  "allowed-domains": [
    "github.com",
    "docs.python.org",
    "stackoverflow.com"
  ]
}
```

## How It Works

When cecli detects URLs in AI responses or user input, it checks the security configuration before offering to open them in a browser:

1. **URL analysis**: The domain is extracted from any detected URLs
2. **Policy enforcement**: The domain is checked against the configured `allowed-domains` list
3. **Access decision**:
   - If no `allowed-domains` are configured → All domains are allowed
   - If domain matches an allowed domain → URL access is permitted
   - If domain doesn't match any allowed domain → URL access is blocked

This provides a simple yet effective way to control which external websites can be accessed during development sessions.

## Configuration Examples

### Command Line Examples

Allow only GitHub domains:

```bash
cecli --security-config '{"allowed-domains": ["github.com"]}'
```

Allow multiple trusted domains:

```bash
cecli --security-config '{"allowed-domains": ["github.com", "docs.python.org", "pypi.org"]}'
```

### YAML Configuration File Examples

In `.aider.conf.yml` or `~/.aider.conf.yml`:

```yaml
# Restrict to GitHub and Python documentation
security-config:
  allowed-domains:
    - github.com
    - docs.python.org
    - pypi.org
```

More comprehensive configuration:

```yaml
# Complete configuration with security settings
model: claude-3-5-sonnet-20241022
security-config:
  allowed-domains:
    - github.com
    - gitlab.com
    - bitbucket.org
    - docs.python.org
    - stackoverflow.com
    - pypi.org
```

## Use Cases

### 1. Enterprise Security

In corporate environments where access to external resources needs to be controlled:

```yaml
security-config:
  allowed-domains:
    - internal-git.company.com
    - docs.internal.company.com
    - approved-external.com
```

### 2. Educational Settings

For classroom or training environments where you want to limit distractions:

```yaml
security-config:
  allowed-domains:
    - github.com
    - docs.python.org
    - w3schools.com
```

### 3. Personal Productivity

Limit access to only essential development resources:

```yaml
security-config:
  allowed-domains:
    - github.com
    - stackoverflow.com
    - pypi.org
    - npmjs.com
```

## Integration with Other Features

### Agent Mode Integration

When using Agent Mode, security configuration works alongside other security features:

```yaml
agent: true
agent-config:
  tools_excludelist: ["command", "commandinteractive"]
security-config:
  allowed-domains:
    - github.com
    - docs.python.org
```

### Custom Commands

Security configuration applies to all URL detection throughout cecli, including custom commands that might generate or process URLs.

## Best Practices

1. **Start with a permissive configuration**: Begin without restrictions and add domains as needed
2. **Use specific domains**: Prefer specific domains over wildcards for better security
3. **Regularly review**: Periodically review and update your allowed domains list
4. **Combine with other security measures**: Use security configuration alongside other cecli security features like tool restrictions in Agent Mode
5. **Test configuration**: Verify your configuration works as expected by testing with URLs from allowed and blocked domains

## Troubleshooting

### URLs Not Being Offered

If URLs are not being offered when expected:
1. Check that the domain is in your `allowed-domains` list
2. Verify the URL parsing is extracting the correct domain
3. Ensure the configuration is properly formatted as JSON/YAML

### Configuration Not Applied

If security configuration doesn't seem to be applied:
1. Check command line syntax for JSON escaping
2. Verify YAML indentation in configuration files
3. Ensure the `--security-config` argument is being passed correctly

## Future Extensibility

The security configuration system is designed to be extensible, with website whitelisting being just the first implemented security policy. The architecture supports adding additional security controls in future releases, such as:

- **File access controls**: Restrict which files or directories can be read/written
- **Network access controls**: Limit network connections to specific hosts or ports
- **Command execution controls**: Restrict which shell commands can be executed
- **Resource limits**: Set limits on memory, CPU, or other resource usage
- **Plugin security**: Control which plugins or extensions can be loaded

This modular approach allows cecli to implement a comprehensive security framework while maintaining backward compatibility with existing configurations.

## Related Documentation

- [Agent Mode Configuration](agent-mode.md) - For additional security controls in Agent Mode
- [Custom Commands](custom-commands.md) - For creating secure custom commands
- [Options Reference](options.md) - For complete configuration options

Security Configuration provides a simple yet effective way to control external resource access in cecli, helping to maintain security and focus during development sessions.