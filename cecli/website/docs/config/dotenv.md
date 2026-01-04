---
parent: Configuration
nav_order: 20
description: Using a .env file to store LLM API keys for aider.
---

# Config with .env

You can use a `.env` file to store API keys and other settings for the
models you use with aider.
You can also set many general aider options
in the `.env` file.

Aider will look for a `.env` file in these locations:

- Your home directory.
- The root of your git repo.
- The current directory.
- As specified with the `--env-file <filename>` parameter.

If the files above exist, they will be loaded in that order. Files loaded last will take priority.

{% include keys.md %}

## Sample .env file

Below is a sample `.env` file, which you
can also
[download from GitHub](https://github.com/Aider-AI/aider/blob/main/aider/website/assets/sample.env).

<!--[[[cog
from aider.args import get_sample_dotenv
from pathlib import Path
text=get_sample_dotenv()
Path("aider/website/assets/sample.env").write_text(text)
cog.outl("```")
cog.out(text)
cog.outl("```")
]]]-->
```
##########################################################
# Sample aider .env file.
# Place at the root of your git repo.
# Or use `aider --env <fname>` to specify.
##########################################################

#################
# LLM parameters:
#
# Include xxx_API_KEY parameters and other params needed for your LLMs.
# See https://aider.chat/docs/llms.html for details.

## OpenAI
#OPENAI_API_KEY=

## Anthropic
#ANTHROPIC_API_KEY=

##...

#############
# Main model:

## Specify the model to use for the main chat
#CECLI_MODEL=

########################
# API Keys and settings:

## Specify the OpenAI API key
#CECLI_OPENAI_API_KEY=

## Specify the Anthropic API key
#CECLI_ANTHROPIC_API_KEY=

## Specify the api base url
#CECLI_OPENAI_API_BASE=

## (deprecated, use --set-env OPENAI_API_TYPE=<value>)
#CECLI_OPENAI_API_TYPE=

## (deprecated, use --set-env OPENAI_API_VERSION=<value>)
#CECLI_OPENAI_API_VERSION=

## (deprecated, use --set-env OPENAI_API_DEPLOYMENT_ID=<value>)
#CECLI_OPENAI_API_DEPLOYMENT_ID=

## (deprecated, use --set-env OPENAI_ORGANIZATION=<value>)
#CECLI_OPENAI_ORGANIZATION_ID=

## Set an environment variable (to control API settings, can be used multiple times)
#CECLI_SET_ENV=

## Set an API key for a provider (eg: --api-key provider=<key> sets PROVIDER_API_KEY=<key>)
#CECLI_API_KEY=

#################
# Model settings:

## List known models which match the (partial) MODEL name
#CECLI_LIST_MODELS=

## Specify a file with aider model settings for unknown models
#CECLI_MODEL_SETTINGS_FILE=.aider.model.settings.yml

## Specify a file with context window and costs for unknown models
#CECLI_MODEL_METADATA_FILE=.aider.model.metadata.json

## Add a model alias (can be used multiple times)
#CECLI_ALIAS=

## Set the reasoning_effort API parameter (default: not set)
#CECLI_REASONING_EFFORT=

## Set the thinking token budget for models that support it. Use 0 to disable. (default: not set)
#CECLI_THINKING_TOKENS=

## Verify the SSL cert when connecting to models (default: True)
#CECLI_VERIFY_SSL=true

## Timeout in seconds for API calls (default: None)
#CECLI_TIMEOUT=

## Specify what edit format the LLM should use (default depends on model)
#CECLI_EDIT_FORMAT=

## Use architect edit format for the main chat
#CECLI_ARCHITECT=

## Enable/disable automatic acceptance of architect changes (default: True)
#CECLI_AUTO_ACCEPT_ARCHITECT=true

## Specify the model to use for commit messages and chat history summarization (default depends on --model)
#CECLI_WEAK_MODEL=

## Specify the model to use for editor tasks (default depends on --model)
#CECLI_EDITOR_MODEL=

## Specify the edit format for the editor model (default: depends on editor model)
#CECLI_EDITOR_EDIT_FORMAT=

## Only work with models that have meta-data available (default: True)
#CECLI_SHOW_MODEL_WARNINGS=true

## Check if model accepts settings like reasoning_effort/thinking_tokens (default: True)
#CECLI_CHECK_MODEL_ACCEPTS_SETTINGS=true

## Soft limit on tokens for chat history, after which summarization begins. If unspecified, defaults to the model's max_chat_history_tokens.
#CECLI_MAX_CHAT_HISTORY_TOKENS=

#################
# Cache settings:

## Enable caching of prompts (default: False)
#CECLI_CACHE_PROMPTS=false

## Number of times to ping at 5min intervals to keep prompt cache warm (default: 0)
#CECLI_CACHE_KEEPALIVE_PINGS=false

###################
# Repomap settings:

## Suggested number of tokens to use for repo map, use 0 to disable
#CECLI_MAP_TOKENS=

## Control how often the repo map is refreshed. Options: auto, always, files, manual (default: auto)
#CECLI_MAP_REFRESH=auto

## Multiplier for map tokens when no files are specified (default: 2)
#CECLI_MAP_MULTIPLIER_NO_FILES=true

## Maximum line length for the repo map code. Prevents sending crazy long lines of minified JS files etc. (default: 100)
#CECLI_MAP_MAX_LINE_LENGTH=100

################
# History Files:

## Specify the chat input history file (default: .aider.input.history)
#CECLI_INPUT_HISTORY_FILE=.aider.input.history

## Specify the chat history file (default: .aider.chat.history.md)
#CECLI_CHAT_HISTORY_FILE=.aider.chat.history.md

## Restore the previous chat history messages (default: False)
#CECLI_RESTORE_CHAT_HISTORY=false

## Log the conversation with the LLM to this file (for example, .aider.llm.history)
#CECLI_LLM_HISTORY_FILE=

##################
# Output settings:

## Use colors suitable for a dark terminal background (default: False)
#CECLI_DARK_MODE=false

## Use colors suitable for a light terminal background (default: False)
#CECLI_LIGHT_MODE=false

## Enable/disable pretty, colorized output (default: True)
#CECLI_PRETTY=true

## Enable/disable streaming responses (default: True)
#CECLI_STREAM=true

## Set the color for user input (default: #00cc00)
#CECLI_USER_INPUT_COLOR=#00cc00

## Set the color for tool output (default: None)
#CECLI_TOOL_OUTPUT_COLOR=

## Set the color for tool error messages (default: #FF2222)
#CECLI_TOOL_ERROR_COLOR=#FF2222

## Set the color for tool warning messages (default: #FFA500)
#CECLI_TOOL_WARNING_COLOR=#FFA500

## Set the color for assistant output (default: #0088ff)
#CECLI_ASSISTANT_OUTPUT_COLOR=#0088ff

## Set the color for the completion menu (default: terminal's default text color)
#CECLI_COMPLETION_MENU_COLOR=

## Set the background color for the completion menu (default: terminal's default background color)
#CECLI_COMPLETION_MENU_BG_COLOR=

## Set the color for the current item in the completion menu (default: terminal's default background color)
#CECLI_COMPLETION_MENU_CURRENT_COLOR=

## Set the background color for the current item in the completion menu (default: terminal's default text color)
#CECLI_COMPLETION_MENU_CURRENT_BG_COLOR=

## Set the markdown code theme (default: default, other options include monokai, solarized-dark, solarized-light, or a Pygments builtin style, see https://pygments.org/styles for available themes)
#CECLI_CODE_THEME=default

## Show diffs when committing changes (default: False)
#CECLI_SHOW_DIFFS=false

###############
# Git settings:

## Enable/disable looking for a git repo (default: True)
#CECLI_GIT=true

## Enable/disable adding .aider* to .gitignore (default: True)
#CECLI_GITIGNORE=true

## Enable/disable the addition of files listed in .gitignore to Aider's editing scope.
#CECLI_ADD_GITIGNORE_FILES=false

## Specify the aider ignore file (default: .aiderignore in git root)
#CECLI_AIDERIGNORE=.aiderignore

## Only consider files in the current subtree of the git repository
#CECLI_SUBTREE_ONLY=false

## Enable/disable auto commit of LLM changes (default: True)
#CECLI_AUTO_COMMITS=true

## Enable/disable commits when repo is found dirty (default: True)
#CECLI_DIRTY_COMMITS=true

## Attribute aider code changes in the git author name (default: True). If explicitly set to True, overrides --attribute-co-authored-by precedence.
#CECLI_ATTRIBUTE_AUTHOR=

## Attribute aider commits in the git committer name (default: True). If explicitly set to True, overrides --attribute-co-authored-by precedence for aider edits.
#CECLI_ATTRIBUTE_COMMITTER=

## Prefix commit messages with 'aider: ' if aider authored the changes (default: False)
#CECLI_ATTRIBUTE_COMMIT_MESSAGE_AUTHOR=false

## Prefix all commit messages with 'aider: ' (default: False)
#CECLI_ATTRIBUTE_COMMIT_MESSAGE_COMMITTER=false

## Attribute aider edits using the Co-authored-by trailer in the commit message (default: True). If True, this takes precedence over default --attribute-author and --attribute-committer behavior unless they are explicitly set to True.
#CECLI_ATTRIBUTE_CO_AUTHORED_BY=true

## Enable/disable git pre-commit hooks with --no-verify (default: False)
#CECLI_GIT_COMMIT_VERIFY=false

## Commit all pending changes with a suitable commit message, then exit
#CECLI_COMMIT=false

## Specify a custom prompt for generating commit messages
#CECLI_COMMIT_PROMPT=

## Perform a dry run without modifying files (default: False)
#CECLI_DRY_RUN=false

## Skip the sanity check for the git repository (default: False)
#CECLI_SKIP_SANITY_CHECK_REPO=false

## Enable/disable watching files for ai coding comments (default: False)
#CECLI_WATCH_FILES=false

########################
# Fixing and committing:

## Lint and fix provided files, or dirty files if none provided
#CECLI_LINT=false

## Specify lint commands to run for different languages, eg: "python: flake8 --select=..." (can be used multiple times)
#CECLI_LINT_CMD=

## Enable/disable automatic linting after changes (default: True)
#CECLI_AUTO_LINT=true

## Specify command to run tests
#CECLI_TEST_CMD=

## Enable/disable automatic testing after changes (default: False)
#CECLI_AUTO_TEST=false

## Run tests, fix problems found and then exit
#CECLI_TEST=false

############
# Analytics:

## Enable/disable analytics for current session (default: random)
#CECLI_ANALYTICS=

## Specify a file to log analytics events
#CECLI_ANALYTICS_LOG=

## Permanently disable analytics
#CECLI_ANALYTICS_DISABLE=false

## Send analytics to custom PostHog instance
#CECLI_ANALYTICS_POSTHOG_HOST=

## Send analytics to custom PostHog project
#CECLI_ANALYTICS_POSTHOG_PROJECT_API_KEY=

############
# Upgrading:

## Check for updates and return status in the exit code
#CECLI_JUST_CHECK_UPDATE=false

## Check for new aider versions on launch
#CECLI_CHECK_UPDATE=true

## Show release notes on first run of new version (default: None, ask user)
#CECLI_SHOW_RELEASE_NOTES=

## Install the latest version from the main branch
#CECLI_INSTALL_MAIN_BRANCH=false

## Upgrade aider to the latest version from PyPI
#CECLI_UPGRADE=false

########
# Modes:

## Specify a single message to send the LLM, process reply then exit (disables chat mode)
#CECLI_MESSAGE=

## Specify a file containing the message to send the LLM, process reply, then exit (disables chat mode)
#CECLI_MESSAGE_FILE=

## Run aider in your browser (default: False)
#CECLI_GUI=false

## Enable automatic copy/paste of chat between aider and web UI (default: False)
#CECLI_COPY_PASTE=false

## Apply the changes from the given file instead of running the chat (debug)
#CECLI_APPLY=

## Apply clipboard contents as edits using the main model's editor format
#CECLI_APPLY_CLIPBOARD_EDITS=false

## Do all startup activities then exit before accepting user input (debug)
#CECLI_EXIT=false

## Print the repo map and exit (debug)
#CECLI_SHOW_REPO_MAP=false

## Print the system prompts and exit (debug)
#CECLI_SHOW_PROMPTS=false

#################
# Voice settings:

## Audio format for voice recording (default: wav). webm and mp3 require ffmpeg
#CECLI_VOICE_FORMAT=wav

## Specify the language for voice using ISO 639-1 code (default: auto)
#CECLI_VOICE_LANGUAGE=en

## Specify the input device name for voice recording
#CECLI_VOICE_INPUT_DEVICE=

#################
# Other settings:

## Never prompt for or attempt to install Playwright for web scraping (default: False).
#CECLI_DISABLE_PLAYWRIGHT=false

## specify a file to edit (can be used multiple times)
#CECLI_FILE=

## specify a read-only file (can be used multiple times)
#CECLI_READ=

## Use VI editing mode in the terminal (default: False)
#CECLI_VIM=false

## Specify the language to use in the chat (default: None, uses system settings)
#CECLI_CHAT_LANGUAGE=

## Specify the language to use in the commit message (default: None, user language)
#CECLI_COMMIT_LANGUAGE=

## Always say yes to every confirmation
#CECLI_YES_ALWAYS=

## Enable verbose output
#CECLI_VERBOSE=false

## Load and execute /commands from a file on launch
#CECLI_LOAD=

## Specify the encoding for input and output (default: utf-8)
#CECLI_ENCODING=utf-8

## Line endings to use when writing files (default: platform)
#CECLI_LINE_ENDINGS=platform

## Specify the .env file to load (default: .env in git root)
#CECLI_ENV_FILE=.env

## Enable/disable suggesting shell commands (default: True)
#CECLI_SUGGEST_SHELL_COMMANDS=true

## Enable/disable fancy input with history and completion (default: True)
#CECLI_FANCY_INPUT=true

## Enable/disable multi-line input mode with Meta-Enter to submit (default: False)
#CECLI_MULTILINE=false

## Enable/disable terminal bell notifications when LLM responses are ready (default: False)
#CECLI_NOTIFICATIONS=false

## Specify a command to run for notifications instead of the terminal bell. If not specified, a default command for your OS may be used.
#CECLI_NOTIFICATIONS_COMMAND=

## Enable/disable detection and offering to add URLs to chat (default: True)
#CECLI_DETECT_URLS=true

## Specify which editor to use for the /editor command
#CECLI_EDITOR=

## Print shell completion script for the specified SHELL and exit. Supported shells: bash, tcsh, zsh. Example: aider --shell-completions bash
#CECLI_SHELL_COMPLETIONS=

############################
# Deprecated model settings:

## Use claude-3-opus-20240229 model for the main chat (deprecated, use --model)
#CECLI_OPUS=false

## Use anthropic/claude-3-7-sonnet-20250219 model for the main chat (deprecated, use --model)
#CECLI_SONNET=false

## Use claude-3-5-haiku-20241022 model for the main chat (deprecated, use --model)
#CECLI_HAIKU=false

## Use gpt-4-0613 model for the main chat (deprecated, use --model)
#CECLI_4=false

## Use gpt-4o model for the main chat (deprecated, use --model)
#CECLI_4O=false

## Use gpt-4o-mini model for the main chat (deprecated, use --model)
#CECLI_MINI=false

## Use gpt-4-1106-preview model for the main chat (deprecated, use --model)
#CECLI_4_TURBO=false

## Use gpt-3.5-turbo model for the main chat (deprecated, use --model)
#CECLI_35TURBO=false

## Use deepseek/deepseek-chat model for the main chat (deprecated, use --model)
#CECLI_DEEPSEEK=false

## Use o1-mini model for the main chat (deprecated, use --model)
#CECLI_O1_MINI=false

## Use o1-preview model for the main chat (deprecated, use --model)
#CECLI_O1_PREVIEW=false
```
<!--[[[end]]]-->
