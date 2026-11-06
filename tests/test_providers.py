import contextlib
import io
import json
import os
import sys
import types
import tempfile
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import remediate as app
from engine.providers import configuration, generate, ProviderError


class ProviderTests(unittest.TestCase):
    def env(self, **values):
        return patch.dict(os.environ, {'GREENPR_ENABLE_MODEL_REPAIR': '1',
                                      'GREENPR_MODEL': 'customer-selected-model', **values}, clear=True)

    def test_disabled_never_constructs_clients_or_requires_credentials(self):
        with patch.dict(os.environ, {}, clear=True), patch('engine.providers.httpx.Client') as client:
            self.assertIsNone(generate('private', 'x', 'openai'))
            self.assertEqual(app.resolve_engine_tiers()['provider'], 'disabled')
            client.assert_not_called()

    def test_multiple_keys_require_choice_and_explicit_choice_wins(self):
        with self.env(GEMINI_API_KEY='google-fixture', OPENAI_API_KEY='openai-fixture'):
            with self.assertRaises(ProviderError):
                configuration()
            os.environ['GREENPR_PROVIDER'] = 'openai'
            self.assertEqual(configuration().key, 'openai-fixture')

    def test_empty_action_credentials_do_not_override_generic_key(self):
        with self.env(GREENPR_PROVIDER='openai', GREENPR_API_KEY='generic-fixture',
                      GEMINI_API_KEY='', OPENAI_API_KEY='', ANTHROPIC_API_KEY=''):
            self.assertEqual(configuration().key, 'generic-fixture')
            self.assertEqual(configuration().provider, 'openai')

    def test_alias_and_model_selection_without_environment_mutation(self):
        with self.env(GOOGLE_API_KEY='fixture', GREENPR_REPAIR_MODEL='repair-selected'):
            before = dict(os.environ)
            self.assertEqual(app.resolve_engine_tiers(), {'provider': 'gemini', 'tier1': 'customer-selected-model', 'tier2': 'repair-selected'})
            self.assertEqual(dict(os.environ), before)
            os.environ['GEMINI_API_KEY'] = 'different'
            with self.assertRaises(ProviderError):
                configuration()

    def test_missing_model_or_key_and_unknown_provider_fail_before_transport(self):
        for values in ({'GREENPR_PROVIDER': 'groq'}, {'GREENPR_PROVIDER': 'unknown'},
                       {'GREENPR_API_KEY': 'generic'}, {'OPENAI_API_KEY': 'fixture', 'GREENPR_MODEL': ''}):
            with self.subTest(values=values), self.env(**values), patch('engine.providers.httpx.Client') as client:
                with self.assertRaises(ProviderError):
                    configuration()
                client.assert_not_called()

    def test_gemini_binds_selected_key_model_and_endpoint(self):
        calls = []
        client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=lambda **kw: calls.append(kw) or types.SimpleNamespace(text='fixed')), close=lambda: calls.append('closed'))
        factory = lambda **kw: calls.append(kw) or client
        google = types.ModuleType('google')
        google.genai = types.SimpleNamespace(Client=factory)
        with self.env(GREENPR_PROVIDER='gemini', GREENPR_API_KEY='chosen', OPENAI_API_KEY='other'), patch.dict(sys.modules, {'google': google}):
            self.assertEqual(generate('source', 'customer-selected-model', 'gemini'), 'fixed')
        self.assertEqual(calls[0]['api_key'], 'chosen')
        self.assertFalse(calls[0]['vertexai'])
        self.assertEqual(calls[0]['http_options']['base_url'], 'https://generativelanguage.googleapis.com')
        self.assertEqual(calls[0]['http_options']['client_args'], {'trust_env': False, 'follow_redirects': False})
        self.assertEqual(calls[1]['model'], 'customer-selected-model')
        self.assertEqual(calls[-1], 'closed')

    def test_http_providers_use_only_selected_endpoint_key_and_model(self):
        real_client = httpx.Client
        for provider, url in [('openai', 'https://api.openai.com/v1/chat/completions'),
                              ('deepseek', 'https://api.deepseek.com/chat/completions'),
                              ('groq', 'https://api.groq.com/openai/v1/chat/completions'),
                              ('anthropic', 'https://api.anthropic.com/v1/messages')]:
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(200, json=({'content': [{'type': 'text', 'text': 'fixed'}]} if provider == 'anthropic' else {'choices': [{'message': {'content': 'fixed'}}]}))
            with self.subTest(provider=provider), self.env(GREENPR_PROVIDER=provider, GREENPR_API_KEY='selected', GEMINI_API_KEY='other'), patch('engine.providers.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
                self.assertEqual(generate('source', 'customer-selected-model', provider), 'fixed')
            self.assertEqual(len(requests), 1)
            self.assertEqual(str(requests[0].url), url)
            self.assertEqual(json.loads(requests[0].content)['model'], 'customer-selected-model')
            self.assertEqual(requests[0].headers.get('x-api-key') if provider == 'anthropic' else requests[0].headers.get('authorization'), 'selected' if provider == 'anthropic' else 'Bearer selected')

    def test_redirect_or_server_error_never_falls_back_or_exposes_payload(self):
        real_client = httpx.Client
        for status in (302, 401, 429, 500):
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(status, headers={'location': 'https://wrong.example/'}, text='private-source key-secret')
            with self.env(GREENPR_PROVIDER='openai', GREENPR_API_KEY='key-secret', GEMINI_API_KEY='other'), patch('engine.providers.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)), self.assertRaises(ProviderError) as error:
                generate('private-source', 'customer-selected-model', 'openai')
            self.assertEqual(len(requests), 1)
            self.assertNotIn('key-secret', str(error.exception))
            self.assertNotIn('private-source', str(error.exception))

    def test_compatible_url_validation_and_mismatch_prevents_disclosure(self):
        for url in ('http://remote.example/v1', 'https://user:pass@example.com/v1', 'https://example.com/v1?key=x', ''):
            with self.env(GREENPR_PROVIDER='openai-compatible', GREENPR_API_KEY='fixture', GREENPR_BASE_URL=url), self.assertRaises(ProviderError):
                configuration()
        with self.env(GREENPR_PROVIDER='openai-compatible', GREENPR_API_KEY='fixture', GREENPR_BASE_URL='http://127.0.0.1:8000/v1'):
            self.assertEqual(configuration().base_url, 'http://127.0.0.1:8000/v1')
            with patch('engine.providers.httpx.Client') as client, self.assertRaises(ProviderError):
                generate('source', 'wrong-model', 'openai-compatible')
            client.assert_not_called()

    def test_migration_plan_and_repair_share_explicit_route(self):
        with self.env(GREENPR_PROVIDER='groq', GROQ_API_KEY='fixture'), patch.object(app, '_call_native_llm', return_value=json.dumps({'package_name': 'fixture', 'target_version': '2.0', 'general_summary': 'verified'})) as call:
            result = app.extract_migration_plan('fixture', '1.0', '2.0', 'notes')
            self.assertEqual(result.general_summary, 'verified')
            self.assertEqual(call.call_args.args[1:], ('customer-selected-model', 'groq'))

    def test_mock_http_repair_updates_tracked_source_and_real_gate_passes(self):
        previous = Path.cwd()
        real_client = httpx.Client
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'choices': [{'message': {'content': '```python\ndef value():\n    return 1\n```'}}]})
        with tempfile.TemporaryDirectory(prefix='greenpr-provider-repair-') as directory:
            try:
                os.chdir(directory)
                for args in (['init', '-q'], ['config', 'user.name', 'Fixture'], ['config', 'user.email', 'fixture@example.invalid']):
                    subprocess.run(['git', *args], check=True)
                Path('service.py').write_text('def value():\n    return 0\n')
                Path('test_guard.py').write_text('unchanged\n')
                subprocess.run(['git', 'add', '.'], check=True)
                subprocess.run(['git', 'commit', '-qm', 'fixture'], check=True)
                with self.env(GREENPR_PROVIDER='openai', OPENAI_API_KEY='fixture', PATH=os.environ.get('PATH', ''), SystemRoot=os.environ.get('SystemRoot', '')), patch('engine.providers.httpx.Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
                    vuln = {'package': 'fixture', 'target_version': '2.0'}
                    plan = app.MigrationPlan(package_name='fixture', target_version='2.0', general_summary='fixture')
                    self.assertTrue(app._attempt_file_patch('service.py', 'expected 1', vuln, plan, 'customer-selected-model', 'openai'))
                    self.assertFalse(app._attempt_file_patch('test_guard.py', 'error', vuln, plan, 'customer-selected-model', 'openai'))
                subprocess.run([sys.executable, '-c', 'import service; assert service.value() == 1'], check=True)
                self.assertEqual(len(requests), 1)
                self.assertIn('return 0', json.loads(requests[0].content)['messages'][0]['content'])
                self.assertEqual(Path('test_guard.py').read_text(), 'unchanged\n')
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
