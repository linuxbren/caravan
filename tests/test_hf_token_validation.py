import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import hf_auth


class TokenValidationTests(unittest.TestCase):
    def setUp(self):
        hf_auth._validation_cache.clear()
        self.status = patch.object(hf_auth, 'token_status', return_value={
            'configured': True, 'source': 'settings', 'has_settings': True})
        self.token = patch.object(hf_auth, 'resolve_hf_token', return_value='test-secret')
        self.status.start()
        self.token.start()
        self.addCleanup(self.status.stop)
        self.addCleanup(self.token.stop)

    def test_accepted_and_cached_without_secret(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"name":"tester"}')) as call:
            result = hf_auth.validated_token_status()
            self.assertEqual(result['validation'], 'accepted')
            self.assertNotIn('test-secret', repr(result))
            self.assertEqual(hf_auth.validated_token_status(), result)
            self.assertEqual(call.call_count, 1)

    def test_rejected(self):
        with patch('urllib.request.urlopen', side_effect=HTTPError('url', 401, 'bad', {}, None)):
            self.assertEqual(hf_auth.validated_token_status()['validation'], 'rejected')

    def test_network_and_rate_limit_are_not_rejected(self):
        for error in (URLError('offline'), HTTPError('url', 429, 'limit', {}, None)):
            hf_auth._validation_cache.clear()
            with patch('urllib.request.urlopen', side_effect=error):
                self.assertEqual(hf_auth.validated_token_status()['validation'], 'unavailable')

    def test_missing_does_not_call_network(self):
        with patch.object(hf_auth, 'resolve_hf_token', return_value=None), patch('urllib.request.urlopen') as call:
            self.assertEqual(hf_auth.validated_token_status()['validation'], 'missing')
            call.assert_not_called()

    def test_replacement_invalidates_digest_cache(self):
        with patch('urllib.request.urlopen', side_effect=lambda *a, **k: io.BytesIO(b'{"name":"tester"}')) as call:
            hf_auth.validated_token_status()
            with patch.object(hf_auth, 'resolve_hf_token', return_value='replacement'):
                hf_auth.validated_token_status()
            self.assertEqual(call.call_count, 2)


class TokenSettingsUiTests(unittest.TestCase):
    def test_compact_editor_and_validation_states(self):
        import pathlib
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node is required for UI state assertions")
        html = (pathlib.Path(__file__).parents[1] / "proxy/web/index.html").read_text()
        function = html.split("  function renderHfTokenStatus", 1)[1].split('  $("btnHfTokenEdit").addEventListener', 1)[0]
        script = """
const assert = require('assert');
const elements = {};
const $ = id => elements[id] || (elements[id] = {});
let hfTokenState = {};
function renderHfTokenStatus""" + function + """
const saved = {configured:true, has_settings:true, source:'settings', validation:'accepted'};
renderHfTokenStatus(saved);
assert.equal($('hfTokenEditor').hidden, true);
assert.equal($('btnHfTokenEdit').hidden, false);
assert.match($('hfTokenStatus').textContent, /Hugging Face token accepted/);
renderHfTokenStatus(saved, true);
assert.equal($('hfTokenEditor').hidden, false);
assert.equal($('btnHfTokenCancel').hidden, false);
renderHfTokenStatus({...saved, validation:'rejected'});
assert.equal($('hfTokenEditor').hidden, false);
assert.match($('hfTokenStatus').textContent, /rejected/);
renderHfTokenStatus({...saved, validation:'unavailable'});
assert.match($('hfTokenStatus').textContent, /couldn't check/);
assert.doesNotMatch($('hfTokenStatus').textContent, /accepted|rejected/);
renderHfTokenStatus({...saved, has_settings:false, source:'env'});
assert.equal($('btnHfTokenClear').hidden, true);
"""
        subprocess.run(["node", "-e", script], check=True, capture_output=True)
