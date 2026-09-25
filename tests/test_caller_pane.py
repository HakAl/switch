"""A live target is insufficient: the request must come from that pane."""
import os
from unittest.mock import patch
import unittest
from test_review_fixes import fixture
import switch as s


class CallerPaneTests(unittest.TestCase):
    def test_other_live_pane_is_refused_before_read_or_claim(self):
        for command in ('preflight', 'request'):
            with self.subTest(command=command), fixture() as f:
                s.hook(f.root, 'pane-B', {'hook_event_name': 'SessionStart', 'session_id': 'old',
                    'source': 'startup', 'cwd': str(f.root), 'permission_mode': 'auto'})
                with patch.dict(os.environ, {'HERDR_PANE_ID': 'pane-A'}):
                    with self.assertRaisesRegex(s.Refused, 'caller pane'):
                        if command == 'preflight': s.preflight(f.h, f.root, 'pane-B', 'old', f.cp)
                        else: s.create(f.h, f.root, 'pane-B', 'old', f.cp, 'injected next action')
                self.assertEqual(f.h.agent_calls, 0)
                self.assertFalse((f.root / 'requests').exists())
                self.assertFalse((f.root / 'claims').exists())
                self.assertFalse(f.h.sent)

    def test_wrong_caller_does_not_read_checkpoint(self):
        for command in ('preflight', 'request'):
            with self.subTest(command=command), fixture() as f:
                f.cp.unlink()
                with patch.dict(os.environ, {'HERDR_PANE_ID': 'other'}):
                    with self.assertRaisesRegex(s.Refused, 'caller pane'):
                        if command == 'preflight': s.preflight(f.h, f.root, 'p1', 'old', f.cp)
                        else: s.create(f.h, f.root, 'p1', 'old', f.cp, 'next')

    def test_missing_caller_identity_fails_closed(self):
        for command in ('preflight', 'request'):
            with self.subTest(command=command), fixture() as f:
                with patch.dict(os.environ, {}, clear=True):
                    with self.assertRaisesRegex(s.Refused, 'HERDR_PANE_ID'):
                        if command == 'preflight': s.preflight(f.h, f.root, 'p1', 'old', f.cp)
                        else: s.create(f.h, f.root, 'p1', 'old', f.cp, 'next')
                self.assertFalse((f.root / 'requests').exists())

    def test_correct_pane_still_requires_its_current_live_session(self):
        with fixture() as f, patch.dict(os.environ, {'HERDR_PANE_ID': 'p1'}):
            f.h.sid = 'different-live-session'
            with self.assertRaisesRegex(s.Refused, 'target or session changed'):
                s.create(f.h, f.root, 'p1', 'old', f.cp, 'next')
            self.assertFalse((f.root / 'requests').exists())

    def test_matching_caller_can_schedule_and_resume(self):
        with fixture() as f, patch.dict(os.environ, {'HERDR_PANE_ID': 'p1'}):
            f.request()
            self.assertEqual(f.run_request()['outcome'], 'resumed')
