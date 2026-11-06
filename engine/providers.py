"""Explicit BYOK routing. Never infer a provider from a key or fall back across providers."""
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

import httpx


class ProviderError(ValueError):
    pass


@dataclass(frozen=True)
class Configuration:
    provider: str
    model: str
    repair_model: str
    key: str = field(repr=False)
    base_url: str = ''


KEYS = {'gemini': ('GEMINI_API_KEY', 'GOOGLE_API_KEY'), 'openai': ('OPENAI_API_KEY',),
        'anthropic': ('ANTHROPIC_API_KEY',), 'deepseek': ('DEEPSEEK_API_KEY',),
        'groq': ('GROQ_API_KEY',), 'openai-compatible': ()}
BASES = {'openai': 'https://api.openai.com/v1', 'deepseek': 'https://api.deepseek.com',
         'groq': 'https://api.groq.com/openai/v1', 'anthropic': 'https://api.anthropic.com/v1'}


def configuration():
    if os.environ.get('GREENPR_ENABLE_MODEL_REPAIR') != '1':
        return None
    value = lambda name: os.environ.get(name, '').strip()
    provider = value('GREENPR_PROVIDER').lower()
    present = {p: [value(k) for k in names if value(k)] for p, names in KEYS.items()}
    if not provider:
        choices = [p for p, keys in present.items() if keys]
        if value('GREENPR_API_KEY') or len(choices) != 1:
            raise ProviderError('Set GREENPR_PROVIDER explicitly when using a generic key or multiple/no providers')
        provider = choices[0]
    if provider not in KEYS:
        raise ProviderError('Unsupported GREENPR_PROVIDER')
    keys = set(present[provider])
    if value('GREENPR_API_KEY'):
        keys.add(value('GREENPR_API_KEY'))
    if len(keys) > 1:
        raise ProviderError('Conflicting credential aliases for selected provider')
    key = next(iter(keys), '') or value('GREENPR_API_KEY')
    model = value('GREENPR_MODEL') or value('MODEL')
    if not key or not model:
        raise ProviderError('Selected provider requires a nonempty API key and GREENPR_MODEL')
    base = BASES.get(provider, '')
    if provider == 'openai-compatible':
        base = value('GREENPR_BASE_URL').rstrip('/')
        parsed = urlsplit(base)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))):
            raise ProviderError('Compatible endpoint requires HTTPS or explicit loopback HTTP, without URL credentials/query')
    elif value('GREENPR_BASE_URL'):
        raise ProviderError('GREENPR_BASE_URL is only supported with openai-compatible provider')
    return Configuration(provider, model, value('GREENPR_REPAIR_MODEL') or model, key, base)


def generate(prompt, model, provider):
    config = configuration()
    if config is None:
        return None
    if provider != config.provider or model not in (config.model, config.repair_model):
        raise ProviderError('Requested provider/model differs from selected configuration')
    try:
        if provider == 'gemini':
            from google import genai
            client = genai.Client(api_key=config.key, vertexai=False,
                                  http_options={'base_url': 'https://generativelanguage.googleapis.com', 'timeout': 60000,
                                                'client_args': {'trust_env': False, 'follow_redirects': False},
                                                'async_client_args': {'trust_env': False, 'follow_redirects': False}})
            try:
                text = client.models.generate_content(model=model, contents=prompt,
                                                     config={'max_output_tokens': 4096}).text
            finally:
                client.close()
        else:
            headers = {'Authorization': 'Bearer ' + config.key}
            body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}]}
            endpoint = '/chat/completions'
            if provider == 'anthropic':
                headers = {'x-api-key': config.key, 'anthropic-version': '2023-06-01'}
                body['max_tokens'] = 4096
                endpoint = '/messages'
            else:
                body['max_completion_tokens' if provider == 'openai' else 'max_tokens'] = 4096
            with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = client.post(config.base_url + endpoint, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
            text = (''.join(c['text'] for c in data['content'] if c.get('type') == 'text')
                    if provider == 'anthropic' else data['choices'][0]['message']['content'])
        if not isinstance(text, str) or not text.strip():
            raise ProviderError('Provider returned no usable text')
        return text.strip()
    except Exception as exc:
        # Do not echo provider bodies, prompts, credentials, or change providers.
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        raise ProviderError(f'{provider} request failed ({status or type(exc).__name__}); no provider fallback') from None
