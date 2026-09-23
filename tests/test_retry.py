import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_review_fixes import fixture
import switch as s
import switch_auto as a


def cancel(f):
    f.request()
    s.hook(f.root, 'p1', {'hook_event_name': 'UserPromptSubmit',
                         'session_id': 'old', 'prompt': 'continue'})
    s.hook(f.root, 'p1', {'hook_event_name': 'Stop', 'session_id': 'old'})
    return f.run_request()


def retry(f, rid):
    return s.create(f.h, f.root, 'p1', 'old', f.cp, 'write result', 2, 2, 2,
                    retry_of=rid)


class RetryTests(unittest.TestCase):
    def test_explicit_retry_keeps_automatic_feedback_suppressed(self):
        with fixture() as f:
            c = {'root': str(f.root), 'limit': a.limit('1')}
            def event(name, **extra):
                return a.auto_event(c, 'p1', dict(hook_event_name=name, session_id='old', **extra))
            protocol = event('SessionStart', source='startup')
            self.assertIn('--retry-of', protocol)
            event('PreToolUse', tool_name='Bash', tool_input={'command': f'{sys.executable} {s.__file__} request'})
            old = cancel(f)
            self.assertIsNone(event('Stop'))
            self.assertIsNotNone(a.auto_state(f.root, 'p1', 'old')['attempted_at'])
            new = retry(f, old['request_id'])
            self.assertIsNone(event('Stop'))
            self.assertEqual(a.auto_state(f.root, 'p1', 'old')['request_id'], new['request_id'])

    def test_cancel_then_explicit_retry_resumes_once_preserving_receipt(self):
        with fixture() as f:
            old = cancel(f)
            self.assertEqual(old['outcome'], 'not_cleared')
            self.assertEqual(f.h.sent, [])
            old_path = s.request_dir(f.root, old['request_id']) / 'request.json'
            before = old_path.read_bytes()
            self.assertTrue(s.inspect(f.root, old['request_id'])['retry_eligible'])
            f.c['next_action'] = 'updated action after user input'
            f.write_cp()
            f.r = retry(f, old['request_id'])
            self.assertEqual(f.r['retry_of'], old['request_id'])
            self.assertGreater(f.r['requested_at'], old['requested_at'])
            self.assertFalse(s.readiness(f.h, f.r, 'old', after_stop=True)[0])
            s.hook(f.root, 'p1', {'hook_event_name': 'Stop', 'session_id': 'old'})
            self.assertEqual(f.run_request()['outcome'], 'resumed')
            self.assertEqual(f.h.sent.count('/clear'), 1)
            self.assertEqual(old_path.read_bytes(), before)
            self.assertEqual(s.checked_checkpoint(s.request_dir(f.root, f.r['request_id']), f.r)['next_action'],
                             f.c['next_action'])
            status = s.inspect(f.root, old['request_id'])
            self.assertFalse(status['retry_eligible'])
            self.assertEqual(status['current_request_id'], f.r['request_id'])
            self.assertIn('superseded', status['retry_reason'])
            s.execute(f.h, f.root, old['request_id'])
            self.assertEqual(f.h.sent.count('/clear'), 1)

    def test_repeated_cancellation_requires_explicit_latest_predecessor(self):
        with fixture() as f:
            old = cancel(f)
            f.r = retry(f, old['request_id'])
            s.hook(f.root, 'p1', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'old', 'prompt': 'wait'})
            again = f.run_request()
            self.assertEqual(again['outcome'], 'not_cleared')
            with self.assertRaisesRegex(s.Refused, 'superseded'):
                retry(f, old['request_id'])
            with self.assertRaisesRegex(s.Refused, 'already claimed'):
                f.request()
            third = retry(f, again['request_id'])
            self.assertEqual(third['retry_of'], again['request_id'])
            self.assertEqual(f.h.sent, [])

    def test_ambiguous_or_malformed_predecessor_never_retries(self):
        variants = [
            {'clear_attempted': True}, {'clear_attempted': None}, {'clear_attempted': 0},
            {'resume_attempted': True}, {'new_session': 'new'}, {'stage': 'waiting_for_stop'},
            {'outcome': 'clear_uncertain'}, {'outcome': 'interrupted_uncertain'},
            {'clear_at': 1}, {'resume_at': 1}, {'clear_send_returned': False},
            {'history': []}, {'history': [{'stage': 'clear_sending', 'at': 1}]},
            {'history': None}, {'history': [None]}, {'requested_at': 'bad'},
            {'root': '/different-root'}, {'request_id': 'other'},
        ]
        for fields in variants:
            with self.subTest(fields=fields), fixture() as f:
                old = cancel(f)
                path = s.request_dir(f.root, old['request_id']) / 'request.json'
                s.atomic(path, dict(old, **fields))
                with self.assertRaises(s.Refused):
                    retry(f, old['request_id'])
                self.assertEqual(f.h.sent, [])
        for key in ('clear_attempted', 'resume_attempted', 'new_session', 'history', 'terminal_id'):
            with self.subTest(missing=key), fixture() as f:
                old = cancel(f); damaged = dict(old); del damaged[key]
                s.atomic(s.request_dir(f.root, old['request_id']) / 'request.json', damaged)
                with self.assertRaises(s.Refused): retry(f, old['request_id'])

    def test_failed_clear_send_stays_ineligible(self):
        with fixture() as f:
            f.request(); f.h.clear_effect = False; f.h.clear_ok = False
            old = f.run_request()
            self.assertEqual(old['outcome'], 'clear_uncertain')
            with self.assertRaises(s.Refused): retry(f, old['request_id'])
            self.assertEqual(f.h.sent, ['/clear'])

    def test_retry_revalidates_identity_checkpoint_and_worker_locks(self):
        with fixture() as f:
            old = cancel(f); rid = old['request_id']
            f.h.terminal = 'replaced'
            with self.assertRaises(s.Refused): retry(f, rid)
            f.h.terminal = 'term-test'
            f.c['preparation']['workers'] = ['active']; f.write_cp()
            with self.assertRaises(s.Refused): retry(f, rid)
            f.c['preparation']['workers'] = []; f.write_cp()
            for path in (f.root / 'claim.lock', f.root / 'panes/p1.reset.lock',
                         s.request_dir(f.root, rid) / 'worker.lock'):
                with self.subTest(lock=path.name), s.lock(path):
                    with self.assertRaisesRegex(s.Refused, 'temporarily.*busy'):
                        retry(f, rid)
            self.assertEqual(f.h.sent, [])

    def test_concurrent_retries_have_one_owner(self):
        with fixture() as f:
            old = cancel(f)
            def attempt():
                try: return retry(f, old['request_id'])
                except s.Refused: return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: attempt(), range(2)))
            self.assertEqual(sum(r is not None for r in results), 1)

    def test_failed_claim_publication_leaves_unsendable_orphan(self):
        with fixture() as f:
            old = cancel(f)
            real_atomic = s.atomic
            def fail_claim(path, data):
                if Path(path).parent.name == 'claims': raise OSError('injected publication failure')
                real_atomic(path, data)
            with patch.object(s, 'atomic', side_effect=fail_claim):
                with self.assertRaises(OSError): retry(f, old['request_id'])
            orphan = next(p for p in (f.root / 'requests').iterdir() if p.name != old['request_id'])
            result = s.execute(f.h, f.root, orphan.name)
            self.assertEqual(result['outcome'], 'not_cleared')
            self.assertIn('ownership', result['reason'])
            self.assertFalse(s.inspect(f.root, orphan.name)['retry_eligible'])
            self.assertTrue(s.inspect(f.root, old['request_id'])['retry_eligible'])
            self.assertEqual(f.h.sent, [])

    def test_crash_after_publication_retains_claim_and_refuses_retry(self):
        with fixture() as f:
            old = cancel(f)
            new = retry(f, old['request_id'])
            with patch.object(s.time, 'time', return_value=new['requested_at'] + 11):
                status = s.inspect(f.root, new['request_id'])
            self.assertEqual(status['outcome'], 'interrupted_uncertain')
            self.assertFalse(status['retry_eligible'])
            with self.assertRaises(s.Refused): retry(f, new['request_id'])

    def test_cli_launch_failure_is_retryable_and_recovery_names_cause(self):
        with fixture() as f:
            args = ['request', '--state-dir', str(f.root), '--pane', 'p1', '--session', 'old',
                    '--checkpoint', str(f.cp), '--resume', 'write result']
            with patch.object(s, 'Herdr', return_value=f.h), patch.object(s.subprocess, 'Popen', side_effect=OSError('launch failed')):
                with patch('sys.stderr'):
                    self.assertEqual(s.main(args), 3)
            old = s.load(next((f.root / 'requests').glob('*/request.json')))
            self.assertTrue(s.inspect(f.root, old['request_id'])['retry_eligible'])
            self.assertNotIn('New input', old['recovery'])
            retry(f, old['request_id'])

    def test_cli_detached_cancel_then_retry(self):
        with fixture() as f:
            code = Path(s.__file__).parent
            binary = f.root / 'bin'; binary.mkdir()
            shim = binary / 'herdr'
            shim.write_text('#!' + sys.executable + '\n' + (Path(__file__).parent / 'fake_herdr.py').read_text())
            shim.chmod(0o700)
            s.atomic(f.root / 'fake.json', {'sid': 'old'})
            env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                       SWITCH_CODE=str(code), SWITCH_FAKE_ROOT=str(f.root), PYTHONDONTWRITEBYTECODE='1')
            cmd = [sys.executable, '-B', str(code / 'switch.py'), 'request', '--state-dir', str(f.root),
                   '--pane', 'p1', '--session', 'old', '--checkpoint', str(f.cp), '--resume', 'write result',
                   '--idle-deadline', '5', '--clear-deadline', '5', '--ack-deadline', '5']
            def launch(extra=()):
                p = subprocess.run(cmd + list(extra), env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(p.returncode, 0, p.stderr)
                return json.loads(p.stdout)['request_id']
            def finish(rid):
                end = time.monotonic() + 12
                while time.monotonic() < end:
                    r = s.load(s.request_dir(f.root, rid) / 'request.json')
                    if r.get('outcome'): return r
                    time.sleep(0.05)
                self.fail('detached helper did not finish')
            old = launch()
            s.hook(f.root, 'p1', {'hook_event_name': 'UserPromptSubmit', 'session_id': 'old', 'prompt': 'continue'})
            self.assertEqual(finish(old)['outcome'], 'not_cleared')
            new = launch(['--retry-of', old])
            s.hook(f.root, 'p1', {'hook_event_name': 'Stop', 'session_id': 'old'})
            self.assertEqual(finish(new)['outcome'], 'resumed')
            sends = [json.loads(line) for line in (f.root / 'sends.jsonl').read_text().splitlines()]
            self.assertEqual(sends.count('/clear'), 1)
            self.assertEqual(len(sends), 2)
