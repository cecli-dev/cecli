# TUI Mode

TUI (Textual User Interface) Mode provides a modern, visually rich terminal interface for AI pair programming.

## Activation

Command line:
```
cecli ... --tui

### OR!

cecli ... --tui
```

## Configuration

TUI Mode can be configured directly in the relevant config.json file or with JSON in the command line arguments:

### Minimal Configuration

```yaml
tui: true
```

### Complete Configuration Example

Complete configuration example in YAML configuration file (`.aider.conf.yml` or `~/.aider.conf.yml`). The base theme is pretty nice but if you want different colors and key bindings, do you thing:

```yaml
tui: true
tui-config:
  colors:
    primary: "#00ff5f"
    secondary: "#888888"
    accent: "#00ff87"
    foreground: "#ffffff"
    background: "#1e1e1e"
    success: "#00aa00"
    warning: "#ffd700"
    error: "#ff3333"
    surface: "transparent"
    panel: "transparent"
    input-cursor-foreground: "#00ff87"
  other:
    dark: true
    input-cursor-text-style: "underline"
  key_bindings:
    newline: "enter"
    submit: "shift+enter"
    completion: "tab"
    stop: "escape"
    cycle_forward: "tab"
    cycle_backward: "shift+tab"
    focus: "ctrl+f"
    cancel: "ctrl+c"
    clear: "ctrl+l"
    quit: "ctrl+q"

```

### Key Command Configuration

The TUI provides customizable key bindings for all major actions. The default key bindings are:

| Action | Default Key | Description |
|--------|-------------|-------------|
| New Line | `enter` (multiline mode) / `shift+enter` (single-line mode) | Insert a new line in the input area |
| Submit | `shift+enter` (multiline mode) / `enter` (single-line mode) | Submit the current input |
| Cancel | `ctrl+c` | Stop and stash current input prompt |
| Stop | `escape` | Interrupt the current LLM response or task |
| Cycle Forward | `tab` | Cycle forward through completion suggestions |
| Cycle Backward | `shift+tab` | Cycle backward through completion suggestions |
| Focus | `ctrl+f` | Focus the input area |
| Clear | `ctrl+l` | Clear the output area |
| Quit | `ctrl+q` | Exit the TUI |

#### Customizing Key Bindings

You can customize any key binding by adding a `key_bindings` section to your `tui-config`. For example, to change the quit key to `ctrl+x`:

```yaml
tui-config:
  key_bindings:
    quit: "ctrl+x"
```

All key bindings use Textual's key syntax:
- Single keys: `enter`, `escape`, `tab`
- Modifier combinations: `ctrl+c`, `shift+enter`, etc.

## Benefits

- **Improved Productivity**: Reduced context switching with all information visible at once
- **Better Organization**: Clear separation of concerns between input, output, and status
- **Enhanced Readability**: Proper formatting and syntax highlighting for code discussions
- **Real-time Feedback**: Immediate visual feedback for all operations
- **Modern Interface**: Familiar UI patterns that reduce cognitive load
- **Accessibility**: Full keyboard navigation without requiring mouse interaction

## Integration with Other Modes

TUI Mode works seamlessly with other cecli features:

- **Agent Mode**: Visual feedback for tool calls and autonomous operations
- **Skills**: Clean display of skill outputs and interactions
- **MCP Servers**: Integrated display of MCP tool outputs
- **Git Operations**: Real-time git status updates in the footer

## Troubleshooting

### Common Issues

1. **TUI not starting**: Ensure your terminal supports True Color (24-bit color)
2. **Display issues**: Try resizing your terminal window
3. **Performance problems**: Reduce terminal refresh rate or disable animations
4. **Input lag**: Check for conflicts with terminal multiplexers (tmux, screen)

### Terminal Requirements

- **True Color Support**: Required for proper color rendering
- **Minimum Size**: 80x24 terminal size recommended
- **Unicode Support**: Required for proper symbol display
- **Modern Terminal**: Recommended: Kitty, WezTerm, iTerm2, or Windows Terminal

TUI Mode represents a significant evolution in cecli's user experience, providing a modern, efficient interface for AI pair programming while maintaining the power and flexibility of the command-line foundation. Ideally, this mode makes ai-enabled programming more colorful and more fun for us all!