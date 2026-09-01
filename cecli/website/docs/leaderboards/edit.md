---
parent: LLM Leaderboards
highlight_image: /assets/leaderboard.jpg
nav_order: 50
description: Quantitative benchmark of basic LLM code editing skill.
---

# Code editing leaderboard


> **Note:** This old [cecli code editing leaderboard](edit.html) has been replaced by the new, much more challenging [polyglot leaderboard](index.html).

[cecli's code editing benchmark](../benchmarks.html#gpt-code-editing-benchmarks-the-benchmark) asks the LLM to edit python source files to complete 133 small coding exercises from Exercism. This measures the LLM's coding ability, and whether it can write new code that integrates into existing code. The model also has to successfully apply all its changes to the source file without human intervention.

| Model | Percent completed correctly | Percent using correct edit format | Command | Edit format |
|---|---|---|---|---|
| claude-3-5-sonnet-20241022 | 84.2% | 99.2% | `aider --model anthropic/claude-3-5-sonnet-20241022` | diff |
| o1 | 84.2% | 99.2% | `aider --model openrouter/openai/o1` | diff |
| gemini-exp-1206 (whole) | 80.5% | 100.0% | `aider --model gemini/gemini-exp-1206` | whole |
| o1-preview | 79.7% | 93.2% | `aider --model o1-preview` | diff |
| claude-3.5-sonnet-20240620 | 77.4% | 99.2% | `aider --model claude-3.5-sonnet-20240620` | diff |
| claude-3-5-haiku-20241022 | 75.2% | 95.5% | `aider --model anthropic/claude-3-5-haiku-20241022` | diff |
| gpt-4o-2024-05-13 | 72.9% | 96.2% | `aider` | diff |
| DeepSeek Coder V2 0724 | 72.9% | 97.7% | `aider --model deepseek/deepseek-coder` | diff |
| ollama/qwen2.5-coder:32b | 72.9% | 100.0% | `aider --model ollama/qwen2.5-coder:32b` | whole |
| DeepSeek V2.5 | 72.2% | 96.2% | `aider --deepseek` | diff |
| openai/chatgpt-4o-latest | 72.2% | 97.0% | `aider --model openai/chatgpt-4o-latest` | diff |
| DeepSeek-V2.5-1210 | 72.2% | 99.2% | `aider --model deepseek/deepseek-chat` | diff |
| gpt-4o-2024-08-06 | 71.4% | 98.5% | `aider --model openai/gpt-4o-2024-08-06` | diff |
| Qwen2.5-Coder-32B-Instruct | 71.4% | 94.7% | `aider --model openai/hf:Qwen/Qwen2.5-Coder-32B-Instruct --openai-api-base https://glhf.chat/api/openai/v1` | diff |
| gpt-4o-2024-11-20 | 71.4% | 99.2% | `aider --model openai/gpt-4o-2024-11-20` | diff |
| o1-mini (whole) | 70.7% | 90.0% | `aider --model o1-mini` | whole |
| DeepSeek Chat V2 0628 | 69.9% | 97.7% | `aider --model deepseek/deepseek-chat` | diff |
| gemini-2.0-flash-exp | 69.9% | 97.0% | `aider --model gemini/gemini-2.0-flash-exp` | diff |
| Qwen2.5-Coder-14B-Instruct | 69.2% | 100.0% | `aider --model openai/Qwen2.5-Coder-14B-Instruct` | whole |
| gemini-exp-1206 (diff) | 69.2% | 84.2% | `aider --model gemini/gemini-exp-1206` | diff |
| claude-3-opus-20240229 | 68.4% | 100.0% | `aider --opus` | diff |
| gpt-4-0613 | 67.7% | 100.0% | `aider -4` | diff |
| gemini-1.5-pro-exp-0827 | 66.9% | 94.7% | `aider --model gemini/gemini-1.5-pro-exp-0827` | diff-fenced |
| Dracarys2-72B-Instruct | 66.9% | 100.0% | `(via glhf.chat)` | whole |
| gpt-4-0125-preview | 66.2% | 97.7% | `aider --model gpt-4-0125-preview` | udiff |
| gpt-4-0314 | 66.2% | 93.2% | `aider --model gpt-4-0314` | diff |
| llama-3.1-405b-instruct (whole) | 66.2% | 100.0% | `aider --model openrouter/meta-llama/llama-3.1-405b-instruct` | whole |
| gpt-4-1106-preview | 65.4% | 92.5% | `aider --model gpt-4-1106-preview` | udiff |
| qwen-2.5-72b-instruct (bf16) | 65.4% | 96.2% | `aider --model openrouter/qwen/qwen-2.5-72b-instruct` | diff |
| gemini-1.5-pro-002 | 65.4% | 96.2% | `aider --model gemini/gemini-1.5-pro-002` | diff-fenced |
| Mistral Large (2411) | 65.4% | 96.2% | `aider --model mistral/mistral-large-latest` | diff |
| openrouter/qwen/qwen-2.5-coder-32b-instruct | 65.4% | 84.2% | `aider --model openrouter/qwen/qwen-2.5-coder-32b-instruct` | diff |
| yi-lightning | 65.4% | 97.0% | `aider --model openai/yi-lightning` | whole |
| gpt-4-turbo-2024-04-09 (udiff) | 63.9% | 97.0% | `aider --gpt-4-turbo` | udiff |
| llama-3.1-405b-instruct (diff) | 63.9% | 92.5% | `aider --model openrouter/meta-llama/llama-3.1-405b-instruct` | diff |
| nousresearch/hermes-3-llama-3.1-405b | 63.9% | 100.0% | `aider --model openrouter/nousresearch/hermes-3-llama-3.1-405b` | whole |
| ollama/Qwen2.5.1-Coder-7B-Instruct-GGUF:Q8_0-32k | 63.9% | 100.0% | `aider --model ollama/Qwen2.5.1-Coder-7B-Instruct-GGUF:Q8_0-32k` | whole |
| ollama/qwen2.5-coder:14b | 61.7% | 98.5% | `aider --model ollama/qwen2.5-coder:14b` | whole |
| o1-mini | 61.1% | 100.0% | `aider --model o1-mini` | diff |
| gemini-exp-1114 | 60.9% | 85.7% | `aider --model gemini/gemini-exp-1114` | diff |
| Mistral Large 2 (2407) | 60.2% | 100.0% | `aider --model mistral/mistral-large-2407` | whole |
| llama-3.3-70b-instruct | 59.4% | 88.7% | `aider --model openrouter/meta-llama/llama-3.3-70b-instruct` | diff |
| llama-3.1-70b-instruct | 58.6% | 100.0% | `aider --model fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct` | whole |
| Grok-2 | 58.6% | 98.5% | `aider --model openrouter/x-ai/grok-2` | whole |
| ollama/qwen2.5:32b-instruct-q8_0 | 58.6% | 100.0% | `aider --model ollama/qwen2.5:32b-instruct-q8_0` | whole |
| gpt-3.5-turbo-0301 | 57.9% | 100.0% | `aider --model gpt-3.5-turbo-0301` | whole |
| Qwen2.5-Coder-7B-Instruct | 57.9% | 100.0% | `aider --model openai/Qwen2.5-Coder-7B-Instruct` | whole |
| gemini-exp-1121 | 57.9% | 83.5% | `aider --model gemini/gemini-exp-1121` | diff |
| gpt-4-turbo-2024-04-09 (diff) | 57.6% | 100.0% | `aider --model gpt-4-turbo-2024-04-09` | diff |
| gemini-1.5-pro-001 | 57.1% | 87.2% | `aider --model gemini/gemini-1.5-pro-latest` | diff-fenced |
| gpt-3.5-turbo-1106 | 56.1% | 100.0% | `aider --model gpt-3.5-turbo-1106` | whole |
| Qwen2 72B Instruct | 55.6% | 100.0% | `aider --model together_ai/qwen/Qwen2-72B-Instruct` | whole |
| gpt-4o-mini | 55.6% | 100.0% | `aider --model gpt-4o-mini` | whole |
| claude-3-sonnet-20240229 | 54.9% | 100.0% | `aider --sonnet` | whole |
| Grok-2-mini | 54.9% | 100.0% | `aider --model openrouter/x-ai/grok-2-mini` | whole |
| Llama-3.1-Nemotron-70B-Instruct-HF | 54.9% | 99.2% | `(via glhf.chat)` | whole |
| Yi Coder 9B Chat | 54.1% | 100.0% | `aider --model openai/hf:01-ai/Yi-Coder-9B-Chat --openai-api-base https://glhf.chat/api/openai/v1` | whole |
| ollama/qwen2.5:32b | 54.1% | 100.0% | `aider --model ollama/qwen2.5:32b` | whole |
| Nova Pro | 54.1% | 100.0% | `aider --model bedrock/us.amazon.nova-pro-v1:0` | whole |
| gemini-1.5-flash-exp-0827 | 52.6% | 100.0% | `aider --model gemini/gemini-1.5-flash-exp-0827` | whole |
| qwen2.5-coder:7b-instruct-q8_0 | 51.9% | 100.0% | `aider --model ollama/qwen2.5-coder:7b-instruct-q8_0` | whole |
| codestral-2405 | 51.1% | 100.0% | `aider --model mistral/codestral-2405` | whole |
| gemini-1.5-flash-002 (0924) | 51.1% | 100.0% | `aider --model gemini/gemini-1.5-flash-002` | whole |
| gpt-3.5-turbo-0125 | 50.4% | 100.0% | `aider -3` | whole |
| gpt-3.5-turbo-0613 | 50.4% | 100.0% | `aider --model gpt-3.5-turbo-0613` | whole |
| qwen2:72b-instruct-q8_0 | 49.6% | 100.0% | `aider --model ollama/qwen2:72b-instruct-q8_0` | whole |
| llama3-70b-8192 | 49.2% | 73.5% | `aider --model groq/llama3-70b-8192` | diff |
| codestral:22b-v0.1-q8_0 | 48.1% | 100.0% | `aider --model ollama/codestral:22b-v0.1-q8_0` | whole |
| Codestral-22B-v0.1-Q4_K_M | 48.1% | 100.0% | `aider --model Codestral-22B-v0.1-Q4_K_M` | whole |
| claude-3-haiku-20240307 | 47.4% | 100.0% | `aider --model claude-3-haiku-20240307` | whole |
| ollama/codestral | 45.9% | 98.5% | `aider --model ollama/codestral` | whole |
| yi-coder:9b-chat-q4_0 | 45.1% | 100.0% | `aider --model ollama/yi-coder:9b-chat-q4_0` | whole |
| WizardLM-2 8x22B | 44.4% | 100.0% | `aider --model openrouter/microsoft/wizardlm-2-8x22b` | whole |
| gemini-1.5-flash-latest | 44.4% | 100.0% | `aider --model gemini/gemini-1.5-flash-latest` | whole |
| ollama/yi-coder:9b-chat-fp16 | 43.6% | 99.2% | `aider --model ollama/yi-coder:9b-chat-fp16` | whole |
| Reflection-70B | 42.1% | 100.0% | `(not currently supported)` | whole |
| Qwen2.5-Coder-3B-Instruct | 39.1% | 100.0% | `aider --model openai/Qwen2.5-Coder-3B-Instruct` | whole |
| gemini-1.5-flash-8b-exp-0827 | 38.3% | 100.0% | `aider --model gemini/gemini-1.5-flash-8b-exp-0827` | whole |
| Command R+ (08-24) | 38.3% | 100.0% | `aider --model command-r-plus-08-2024` | whole |
| Command R (08-24) | 38.3% | 100.0% | `aider --model command-r-08-2024` | whole |
| gemini-1.5-flash-8b-exp-0924 | 38.3% | 100.0% | `aider --model gemini/gemini-1.5-flash-8b-exp-0924` | whole |
| ollama/mistral-small | 38.3% | 99.2% | `aider --model ollama/mistral-small` | whole |
| qwen1.5-110b-chat | 37.6% | 100.0% | `aider --model together_ai/qwen/qwen1.5-110b-chat` | whole |
| llama-3.1-8b-instruct | 37.6% | 100.0% | `aider --model fireworks_ai/accounts/fireworks/models/llama-v3p1-8b-instruct` | whole |
| gemma2:27b-instruct-q8_0 | 36.1% | 100.0% | `aider --model ollama/gemma2:27b-instruct-q8_0` | whole |
| codeqwen:7b-chat-v1.5-q8_0 | 34.6% | 100.0% | `aider --model ollama/codeqwen:7b-chat-v1.5-q8_0` | whole |
| ollama/mistral-nemo:12b-instruct-2407-q4_K_M | 33.1% | 100.0% | `aider --model ollama/mistral-nemo:12b-instruct-2407-q4_K_M` | whole |
| ollama/codegeex4 | 32.3% | 97.0% | `aider --model ollama/codegeex4` | whole |
| command-r-plus | 31.6% | 100.0% | `aider --model command-r-plus` | whole |
| Qwen2.5-Coder-1.5B-Instruct | 31.6% | 100.0% | `aider --model openai/Qwen2.5-Coder-1.5B-Instruct` | whole |
| ollama/wojtek/opencodeinterpreter:6.7b | 30.1% | 91.0% | `aider --model ollama/wojtek/opencodeinterpreter:6.7b` | whole |
| ollama/hermes3:8b-llama3.1-fp16 | 30.1% | 98.5% | `aider --model ollama/hermes3:8b-llama3.1-fp16` | whole |
| o1-mini-2024-09-12 | 27.1% | 95.6% | `aider --model o1-mini` | whole |
| ollama/llama3.2:3b-instruct-fp16 | 26.3% | 97.0% | `aider --model ollama/llama3.2:3b-instruct-fp16` | whole |
| ollama/tulu3 | 26.3% | 100.0% | `aider --model ollama/tulu3` | whole |
| ollama/hermes3 | 22.6% | 98.5% | `aider --model ollama/hermes3` | whole |
| ollama/granite3-dense:8b | 20.3% | 78.9% | `aider --model ollama/granite3-dense:8b` | whole |
| Qwen2.5-Coder-0.5B-Instruct | 14.3% | 100.0% | `aider --model openai/Qwen2.5-Coder-0.5B-Instruct` | whole |

## Notes on benchmarking results

The key benchmarking results are:

- **Percent completed correctly** - Measures what percentage of the coding tasks that the LLM completed successfully. To complete a task, the LLM must solve the programming assignment *and* edit the code to implement that solution.
- **Percent using correct edit format** - Measures the percent of coding tasks where the LLM complied with the edit format specified in the system prompt. If the LLM makes edit mistakes, cecli will give it feedback and ask for a fixed copy of the edit. The best models can reliably conform to the edit format, without making errors.


## Notes on the edit format

Cecli uses different "edit formats" to collect code edits from different LLMs. The "whole" format is the easiest for an LLM to use, but it uses a lot of tokens and may limit how large a file can be edited. Models which can use one of the diff formats are much more efficient, using far fewer tokens. Models that use a diff-like format are able to edit larger files with less cost and without hitting token limits.

Cecli is configured to use the best edit format for the popular OpenAI and Anthropic models and the [other models recommended on the LLM page](../llms.html). For lesser known models cecli will default to using the "whole" editing format since it is the easiest format for an LLM to use.

## Contributing benchmark results

Contributions of benchmark results are welcome! See the [benchmark README](https://github.com/cecli-dev/cecli/blob/main/benchmark/README.md) for information on running cecli's code editing benchmarks. Submit results by opening a PR with edits to the [benchmark results data files](https://github.com/cecli-dev/cecli/blob/main/cecli/website/_data/).

By Paul Gauthier, last updated April 12, 2025.
