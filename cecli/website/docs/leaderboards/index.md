---
highlight_image: /assets/leaderboard.jpg
nav_order: 950
description: Quantitative benchmarks of LLM code editing skill.
has_children: true
---


# LLM Leaderboards

Cecli excels with LLMs skilled at writing and *editing* code, and uses benchmarks to evaluate an LLM's ability to follow instructions and edit code successfully without human intervention. [Aider's polyglot benchmark](https://cecli.dev/2024/12/21/polyglot.html#the-polyglot-benchmark) tests LLMs on 225 challenging Exercism coding exercises across C++, Go, Java, JavaScript, Python, and Rust.

## cecli polyglot coding leaderboard

| Model | Percent correct | Cost | Correct edit format | Edit format |
|---|---|---|---|---|
| gpt-5 (high) | 88.0% | $29.08 | 91.6% | diff |
| gpt-5 (medium) | 86.7% | $17.69 | 88.4% | diff |
| o3-pro (high) | 84.9% | $146.32 | 97.8% | diff |
| gemini-2.5-pro-preview-06-05 (32k think) | 83.1% | $49.88 | 99.6% | diff-fenced |
| o3 (high) | 81.3% | $21.23 | 94.7% | diff |
| gpt-5 (low) | 81.3% | $10.37 | 86.7% | diff |
| grok-4 (high) | 79.6% | $59.62 | 97.3% | diff |
| gemini-2.5-pro-preview-06-05 (default think) | 79.1% | $45.60 | 100.0% | diff-fenced |
| o3 (high) + gpt-4.1 | 78.2% | $17.55 | 100.0% | architect |
| Gemini 2.5 Pro Preview 05-06 | 76.9% | $37.41 | 97.3% | diff-fenced |
| o3 | 76.9% | $13.75 | 93.8% | diff |
| DeepSeek-V3.2-Exp (Reasoner) | 74.2% | $1.30 | 97.3% | diff |
| Gemini 2.5 Pro Preview 03-25 | 72.9% |  | 92.4% | diff-fenced |
| o4-mini (high) | 72.0% | $19.64 | 90.7% | diff |
| claude-opus-4-20250514 (32k thinking) | 72.0% | $65.75 | 97.3% | diff |
| DeepSeek R1 (0528) | 71.4% | $4.80 | 94.6% | diff |
| claude-opus-4-20250514 (no think) | 70.7% | $68.63 | 98.7% | diff |
| DeepSeek-V3.2-Exp (Chat) | 70.2% | $0.88 | 98.2% | diff |
| claude-3-7-sonnet-20250219 (32k thinking tokens) | 64.9% | $36.83 | 97.8% | diff |
| DeepSeek R1 + claude-3-5-sonnet-20241022 | 64.0% | $13.29 | 100.0% | architect |
| o1-2024-12-17 (high) | 61.7% | $186.50 | 91.5% | diff |
| claude-sonnet-4-20250514 (32k thinking) | 61.3% | $26.58 | 97.3% | diff |
| o3-mini (high) | 60.4% | $18.16 | 93.3% | diff |
| claude-3-7-sonnet-20250219 (no thinking) | 60.4% | $17.72 | 93.3% | diff |
| Qwen3 235B A22B diff, no think, Alibaba API | 59.6% |  | 92.9% | diff |
| Kimi K2 | 59.1% | $1.24 | 92.9% | diff |
| DeepSeek R1 | 56.9% | $5.42 | 96.9% | diff |
| claude-sonnet-4-20250514 (no thinking) | 56.4% | $15.82 | 98.2% | diff |
| DeepSeek V3 (0324) | 55.1% | $1.12 | 99.6% | diff |
| gemini-2.5-flash-preview-05-20 (24k think) | 55.1% | $8.56 | 95.6% | diff |
| Quasar Alpha | 54.7% |  | 98.2% | diff |
| o3-mini (medium) | 53.8% | $8.86 | 95.1% | diff |
| Grok 3 Beta | 53.3% | $11.03 | 99.6% | diff |
| Optimus Alpha | 52.9% |  | 97.3% | diff |
| gpt-4.1 | 52.4% | $9.86 | 98.2% | diff |
| claude-3-5-sonnet-20241022 | 51.6% | $14.41 | 99.6% | diff |
| Grok 3 Mini Beta (high) | 49.3% | $0.73 | 99.6% | whole |
| DeepSeek Chat V3 (prev) | 48.4% | $0.34 | 98.7% | diff |
| gemini-2.5-flash-preview-04-17 (default) | 47.1% | $1.85 | 85.3% | diff |
| chatgpt-4o-latest (2025-03-29) | 45.3% | $19.74 | 64.4% | diff |
| gpt-4.5-preview | 44.9% | $183.18 | 97.3% | diff |
| gemini-2.5-flash-preview-05-20 (no think) | 44.0% | $1.14 | 93.8% | diff |
| gpt-oss-120b (high) | 41.8% | $0.74 | 79.1% | diff |
| Qwen3 32B | 40.0% | $0.76 | 83.6% | diff |
| gemini-exp-1206 | 38.2% |  | 98.2% | whole |
| Gemini 2.0 Pro exp-02-05 | 35.6% |  | 100.0% | whole |
| Grok 3 Mini Beta (low) | 34.7% | $0.79 | 100.0% | whole |
| o1-mini-2024-09-12 | 32.9% | $18.58 | 96.9% | whole |
| gpt-4.1-mini | 32.4% | $1.99 | 92.4% | diff |
| claude-3-5-haiku-20241022 | 28.0% | $6.06 | 91.1% | diff |
| chatgpt-4o-latest (2025-02-15) | 27.1% | $14.37 | 93.3% | diff |
| QwQ-32B + Qwen 2.5 Coder Instruct | 26.2% |  | 100.0% | architect |
| gpt-4o-2024-08-06 | 23.1% | $7.03 | 94.2% | diff |
| gemini-2.0-flash-exp | 22.2% |  | 100.0% | whole |
| qwen-max-2025-01-25 | 21.8% |  | 90.2% | diff |
| QwQ-32B | 20.9% |  | 67.6% | diff |
| gpt-4o-2024-11-20 | 18.2% | $6.74 | 95.1% | diff |
| gemini-2.0-flash-thinking-exp-01-21 | 18.2% |  | 77.8% | diff |
| DeepSeek Chat V2.5 | 17.8% | $0.51 | 92.9% | diff |
| Qwen2.5-Coder-32B-Instruct | 16.4% |  | 99.6% | whole |
| Llama 4 Maverick | 15.6% |  | 99.1% | whole |
| yi-lightning | 12.9% |  | 92.9% | whole |
| command-a-03-2025-quality | 12.0% |  | 99.6% | whole |
| Codestral 25.01 | 11.1% | $1.98 | 100.0% | whole |
| openhands-lm-32b-v0.1 | 10.2% |  | 95.1% | whole |
| gpt-4.1-nano | 8.9% | $0.43 | 94.2% | whole |
| Qwen2.5-Coder-32B-Instruct | 8.0% |  | 71.6% | diff |
| gemma-3-27b-it | 4.9% |  | 100.0% | whole |
| gpt-4o-mini-2024-07-18 | 3.6% | $0.32 | 100.0% | whole |

The full per-run details for each model (command, date, error counts, token usage, etc.) are maintained in [`cecli/website/_data/polyglot_leaderboard.yml`](https://github.com/cecli-dev/cecli/blob/main/cecli/website/_data/polyglot_leaderboard.yml) in the repository.

By Paul Gauthier, last updated November 20, 2025.
