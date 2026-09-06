---
parent: Configuration
nav_order: 800
description: Configure custom OpenAI-compatible model providers.
---

# Model Providers

Model providers allow you to use OpenAI-compatible API endpoints with cecli. You can define custom providers that point to any OpenAI-compatible API, including self-hosted models, proprietary endpoints, or third-party services.

Built-in providers are defined in [`providers.json`](https://github.com/cecli/cecli/blob/main/cecli/resources/providers.json) and are automatically available. Use the `--model-providers` option to add your own.

## Configuration Format

Each provider is defined as a JSON object with the following keys:

| Key | Required | Description |
|-----|----------|-------------|
| `api_base` | Yes | The base URL for the OpenAI-compatible API endpoint |
| `api_key_env` | Yes | A list of environment variable names that can hold the API key (the first found one is used) |
| `display_name` | No | A human-readable name for the provider |
| `models_url` | No | URL to fetch the model list (defaults to `{api_base}/models`) |
| `default_headers` | No | A dict of default HTTP headers to include in every request |
| `account_id_env` | No | Environment variable name for an account ID (used with `{account_id}` in `models_url` or `api_base`) |
| `static_models` | No | A list of static model definitions when no `models_url` is available |
| `hf_namespace` | No | If `true`, model names are treated as HuggingFace repository identifiers (prefixed with `hf:`) |
| `supports_stream` | No | Set to `false` if the provider does not support streaming responses |
| `requires_api_key` | No | Set to `false` if the provider does not require an API key (default: `true`) |
| `base_url_env` | No | A list of environment variable names that can override `api_base` (takes precedence if set) |
| `session_header` | No | Name of a request header that carries a per-session unique key |


## Configuration File Usage

You can also define model providers in your `~/.cecli/conf.yml` or `.cecli.conf.yml` configuration file:

```yaml
model-providers:
  my-provider:
    api_base: "https://api.myprovider.com/v1"
    api_key_env:
      - "MY_PROVIDER_API_KEY"
    display_name: "My Provider"
```

## Command Line Usage

Use the `--model-providers` option to define custom providers as a JSON string:

```bash
cecli --model-providers '{
  "my-provider": {
    "api_base": "https://api.myprovider.com/v1",
    "api_key_env": ["MY_PROVIDER_API_KEY"],
    "display_name": "My Provider"
  }
}'
```

## Using Custom Provider Models

Once a provider is configured, you can use its models by referencing them with the provider slug as a prefix:

```bash
cecli --model my-provider/model-name
```

For example, if you configure provider `my-provider` and it serves a model called `gpt-4o-mini`, you would use:

```bash
cecli --model my-provider/gpt-4o-mini
```

## Setting API Keys

Set the environment variable(s) specified in `api_key_env` before running cecli:

```bash
export MY_PROVIDER_API_KEY="sk-your-key-here"
cecli --model my-provider/gpt-4o-mini
```


## Advanced Configuration

### Custom Model List Endpoint

If your provider uses a different endpoint for listing models, specify `models_url`:

```yaml
model-providers:
  my-provider:
    api_base: "https://api.myprovider.com/v1"
    api_key_env: ["MY_PROVIDER_API_KEY"]
    models_url: "https://api.myprovider.com/v1/models/list"
```

### Static Model Definitions

If your provider does not expose a `/models` endpoint, define models statically:

```yaml
model-providers:
  my-provider:
    api_base: "https://api.myprovider.com/v1"
    api_key_env: ["MY_PROVIDER_API_KEY"]
    static_models:
      - id: "gpt-4o"
        max_input_tokens: 128000
        mode: "chat"
      - id: "gpt-4o-mini"
        max_input_tokens: 128000
        mode: "chat"
```

### Default Headers

Add default HTTP headers for every request:

```yaml
model-providers:
  my-provider:
    api_base: "https://api.myprovider.com/v1"
    api_key_env: ["MY_PROVIDER_API_KEY"]
    default_headers:
      X-Custom-Header: "value"
      X-Organization: "my-org"
```

### HuggingFace Namespace

For providers that serve HuggingFace models, enable the `hf_namespace` flag:

```yaml
model-providers:
  my-hf-provider:
    api_base: "https://api.myprovider.com/v1"
    api_key_env: ["MY_PROVIDER_API_KEY"]
    hf_namespace: true
```

This will prefix model names with `hf:` (e.g., `hf:meta-llama/Llama-2-7b`).

## Built-in Providers

Cecli ships with several built-in providers defined in `providers.json`. These are automatically available without any configuration:

| Provider | Slug | API Base |
|----------|------|----------|
| AI21 Labs | `ai21` | `https://api.ai21.com/studio/v1` |
| Anyscale | `anyscale` | `https://api.endpoints.anyscale.com/v1` |
| Apertis | `apertis` | `https://api.stima.tech/v1` |
| Azure OpenAI | `azure` | `https://{resource}.openai.azure.com/openai/deployments/{deployment}` |
| Azure AI | `azure_ai` | `https://{resource}.services.ai.azure.com` |
| Baseten | `baseten` | `https://inference.baseten.co/v1` |
| AWS Bedrock | `bedrock` | `https://bedrock-runtime.{region}.amazonaws.com` |
| Bedrock Mantle | `bedrock_mantle` | `https://bedrock-mantle.{region}.api.aws/v1` |
| Cerebras | `cerebras` | `https://api.cerebras.ai/v1` |
| ChatGPT | `chatgpt` | `https://chatgpt.com/backend-api/codex` |
| Chutes | `chutes` | `https://llm.chutes.ai/v1/` |
| Cloudflare | `cloudflare` | `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1` |
| Codestral | `codestral` | `https://codestral.mistral.ai/v1` |
| Crusoe | `crusoe` | `https://managed-inference-api-proxy.crusoecloud.com/v1` |
| Darkbloom | `darkbloom` | `https://api.darkbloom.dev/v1` |
| DashScope | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Databricks | `databricks` | `https://{workspace}.cloud.databricks.com` |
| DeepInfra | `deepinfra` | `https://api.deepinfra.com/v1/openai` |
| Featherless AI | `featherless_ai` | `https://api.featherless.ai/v1` |
| Fireworks AI | `fireworks_ai` | `https://api.fireworks.ai/inference/v1` |
| Friendli AI | `friendliai` | `https://api.friendli.ai/serverless/v1` |
| GMI Cloud | `gmi` | `https://api.gmi-serving.com/v1` |
| Gradient AI | `gradient_ai` | `https://inference.do-ai.run/v1` |
| Groq | `groq` | `https://api.groq.com/openai/v1` |
| Helicone | `helicone` | `https://ai-gateway.helicone.ai/` |
| Hyperbolic | `hyperbolic` | `https://api.hyperbolic.xyz/v1` |
| Inception Labs | `inception` | `https://api.inceptionlabs.ai/v1` |
| Lambda | `lambda_ai` | `https://api.lambda.ai/v1` |
| Lemonade | `lemonade` | `http://localhost:8000/api/v1` |
| LibertAI | `libertai` | `https://api.libertai.io/v1` |
| LlamaGate | `llamagate` | `https://api.llamagate.dev/v1` |
| Meta Llama | `meta_llama` | `https://api.llama.com/compat/v1` |
| MiniMax | `minimax` | `https://api.minimax.io/v1` |
| Mistral | `mistral` | `https://api.mistral.ai/v1` |
| Moonshot AI | `moonshot` | `https://api.moonshot.ai/v1` |
| Morph | `morph` | `https://api.morphllm.com/v1` |
| Nano-GPT | `nano-gpt` | `https://nano-gpt.com/api/v1` |
| Nebius AI Studio | `nebius` | `https://api.studio.nebius.ai/v1` |
| Novita AI | `novita` | `https://api.novita.ai/v3/openai` |
| Nscale | `nscale` | `https://inference.api.nscale.com/v1` |
| Ollama | `ollama` | `http://localhost:11434/v1` |
| OpenCode Go | `opencode-go` | `https://opencode.ai/zen/go/v1` |
| OpenCode Zen | `opencode-zen` | `https://opencode.ai/zen/v1` |
| OVHcloud | `ovhcloud` | `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1` |
| Perplexity | `perplexity` | `https://api.perplexity.ai` |
| Pinstripes | `pinstripes` | `https://pinstripes.io/v1` |
| Poe | `poe` | `https://api.poe.com/v1` |
| PublicAI | `publicai` | `https://api.publicai.co/v1` |
| SambaNova | `sambanova` | `https://api.sambanova.ai/v1` |
| Sarvam | `sarvam` | `https://api.sarvam.ai/v1` |
| Scaleway | `scaleway` | `https://api.scaleway.ai/v1` |
| Synthetic | `synthetic` | `https://api.synthetic.new/openai/v1` |
| Tencent | `tencent` | `https://tokenhub-intl.tencentcloudmaas.com/v1` |
| TensorMesh | `tensormesh` | `https://serverless.tensormesh.ai/v1` |
| Together AI | `together_ai` | `https://api.together.xyz/v1` |
| v0 | `v0` | `https://api.v0.dev/v1` |
| Venice AI | `veniceai` | `https://api.venice.ai/api/v1` |
| Vercel AI Gateway | `vercel_ai_gateway` | `https://ai-gateway.vercel.sh/v1` |
| Volcengine | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| Weights & Biases | `wandb` | `https://api.inference.wandb.ai/v1` |
| xAI | `xai` | `https://api.x.ai/v1` |
| Xiaomi MiMo | `xiaomi_mimo` | `https://api.xiaomimimo.com/v1` |
| Z.ai | `zai` | `https://api.z.ai/api/paas/v4` |

## Troubleshooting

### "Provider not found"

Ensure the provider slug is correctly spelled and that you are using it as a prefix in the model name:

```bash
cecli --model my-provider/model-name
```

### "Missing API key"

Set the appropriate environment variable defined in `api_key_env` before running cecli:

```bash
export MY_PROVIDER_API_KEY="sk-..."
```

### "Connection refused" or timeout errors

Verify that the `api_base` URL is correct and accessible from your network. Some providers may require VPN access or specific network configuration.