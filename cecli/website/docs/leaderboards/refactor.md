---
parent: LLM Leaderboards
highlight_image: /assets/leaderboard.jpg
nav_order: 100
description: Quantitative benchmark of LLM code refactoring skill.
---


## Refactoring leaderboard

[cecli's refactoring benchmark](https://github.com/cecli-AI/refactor-benchmark) asks the LLM to refactor 89 large methods from large python classes. This is a more challenging benchmark, which tests the model's ability to output long chunks of code without skipping sections or making mistakes. It was developed to provoke and measure [GPT-4 Turbo's "lazy coding" habit](https://cecli.dev/2023/12/21/unified-diffs.html).

The refactoring benchmark requires a large context window to work with large source files. Therefore, results are available for fewer models.

| Model | Percent completed correctly | Percent using correct edit format | Command | Edit format |
|---|---|---|---|---|
| claude-3-5-sonnet-20241022 | 92.1% | 91.0% | `aider --sonnet` | diff |
| o1-preview | 75.3% | 57.3% | `aider --model o1-preview` | diff |
| claude-3-opus-20240229 | 72.3% | 79.5% | `aider --opus` | diff |
| claude-3.5-sonnet-20240620 | 64.0% | 76.4% | `aider --sonnet` | diff |
| gpt-4o | 62.9% | 53.9% | `aider` | diff |
| gpt-4-1106-preview | 50.6% | 39.3% | `aider --model gpt-4-1106-preview` | udiff |
| gemini/gemini-1.5-pro-latest | 49.4% | 7.9% | `aider --model gemini/gemini-1.5-pro-latest` | diff-fenced |
| gpt-4o-2024-08-06 | 49.4% | 89.9% | `aider --model openai/gpt-4o-2024-08-06` | diff |
| o1-mini | 44.9% | 29.2% | `aider --model o1-mini` | diff |
| gpt-4-turbo-2024-04-09 (udiff) | 34.1% | 30.7% | `aider --gpt-4-turbo` | udiff |
| gpt-4-0125-preview | 33.7% | 47.2% | `aider --model gpt-4-0125-preview` | udiff |
| DeepSeek Coder V2 0724 (deprecated) | 32.6% | 59.6% | `aider --model deepseek/deepseek-coder` | diff |
| DeepSeek Chat V2.5 | 31.5% | 67.4% | `aider --deepseek` | diff |
| gpt-4-turbo-2024-04-09 (diff) | 21.4% | 6.8% | `aider --model gpt-4-turbo-2024-04-09` | diff |

By Paul Gauthier, last updated April 12, 2025.
