---
parent: Configuration
nav_order: 120
description: Configure Model Control Protocol (MCP) servers for enhanced AI capabilities.
---

# Model Control Protocol (MCP)

Model Control Protocol (MCP) servers extend cecli's capabilities by providing additional tools and functionality to the AI models. MCP servers can add features like git operations, context retrieval, and other specialized tools.

## Configuring MCP Servers

cecli supports configuring MCP servers using the MCP Server Configuration schema. Please
see the [Model Context Protocol documentation](https://modelcontextprotocol.io/introduction)
for more information.

You have two ways of sharing your MCP server configuration with cecli.

{: .note }

> Today, CECLI/Cecli supports connecting to MCP servers using stdio, http, and sse transports.

### Config Files

You can configure MCP servers in your `.aider.conf.yml` file using either JSON or YAML format:

#### JSON Configuration

```yaml
mcp-servers: |
  {
    "mcpServers": {
      "git": {
        "transport": "http",
        "url": "http://localhost:8000"
      }
    }
  }
```

#### YAML Configuration

```yaml
mcp-servers:
  mcpServers:
    context7:
      transport: http
      url: https://mcp.context7.com/mcp
    deepwiki:
      transport: http
      url: https://mcp.deepwiki.com/mcp
```

Or specify a configuration file:

```yaml
mcp-servers-file: /path/to/mcp.json
```

These options are configurable in any of cecli's config file formats.

Also, you are able to say if you would like an mcp enabled/disabled in the config itself via `"enabled"` key
By default MCP servers are enabled, so you MUST explicitly disable them in the config if you dont wish
for them to be included when cecli starts up

### Flags

You can specify MCP servers directly on the command line using the `--mcp-servers` option with a JSON or YAML string:

#### Using a JSON String

```bash
cecli --mcp-servers '{"mcpServers":{"git":{"transport":"http","url":"http://localhost:8000"}}}'
```

#### Using a YAML String

```bash
cecli --mcp-servers 'mcpServers:
  context7:
    transport: http
    url: https://mcp.context7.com/mcp
  deepwiki:
    transport: http
    url: https://mcp.deepwiki.com/mcp'
```

#### Using a configuration file

Alternatively, you can store your MCP server configurations in a JSON or YAML file and reference it with the `--mcp-servers-file` option:

```bash
cecli --mcp-servers-file mcp.json
```

#### Specifying the transport

You can use the `--mcp-transport` flag to specify the transport for all configured MCP servers that do not have a transport specified.

```bash
cecli --mcp-transport http
```

### Environment Variables

You can also configure MCP servers using environment variables in your `.env` file using JSON or YAML format:

```
CECLI_MCP_SERVERS={"mcpServers":{"git":{"transport": "stdio", "command":"uvx","args":["mcp-server-git"]}}}
```

Or specify a configuration file:

```
CECLI_MCP_SERVERS_FILE=/path/to/mcp.json
```

## Troubleshooting

If you encounter issues with MCP servers:

1. Use the `--verbose` flag to see detailed information about MCP server loading
2. Check that the specified executables are installed and available in your PATH
3. Verify that your JSON or YAML configuration is valid

For more information about specific MCP servers and their capabilities, refer to their respective documentation.

## Common MCP Servers

Here are some commonly used MCP servers that can enhance cecli's capabilities:

### Context7

Context7 MCP provides up-to-date, version-specific documentation and code examples directly from the source into your LLM prompts, eliminating outdated information and hallucinations. It offers a streamlined integration experience with built-in caching mechanisms and is optimized for explorative agentic workflows.

```yaml
mcp-servers:
  mcpServers:
    context7:
      transport: http
      url: https://mcp.context7.com/mcp
```

### DeepWiki

DeepWiki MCP is an unofficial server that crawls Deepwiki URLs, converts pages to Markdown, and returns them as a single document or a list. It features domain safety, HTML sanitization, and link rewriting to provide clean, structured documentation from Deepwiki repositories.

```yaml
mcp-servers:
  mcpServers:
    deepwiki:
      transport: http
      url: https://mcp.deepwiki.com/mcp
```

### Serena

Serena MCP provides LSP support for the current project, offering code analysis, symbol navigation, and project-specific tooling. It runs as a local stdio server and provides context-aware development assistance directly within the IDE environment.

```yaml
mcp-servers:
  mcpServers:
    serena:
      transport: stdio
      command: uvx
      args: [
        "--from",
        "git+https://github.com/oraios/serena",
        "serena",
        "start-mcp-server",
        "--context",
        "ide",
        "--project",
        "{project path}"
      ]
```

### Chrome DevTools

Chrome DevTools MCP provides browser automation and debugging capabilities through Chrome's DevTools Protocol, enabling web page interaction, network monitoring, and performance analysis. It connects to a running Chrome instance and offers tools for web development testing and automation. Note: the configuration below requires you to start chrome with remote debugging enabled before
starting the coding agent.

```yaml
mcp-servers:
  mcpServers:
    chrome-devtools:
      transport: stdio
      command: npx
      args: [
        "chrome-devtools-mcp@latest",
        "--browser-url",
        "http://127.0.0.1:9222"
      ]
```

### GitHub

GitHub MCP provides access to GitHub repositories, issues, pull requests, and other GitHub resources. It enables AI models to interact with GitHub data, read repository contents, and perform various GitHub operations. The server runs in a Docker container and requires a GitHub Personal Access Token for authentication.

```yaml
mcp-servers:
  mcpServers:
    github:
      transport: stdio
      command: "docker"
      args: [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN=<access_token>",
        "ghcr.io/github/github-mcp-server"
      ]
```
