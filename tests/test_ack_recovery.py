import math
from pathlib import Path
import shlex
import sys
import unittest

import switch as s
import switch_auto as a
from test_review_fixes import fixture


class AckRecoveryTests(unittest.TestCase):
    def followup(self, f, **fields):
        s.hook(f.root, 'p1', dict(hook_event_name='UserPromptSubmit',
                                session_id='new', prompt='Please retry the acknowledgment.', **fields))

    def timed_out(self, f):
        f.request()
        f.h.ack = False
        result = f.run_request()
        self.assertEqual(result['outcome'], 'cleared_not_resumed')
        self.assertIn('submitted_at', result)
        return result

    def ack(self, f, r):
        return s.acknowledge(f.h, f.root, r['request_id'], 'new', r['checkpoint_sha256'])

    def test_followup_before_worker_poll_preserves_submission(self):
        with fixture() as f:
            f.request()
            f.h.ack = False
            original = f.h.prompt

            def prompt(pane, text):
                result = original(pane, text)
                if text != '/clear':
                    self.followup(f)
                    self.ack(f, s.load(s.request_dir(f.root, f.r['request_id']) / 'request.json'))
                return result

            f.h.prompt = prompt
            result = f.run_request()
            self.assertEqual(result['outcome'], 'resumed', result.get('reason'))
            self.assertEqual(len(f.h.sent), 2)

    def test_same_session_start_preserves_submission(self):
        with fixture() as f:
            self.timed_out(f)
            before = s.telemetry(f.root, 'p1', 'new')['submitted']
            s.hook(f.root, 'p1', dict(hook_event_name='SessionStart', session_id='new',
                                    source='resume', cwd=str(f.root)))
            self.assertEqual(s.telemetry(f.root, 'p1', 'new')['submitted'], before)

    def test_late_ack_uses_saved_confirmation_after_legacy_telemetry_loss(self):
        with fixture() as f:
            r = self.timed_out(f)
            t = s.telemetry(f.root, 'p1', 'new')
            t['submitted'] = None  # Telemetry written by the old hook after a follow-up.
            s.atomic(s.telemetry_path(f.root, 'p1', 'new'), t)
            self.assertEqual(self.ack(f, r)['session_id'], 'new')
            # A late receipt does not rewrite a finished helper's historical outcome.
            self.assertEqual(s.load(s.request_dir(f.root, r['request_id']) / 'request.json'), r)

    def test_followup_does_not_make_an_unobserved_bootstrap_acknowledgeable(self):
        with fixture() as f:
            f.request()
            f.h.submit = f.h.ack = False
            r = f.run_request()
            self.followup(f)
            with self.assertRaisesRegex(s.Refused, 'bootstrap submission not observed'):
                self.ack(f, r)

    def test_saved_confirmation_does_not_bypass_identity_mode_or_checkpoint(self):
        for invalid in ('session', 'terminal', 'mode', 'checkpoint'):
            with self.subTest(invalid=invalid), fixture() as f:
                r = self.timed_out(f)
                t = s.telemetry(f.root, 'p1', 'new')
                t['submitted'] = None
                s.atomic(s.telemetry_path(f.root, 'p1', 'new'), t)
                self.followup(f)
                if invalid == 'session':
                    f.h.sid = 'other'
                elif invalid == 'terminal':
                    f.h.terminal = 'other'
                elif invalid == 'mode':
                    s.hook(f.root, 'p1', dict(hook_event_name='UserPromptSubmit',
                                            session_id='new', prompt='Retry', permission_mode='default'))
                else:
                    (s.request_dir(f.root, r['request_id']) / 'checkpoint.json').write_text('{}')
                with self.assertRaises(s.Refused):
                    self.ack(f, r)
                self.assertFalse((s.request_dir(f.root, r['request_id']) / 'ack.json').exists())

    def test_invalid_saved_confirmation_is_not_evidence(self):
        for invalid in (None, True, '123', 0, -1, math.nan, math.inf):
            with self.subTest(invalid=invalid), fixture() as f:
                r = self.timed_out(f)
                t = s.telemetry(f.root, 'p1', 'new')
                t['submitted'] = None
                s.atomic(s.telemetry_path(f.root, 'p1', 'new'), t)
                r['submitted_at'] = invalid
                s.atomic(s.request_dir(f.root, r['request_id']) / 'request.json', r)
                with self.assertRaisesRegex(s.Refused, 'bootstrap submission not observed'):
                    self.ack(f, r)

    def test_wrong_or_pre_send_submission_is_not_evidence(self):
        for field in ('id', 'sha256', 'at'):
            with self.subTest(field=field), fixture() as f:
                r = self.timed_out(f)
                r.pop('submitted_at')
                s.atomic(s.request_dir(f.root, r['request_id']) / 'request.json', r)
                t = s.telemetry(f.root, 'p1', 'new')
                t['submitted'][field] = r['resume_at'] - 1 if field == 'at' else 'wrong'
                s.atomic(s.telemetry_path(f.root, 'p1', 'new'), t)
                with self.assertRaisesRegex(s.Refused, 'bootstrap submission not observed'):
                    self.ack(f, r)

    def test_new_session_does_not_inherit_submission(self):
        with fixture() as f:
            self.timed_out(f)
            s.hook(f.root, 'p1', dict(hook_event_name='SessionStart', session_id='other',
                                    source='clear', cwd=str(f.root)))
            self.assertIsNone(s.telemetry(f.root, 'p1', 'other')['submitted'])

    def test_bootstrap_seeds_one_exact_command_covered_by_installer(self):
        with fixture() as f:
            f.request()
            r = f.run_request()
            prompt = f.h.sent[1]
            self.assertIn('exactly as given, alone, in its own Bash call', prompt)
            self.assertIn('Do not chain commands', prompt)
            self.assertIn('checksum checks in a separate call', prompt)
            command = prompt.split('```bash\n', 1)[1].split('\n```', 1)[0]
            args = shlex.split(command)
            self.assertEqual(args[:3], [sys.executable, str(Path(s.__file__).resolve()), 'ack'])
            self.assertEqual(args[3:], ['--state-dir', r['root'], '--request-id', r['request_id'],
                                       '--session', 'new', '--checkpoint-sha256', r['checkpoint_sha256']])
            # Existing install behavior must continue to cover the emitted command prefix.
            installed = a.install('project', f.root, None, f.root)
            rule = 'Bash(' + shlex.join(args[:3]) + ' *)'
            self.assertIn(rule, installed['required_permissions'])
            self.assertIn(rule, s.load(f.root / '.claude/settings.local.json')['permissions']['allow'])
