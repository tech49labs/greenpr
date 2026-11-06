# Optional BYOK repair

Core scanning, deterministic dependency updates, verification and PR delivery need
no model key. Model-assisted planning/repair requires `--enable-model-repair`.
It can disclose changelog content, candidate source and error traces to the chosen
provider. Only enable it for repositories approved for that provider.

Choose `GREENPR_PROVIDER` and a provider-supported native `GREENPR_MODEL` ID.
There is no global model default. Gemini can be your personal configuration;
customers can choose any implemented adapter. `GREENPR_REPAIR_MODEL` optionally
selects a second repair model at the **same** provider. Native IDs are passed
unchanged; check their availability in your provider account.

| Provider | Credential | Transport |
| --- | --- | --- |
| gemini | GEMINI_API_KEY or GOOGLE_API_KEY | Installed Google GenAI SDK, explicit key and Gemini endpoint |
| openai | OPENAI_API_KEY | httpx, OpenAI Chat Completions |
| anthropic | ANTHROPIC_API_KEY | httpx, versioned Messages API |
| deepseek | DEEPSEEK_API_KEY | httpx, DeepSeek Chat Completions |
| groq | GROQ_API_KEY | httpx, Groq OpenAI-compatible endpoint |
| openai-compatible | GREENPR_API_KEY | httpx, explicit GREENPR_BASE_URL |

The existing requirements include both httpx and Google GenAI; no extra provider
SDK installation is needed. A nonempty generic GREENPR_API_KEY is also accepted
when GREENPR_PROVIDER is explicit. Keys are never identified by their prefixes.
One nonempty provider-specific credential can identify its provider; multiple
providers require explicit selection. Conflicting key aliases are rejected.
Empty GitHub Action inputs do not count as credentials. No environment keys are
rewritten and a provider failure never triggers a call to another provider.

Example PowerShell setup (keep real credentials out of source and public logs):

```powershell
$env:GREENPR_PROVIDER = 'openai' # or your chosen supported adapter
$env:OPENAI_API_KEY = '<set privately from your secret store>'
$env:GREENPR_MODEL = '<supported model ID from that provider>'
python C:\tools\greenpr\remediate.py --enable-model-repair --skip-pr
```

For Gemini, change the provider to `gemini` and use GEMINI_API_KEY with your
chosen model. For compatible servers, use `openai-compatible`, GREENPR_API_KEY
and GREENPR_BASE_URL. Custom endpoints require HTTPS, except explicit loopback
HTTP for a local server. URLs containing credentials, queries or fragments are
rejected. Named providers use fixed endpoints; custom endpoint overrides require
the compatible adapter. HTTP redirects and environment proxies are disabled.

The composite action exposes provider, model, api_key, base_url and provider-key
inputs. Put keys in GitHub secrets, enable repair explicitly, and pin a reviewed
GreenPR commit. Hosted Actions are optional and are not required for local use.

## Evidence and limits

Routing, key selection, response handling, redirects, failures, redaction and
default-off behavior are verified offline. These checks do not prove live model
availability or repair quality. Live provider repair remains experimental until
an authorized BYOK smoke verifies it for that account/model. No paid inference is
performed by the release tests. A model response never replaces the verification
gate, target-version/lock verification, advisory rescan or PR review.

Protocol references: [Groq compatibility](https://console.groq.com/docs/openai),
[DeepSeek API](https://api-docs.deepseek.com/),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create).
