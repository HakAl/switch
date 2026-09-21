import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_switch as base
import switch as s
import switch_auto as a


@contextlib.contextmanager
def fixture():
    case = base.SwitchTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


class ReviewFixTests(unittest.TestCase):
    def test_transient_herdr_misses_in_both_readiness_passes_recover(self):
        # Four reads before /clear, confirmation, then four reads before bootstrap.
        for missing_call in (1, 2, 3, 4, 6, 7, 8, 9):
            with self.subTest(missing_call=missing_call), fixture() as f:
                f.request()
                real_agent = f.h.agent
                calls = 0
                def intermittent(pane):
                    nonlocal calls
                    calls += 1
                    return None if calls == missing_call else real_agent(pane)
                with patch.object(f.h, 'agent', side_effect=intermittent):
                    result = f.run_request()
                self.assertEqual(result['outcome'], 'resumed', result.get('reason'))
                self.assertEqual(f.h.sent.count('/clear'), 1)
                self.assertEqual(len(f.h.sent), 2)

    def test_missing_herdr_expires_at_idle_deadline_without_sending(self):
        with fixture() as f:
            f.request()
            with patch.object(f.h, 'agent', return_value=None):
                result = f.run_request()
            self.assertEqual(result['outcome'], 'not_cleared')
            self.assertIn('safe-boundary deadline', result['reason'])
            self.assertGreater(f.clock.t, 1)
            self.assertLessEqual(f.clock.t, 2)
            self.assertEqual(f.h.sent, [])

    def test_transient_missing_row_while_waiting_for_ack_recovers(self):
        with fixture() as f:
            f.request()
            real_agent = f.h.agent
            missed = False
            def intermittent(pane):
                nonlocal missed
                stage = s.load(s.request_dir(f.root, f.r['request_id'])/'request.json')['stage']
                if stage == 'resume_wait' and not missed:
                    missed = True
                    return None
                return real_agent(pane)
            with patch.object(f.h, 'agent', side_effect=intermittent):
                result = f.run_request()
            self.assertTrue(missed)
            self.assertEqual(result['outcome'], 'resumed', result.get('reason'))
            self.assertEqual(len(f.h.sent), 2)

    def test_persistent_missing_row_while_waiting_for_ack_expires(self):
        with fixture() as f:
            f.request()
            real_agent = f.h.agent
            def unavailable(pane):
                stage = s.load(s.request_dir(f.root, f.r['request_id'])/'request.json')['stage']
                return None if stage == 'resume_wait' else real_agent(pane)
            with patch.object(f.h, 'agent', side_effect=unavailable):
                result = f.run_request()
            self.assertEqual(result['outcome'], 'cleared_not_resumed')
            self.assertEqual(f.clock.t, 2)
            self.assertEqual(len(f.h.sent), 2)

    def test_known_identity_change_still_refuses_immediately(self):
        with fixture() as f:
            f.request()
            row = f.h.agent('p1'); row['terminal_id'] = 'replacement'
            with patch.object(f.h, 'agent', return_value=row):
                result = f.run_request()
            self.assertEqual(result['outcome'], 'not_cleared')
            self.assertEqual(f.clock.t, 0)
            self.assertEqual(f.h.sent, [])

    def test_delayed_clear_leaves_full_new_session_readiness_budget(self):
        with fixture() as f:
            f.request()
            f.h.clear_effect = False
            f.h.post_clear_output = 'starting'
            def advance():
                if f.clock.t >= 1.5 and f.h.sid == 'old': f.h.clear()
                if f.clock.t >= 2.5: f.h.output = base.screen()
            f.clock.on_sleep = advance
            real_agent = f.h.agent
            def bounded_agent(pane):
                return None if f.clock.t >= f.h.limit else real_agent(pane)
            with patch.object(f.h, 'agent', side_effect=bounded_agent):
                result = f.run_request()
            self.assertEqual(result['outcome'], 'resumed', result.get('reason'))
            self.assertEqual(f.h.sent.count('/clear'), 1)
            self.assertEqual(f.clock.t, 2.5)

    def test_new_session_readiness_budget_still_expires_without_bootstrap(self):
        with fixture() as f:
            f.request()
            f.h.clear_effect = False
            f.h.post_clear_output = 'starting'
            def advance():
                if f.clock.t >= 1.5 and f.h.sid == 'old': f.h.clear()
            f.clock.on_sleep = advance
            result = f.run_request()
            self.assertEqual(result['outcome'], 'cleared_not_resumed')
            self.assertEqual(f.clock.t, 3.5)
            self.assertEqual(f.h.sent, ['/clear'])

    def test_invalid_checkpoint_json_shapes_have_structured_cli_errors(self):
        with fixture() as f:
            variants = [[], 'text', None]
            variants += [dict(f.c, preparation=x) for x in (None, 'text', [], 42)]
            for value in variants:
                with self.subTest(value=value):
                    f.cp.write_text(json.dumps(value))
                    run = subprocess.run([sys.executable, '-B', s.__file__, 'preflight',
                        '--state-dir', str(f.root), '--pane', 'p1', '--session', 'old',
                        '--checkpoint', str(f.cp)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 3, run.stderr)
                    self.assertIn('checkpoint', json.loads(run.stderr)['error'])
                    self.assertNotIn('Traceback', run.stderr)

    def test_invalid_hook_entries_refuse_install_without_settings_mutation(self):
        variants = [None, 'entry', {'hooks': None}, {'hooks': [None]},
                    {'hooks': [{'command': None}]}, {'hooks': [{'command': 42}]}]
        for entry in variants:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                settings = root/'.claude/settings.local.json'
                s.atomic(settings, {'hooks': {'Stop': [entry]}})
                before = settings.read_bytes()
                run = subprocess.run([sys.executable, '-B', a.__file__, 'install', '250k',
                    '--project', str(root), '--state-dir', str(root/'state')],
                    env=dict(os.environ, CLAUDE_CONFIG_DIR=str(root/'user')),
                    capture_output=True, text=True)
                self.assertEqual(run.returncode, 3, run.stderr)
                self.assertIn('hook', json.loads(run.stderr)['error'])
                self.assertEqual(settings.read_bytes(), before)
                self.assertFalse((settings.parent/a.MANIFEST).exists())

    def test_uninstall_preserves_nonobject_statusline_edits(self):
        for value in (None, 'custom command', [], 42):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(root/'user')}):
                    a.install('project', root, '250k', root/'state')
                    settings = root/'.claude/settings.local.json'
                    data = s.load(settings); data['statusLine'] = value; s.atomic(settings, data)
                    run = subprocess.run([sys.executable, '-B', a.__file__, 'uninstall',
                        '--project', str(root)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertFalse(json.loads(run.stdout)['original_statusline_restored'])
                    self.assertEqual(s.load(settings), {'statusLine': value})

    def test_uninstall_refuses_malformed_statusline_still_referencing_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(root/'user')}):
                a.install('project', root, '250k', root/'state')
                settings = root/'.claude/settings.local.json'
                manifest = settings.parent/a.MANIFEST
                data = s.load(settings); data['statusLine'] = 'python wrapper '+str(manifest)
                s.atomic(settings, data); before = settings.read_bytes()
                with self.assertRaises(s.Refused): a.uninstall('project', root)
                self.assertEqual(settings.read_bytes(), before)
                self.assertTrue(a.read_config(manifest)['enabled'])

    def test_companion_version_matches_base(self):
        run = subprocess.run([sys.executable, '-B', a.__file__, '--version'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), s.VERSION)
