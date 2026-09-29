import copy
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import switch as sw
import switch_auto as a


class AutoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.root = self.base / 'state'
        self.env = patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.base / 'user'), 'HERDR_PANE_ID': 'p1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.manifest = self.project / '.claude' / a.MANIFEST
        self.settings = self.project / '.claude/settings.local.json'
        self.now = 100.0

    def install(self, cap='250k', scope='project'):
        a.install(scope, self.project, cap, self.root)
        path = self.manifest if scope == 'project' else a.user_dir() / a.MANIFEST
        return a.read_config(path)

    def event(self, name, sid='s1', **kw):
        return dict(hook_event_name=name, session_id=sid, cwd=str(self.project), **kw)

    def start(self, cap='250k', sid='s1', source='startup'):
        self.c = self.install(cap)
        e = self.event('SessionStart', sid, source=source)
        sw.hook(self.root, 'p1', e, self.now)
        return a.auto_event(self.c, 'p1', e, self.now)

    def sample(self, tokens=250000, sid='s1', now=None, size=1000000, duration=1):
        data = dict(session_id=sid, cwd=str(self.project), cost={'total_api_duration_ms': duration},
                    context_window=dict(context_window_size=size,
                        current_usage=dict(input_tokens=tokens-100, cache_creation_input_tokens=40,
                                           cache_read_input_tokens=60, output_tokens=9999),
                        total_input_tokens=9999999))
        a.observe(self.c, 'p1', data, self.now if now is None else now)
        return data

    def auto(self, name, **kw):
        return a.auto_event(self.c, 'p1', self.event(name, **kw), self.now)

    def state(self, sid='s1'):
        return a.auto_state(self.root, 'p1', sid)

    def test_limits(self):
        for value, kind, expected in [('250k','tokens',250000), ('300000','tokens',300000),
                                     ('0.2M','tokens',200000), ('25%','percent',25)]:
            self.assertEqual(a.limit(value)['value'], expected)
            self.assertEqual(a.limit(value)['kind'], kind)
        for value in ['0', '-1', 'NaN', '101%', '0%', '2.2', '1e4', '250kk']:
            with self.assertRaises(sw.Refused): a.limit(value)

    def test_install_uninstall_preserves_settings_and_updates_limit(self):
        original = {'permissions': {'allow': ['Read']}, 'env': {'TEST':'yes'},
                    'hooks': {'Stop':[{'hooks':[{'type':'command','command':'true'}]}]},
                    'statusLine': {'type':'command','command':'cat', 'padding':2}}
        sw.atomic(self.settings, original)
        self.install()
        a.install('project', self.project, '300k', self.root)
        self.assertEqual(a.read_config(self.manifest)['limit']['value'], 300000)
        result = a.uninstall('project', self.project)
        self.assertTrue(result['original_statusline_restored'])
        self.assertEqual(sw.load(self.settings), original)
        self.assertFalse(self.manifest.exists())

    def test_uninstall_preserves_later_unrelated_edits(self):
        self.install()
        data = sw.load(self.settings)
        data['model'] = 'other'
        data['statusLine'] = {'type':'command','command':'echo replacement'}
        sw.atomic(self.settings, data)
        a.uninstall('project', self.project)
        self.assertEqual(sw.load(self.settings), {'model':'other', 'statusLine':data['statusLine']})

    def test_uninstall_refuses_dangling_modified_wrapper(self):
        self.install()
        data = sw.load(self.settings)
        data['statusLine']['command'] += ' --extra'
        sw.atomic(self.settings, data)
        with self.assertRaises(sw.Refused): a.uninstall('project', self.project)
        self.assertTrue(a.read_config(self.manifest)['enabled'])
        self.assertEqual(sw.load(self.settings), data)

    def test_dry_run_no_writes(self):
        a.install('project', self.project, '250k', self.root, True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_default_limit_and_reinstall_keeps_installed_limit(self):
        result = a.install('project', self.project, None, self.root)
        self.assertEqual((result['limit']['kind'], result['limit']['value']), ('percent', 25))
        self.assertIn('default 25%', result['notices'][0])
        a.install('project', self.project, '40%', self.root)
        result = a.install('project', self.project, None, self.root)
        self.assertEqual(result['limit']['value'], 40)
        self.assertNotIn('default', result['notices'][0])
        self.assertEqual(a.read_config(self.manifest)['limit']['value'], 40)

    def test_cli_install_without_limit(self):
        with patch('sys.stdout'):
            self.assertEqual(a.main(['install', '--project', str(self.project),
                                     '--state-dir', str(self.root)]), 0)
        self.assertEqual(a.read_config(self.manifest)['limit']['label'], '25%')

    def test_dry_run_reports_default_limit_and_permissions_to_add(self):
        sw.atomic(self.settings, {'permissions': {'allow': ['Read']}})
        before = self.settings.read_bytes()
        result = a.install('project', self.project, None, self.root, True)
        self.assertEqual(result['limit']['value'], 25)
        self.assertEqual(result['permissions_to_add'], a.permissions({'root': str(self.root)}))
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.settings.parent.iterdir()), ['settings.local.json'])

    def test_settings_formatting_round_trips_byte_for_byte(self):
        raws = [b'{\n    "zeta": 1,\n    "permissions": {\n        "allow": [\n            "Read"\n'
                b'        ]\n    },\n    "alpha": "caf\xc3\xa9"\n}\n',
                b'{\n\t"model": "x",\n\t"env": {\n\t\t"A": "1"\n\t}\n}',
                b'{"zeta":1,"alpha":"x"}',
                b'{\n  "name": "caf\\u00e9"\n}\n']
        for raw in raws:
            with self.subTest(raw=raw):
                self.settings.parent.mkdir(exist_ok=True)
                self.settings.write_bytes(raw)
                self.install()
                text = self.settings.read_text()
                if b'zeta' in raw:
                    self.assertLess(text.index('zeta'), text.index('alpha'))
                a.uninstall('project', self.project)
                self.assertEqual(self.settings.read_bytes(), raw)

    def test_existing_statusline_key_order_round_trips(self):
        raw = (json.dumps({'model': 'x', 'statusLine': {'type': 'command', 'command': 'cat', 'padding': 2},
                           'env': {'Z': '1', 'A': '2'}}, indent=2) + '\n').encode()
        self.settings.parent.mkdir()
        self.settings.write_bytes(raw)
        dry = a.install('project', self.project, '250k', self.root, True)
        result = a.install('project', self.project, '250k', self.root)
        self.assertFalse(any('normalizes' in n for n in dry['notices'] + result['notices']))
        self.assertTrue(a.uninstall('project', self.project)['original_statusline_restored'])
        self.assertEqual(self.settings.read_bytes(), raw)

    def test_crlf_line_endings_round_trip(self):
        raw = b'{\r\n  "model": "x"\r\n}\r\n'
        self.settings.parent.mkdir()
        self.settings.write_bytes(raw)
        result = a.install('project', self.project, '250k', self.root)
        self.assertFalse(any('normalizes' in n for n in result['notices']))
        self.assertNotIn(b'\n', self.settings.read_bytes().replace(b'\r\n', b''))
        a.uninstall('project', self.project)
        self.assertEqual(self.settings.read_bytes(), raw)

    def test_unreproducible_formatting_is_announced_and_backed_up(self):
        for raw in [b'{"label":"\\u0041"}', b'{\n  "a" : 1\n}\n', b'{"a": 1, "a": 2}']:
            with self.subTest(raw=raw):
                self.settings.parent.mkdir(exist_ok=True)
                self.settings.write_bytes(raw)
                dry = a.install('project', self.project, '250k', self.root, True)
                self.assertTrue(any('normalizes' in n for n in dry['notices']))
                result = a.install('project', self.project, '250k', self.root)
                self.assertTrue(any('normalizes' in n for n in result['notices']))
                self.assertEqual(Path(result['backup']).read_bytes(), raw)
                self.assertNotIn('notices', a.uninstall('project', self.project))

    def test_uninstall_backs_up_before_normalizing_later_edits(self):
        self.install()
        edited = self.settings.read_bytes().replace(b'"statusLine": ', b'"statusLine" : ')
        self.settings.write_bytes(edited)
        result = a.uninstall('project', self.project)
        self.assertEqual(Path(result['backup']).read_bytes(), edited)
        self.assertIn('normalizes', result['notices'][0])

    def test_permissions_added_then_removed_exactly(self):
        wanted = a.permissions({'root': str(self.root)})
        sw.atomic(self.settings, {'permissions': {'allow': ['Read', wanted[0]], 'deny': ['Bash(rm *)']}})
        result = a.install('project', self.project, '250k', self.root)
        self.assertEqual(result['added_permissions'], wanted[1:])
        allow = sw.load(self.settings)['permissions']['allow']
        self.assertEqual(allow, ['Read'] + wanted)
        data = sw.load(self.settings)
        data['permissions']['allow'].append('Bash(ls)')
        sw.atomic(self.settings, data)
        a.uninstall('project', self.project)
        self.assertEqual(sw.load(self.settings)['permissions'],
                         {'allow': ['Read', wanted[0], 'Bash(ls)'], 'deny': ['Bash(rm *)']})

    def test_permission_keys_created_by_install_are_removed(self):
        result = a.install('project', self.project, '250k', self.root)
        self.assertIsNone(result['backup'])
        self.assertEqual(sw.load(self.settings)['permissions']['allow'], a.permissions({'root': str(self.root)}))
        a.uninstall('project', self.project)
        self.assertNotIn('permissions', sw.load(self.settings))

    def test_malformed_permissions_refuse_install_untouched(self):
        for value in [[], {'allow': 'Read'}, {'allow': [None]}, {'allow': [{}]}, {'allow': ['Read', 1]}]:
            with self.subTest(value=value):
                sw.atomic(self.settings, {'permissions': value})
                before = self.settings.read_bytes()
                with self.assertRaises(sw.Refused): self.install()
                self.assertEqual(self.settings.read_bytes(), before)
                self.assertFalse(self.manifest.exists())

    def test_uninstall_refuses_malformed_permissions_keeping_ownership(self):
        self.install()
        data = sw.load(self.settings)
        for broken in [json.dumps(data['permissions']['allow']), None]:
            with self.subTest(broken=broken):
                if broken is None:
                    data['permissions'] = ['Read']
                else:
                    data['permissions']['allow'] = broken
                sw.atomic(self.settings, data)
                before = self.settings.read_bytes()
                with self.assertRaises(sw.Refused): a.uninstall('project', self.project)
                self.assertEqual(self.settings.read_bytes(), before)
                self.assertTrue(a.read_config(self.manifest)['added_permissions'])

    def test_backup_is_byte_identical_and_never_overwritten(self):
        first = b'{ "model" :   "old" }\n'
        self.settings.parent.mkdir()
        self.settings.write_bytes(first)
        backup = Path(a.install('project', self.project, '250k', self.root)['backup'])
        self.assertEqual(backup.read_bytes(), first)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        a.uninstall('project', self.project)
        self.settings.write_bytes(b'{"model": "new"}\n')
        second = Path(a.install('project', self.project, '250k', self.root)['backup'])
        self.assertNotEqual(second, backup)
        self.assertEqual(backup.read_bytes(), first)
        self.assertEqual(second.read_bytes(), b'{"model": "new"}\n')

    def test_malformed_settings_untouched(self):
        self.settings.parent.mkdir()
        self.settings.write_text('{bad')
        with self.assertRaises(ValueError): self.install()
        self.assertEqual(self.settings.read_text(), '{bad')

    def test_standalone_hook_conflict(self):
        sw.atomic(self.settings, {'hooks': {'Stop':[{'hooks':[{'command':'python3 /x/switch.py hook --state-dir /x'}]}]}})
        with self.assertRaises(sw.Refused): self.install()

    def test_scope_precedence_and_statusline_unwrap(self):
        original = {'type':'command','command':'cat', 'padding':1}
        sw.atomic(a.user_dir() / 'settings.json', {'statusLine':original})
        user = self.install(scope='user')
        project = self.install()
        self.assertEqual(project['original_effective_statusline'], original)
        self.assertFalse(a.active_config(a.user_dir()/a.MANIFEST, user, self.project))
        self.assertTrue(a.active_config(self.manifest, project, self.project/'subdir'))
        self.assertTrue(a.active_config(a.user_dir()/a.MANIFEST, user, self.base))
        a.uninstall('project', self.project)
        self.assertTrue(a.active_config(a.user_dir()/a.MANIFEST, user, self.project))

    def test_statusline_preserves_raw_input_and_output(self):
        sw.atomic(self.settings, {'statusLine': {'type':'command','command':'cat'}})
        self.c = self.install()
        raw = b'{"session_id":"s1", "context_window":null}\n'
        self.assertEqual(a.render_statusline(self.manifest, raw), raw)

    def test_statusline_invalid_observation_still_preserves_display(self):
        sw.atomic(self.settings, {'statusLine': {'type':'command','command':'cat'}})
        self.c = self.install()
        for raw in [b'not json', b'[]', b'{"session_id":"s1","cost":1}']:
            self.assertEqual(a.render_statusline(self.manifest, raw), raw)

    def test_statusline_timeout_kills_inherited_pipe_writer(self):
        sw.atomic(self.settings, {'statusLine': {'type':'command','command':'sleep 30 & wait'}})
        self.c = self.install()
        clock=__import__('time').monotonic
        start=clock()
        self.assertIn(b'unavailable',a.render_statusline(self.manifest,b'{}'))
        self.assertLess(clock()-start,4)

    def test_external_settings_edit_during_install_not_overwritten(self):
        original={'model':'old'}
        sw.atomic(self.settings,original)
        real_atomic=sw.atomic
        def concurrent(path,data):
            real_atomic(path,data)
            if Path(path)==self.manifest:
                real_atomic(self.settings,{'model':'new'})
        with patch.object(sw,'atomic',side_effect=concurrent):
            with self.assertRaises(sw.Refused): self.install()
        self.assertEqual(sw.load(self.settings),{'model':'new'})
        a.uninstall('project',self.project)
        self.assertEqual(sw.load(self.settings),{'model':'new'})

    def test_plain_claude_no_hook_effect(self):
        self.install()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(a.handle_hook(self.manifest, self.event('SessionStart', source='startup')))
            self.assertIsNone(a.handle_hook(self.manifest, self.event('Stop')))
        self.assertFalse(self.root.exists())

    def test_current_tokens_percent_not_cumulative_or_output(self):
        self.start('25%')
        data = self.sample()
        self.assertEqual(a.usage(data), (250000,25))
        self.assertIn('250000 tokens', self.auto('PostToolUse'))

    def test_below_boundary_then_exact_trigger(self):
        self.start()
        self.sample(249999)
        self.assertIsNone(self.auto('PostToolUse'))
        self.sample(250000, duration=2)
        self.assertIsNotNone(self.auto('PostToolUse'))
        self.sample(260000, duration=3)
        self.assertIsNone(self.auto('PostToolUse'))
        self.assertEqual(self.state()['trigger_measurement']['tokens'], 250000)
        self.assertEqual(self.state()['measurement']['tokens'], 260000)

    def test_percent_tracks_window(self):
        self.start('25%')
        self.sample(100000, size=200000)
        self.assertIsNotNone(self.auto('Stop'))

    def test_unknown_invalid_usage(self):
        for data in [{}, {'context_window':None}, {'context_window':{'current_usage':None}},
                     {'context_window':{'current_usage':{'input_tokens':1}}}]:
            self.assertEqual(a.usage(data), (None,None))
        self.start()
        data=self.sample()
        for value in [True, float('nan'), -2, '20', 1.5]:
            data['context_window']['current_usage']['input_tokens'] = value
            self.assertEqual(a.usage(data), (None,None))

    def test_stale_redraw_not_refreshed_and_new_api_refreshes(self):
        self.start()
        self.sample()
        self.sample(now=170)
        self.now=170
        self.assertIsNone(self.auto('Stop'))
        self.assertEqual(self.state()['status'], 'measurement_unknown_or_stale')
        self.sample(duration=2)
        self.assertIsNotNone(self.auto('Stop'))

    def test_wrong_session_and_future_samples_ignored(self):
        self.start()
        self.sample(sid='wrong')
        self.assertIsNone(self.auto('Stop'))
        self.sample(now=120)
        self.assertIsNone(self.auto('Stop'))

    def test_one_notice_and_one_stop_across_turns(self):
        self.start()
        self.sample()
        self.assertIsNotNone(self.auto('PostToolUse'))
        self.assertIsNone(self.auto('PostToolUseFailure'))
        self.assertIsNotNone(self.auto('Stop'))
        self.auto('UserPromptSubmit', prompt='continue')
        self.assertIsNone(self.auto('PostToolUse'))
        self.assertIsNone(self.auto('Stop'))

    def test_concurrent_hook_waits_then_delivers_feedback(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        self.start(); self.sample()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with sw.lock(a.auto_dir(self.root,'p1')/'events.lock'):
                pending=pool.submit(self.auto,'PostToolUse')
                time.sleep(0.05)
            self.assertIsNotNone(pending.result(timeout=1))
        self.assertIsNone(self.auto('PostToolUse'))

    def test_stop_hook_active_no_block(self):
        self.start()
        self.sample()
        self.assertIsNone(self.auto('Stop', stop_hook_active=True))

    def test_request_attempt_before_claim_suppresses_all_feedback(self):
        self.start()
        self.sample()
        self.auto('PreToolUse', tool_name='Bash', tool_input={'command':shlex.join([sys.executable,str(Path(sw.__file__).resolve()),'request','--bad-checkpoint'])})
        self.assertIsNone(self.auto('PostToolUseFailure'))
        self.assertIsNone(self.auto('Stop'))
        self.assertEqual(self.state()['status'], 'reset_attempted_no_repeat')

    def test_failed_claim_no_retry(self):
        self.start()
        self.sample()
        claim=self.root/'claims'/(sw.digest(b'p1\0s1')+'.json')
        sw.atomic(claim, {'request_id':'r1'})
        self.assertIsNone(self.auto('Stop'))
        self.assertEqual(self.state()['request_id'],'r1')

    def test_oversized_token_cap_reported(self):
        self.start()
        self.sample(190000,size=200000)
        self.assertIsNone(self.auto('Stop'))
        self.assertEqual(self.state()['status'],'limit_at_or_above_context_window')

    def test_bootstrap_above_cap_never_loops(self):
        self.start(source='clear')
        self.sample()
        for _ in range(3): self.assertIsNone(self.auto('Stop'))
        self.assertEqual(self.state()['status'],'awaiting_below_limit_after_bootstrap')
        self.sample(200000,duration=2)
        self.assertIsNone(self.auto('PostToolUse'))
        self.sample(260000,duration=3)
        self.assertIsNotNone(self.auto('PostToolUse'))

    def test_bootstrap_requires_fresh_sample_after_ack(self):
        self.start(source='clear')
        st=self.state(); st['bootstrap_request']='r1'; a.save_auto(self.root,'p1','s1',st)
        self.sample(200000)
        self.assertIsNone(self.auto('PostToolUse'))
        self.assertFalse(self.state()['armed'])
        sw.atomic(sw.request_dir(self.root,'r1')/'ack.json',{'session_id':'s1','at':101})
        self.now=102
        self.assertIsNone(self.auto('PostToolUse'))
        self.assertFalse(self.state()['armed'])
        self.sample(200001,duration=2)
        self.assertIsNone(self.auto('PostToolUse'))
        self.assertTrue(self.state()['armed'])

    def test_false_stop_not_recorded_when_continuation_emitted(self):
        self.start()
        self.now=__import__('time').time()
        self.sample()
        result=a.handle_hook(self.manifest,self.event('Stop'))
        self.assertEqual(result['decision'],'block')
        self.assertIsNone(sw.telemetry(self.root,'p1','s1')['stopped_at'])
        self.assertIsNone(a.handle_hook(self.manifest,self.event('Stop',stop_hook_active=True)))
        self.assertIsNotNone(sw.telemetry(self.root,'p1','s1')['stopped_at'])

    def test_subagent_feedback_ignored(self):
        self.start(); self.sample()
        self.assertIsNone(self.auto('Stop', agent_id='sub'))

    def test_provenance_preserves_input_without_bootstrap(self):
        self.start()
        self.auto('UserPromptSubmit',prompt='Original authorized work')
        self.auto('UserPromptSubmit',prompt=sw.MARKER+'bootstrap')
        data=sw.load(a.auto_dir(self.root,'p1')/'s1.inputs.json')
        self.assertEqual([x['prompt'] for x in data['inputs']], ['Original authorized work'])
        self.assertIn('no authority', data['source'])

    def test_procedure_contains_concrete_required_parameters(self):
        text=self.start()
        for value in ['--pane p1','--session s1','--state-dir '+str(self.root),
                      str(self.root/'auto-checkpoints/s1.json'),'authority_sources','workers']:
            self.assertIn(value,text)


if __name__ == '__main__': unittest.main()
