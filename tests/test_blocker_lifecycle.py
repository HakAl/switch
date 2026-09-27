"""Blocker-class consumers; no live pane, production state or reset."""
import json
from pathlib import Path
import unittest

from test_review_fixes import fixture
from test_stale_workers import event
import switch as s


class BlockerLifecycleTests(unittest.TestCase):
    def test_historical_denied_tools_clear_at_parent_stop(self):
        # Request-time inventories included the successful request Bash itself.
        cases = {'three_denials': ('Bash', 'Write', 'Bash'),
                 'two_denials': ('Bash', 'Write')}
        for request, denied in cases.items():
            with self.subTest(request=request), fixture() as f:
                for i, tool in enumerate(denied):
                    event(f, 'PreToolUse', tool_use_id=f'denied-{i}', tool_name=tool)
                event(f, 'PreToolUse', tool_use_id='request', tool_name='Bash')
                event(f, 'PostToolUse', tool_use_id='request', tool_name='Bash')
                self.assertEqual(len(s.telemetry(f.root, 'p1', 'old')['tools']), len(denied))
                # No matching post events were observed for the denied calls.
                f.request()
                t = s.telemetry(f.root, 'p1', 'old')
                self.assertEqual(t['tools'], {})
                self.assertEqual(t['workers'], {})
                self.assertFalse(t['blocked'])
                self.assertEqual(f.run_request()['outcome'], 'resumed')
                self.assertEqual(f.h.sent.count('/clear'), 1)

    def test_parent_success_closes_only_matching_tool(self):
        with fixture() as f:
            for tid in ('one', 'two'):
                event(f, 'PreToolUse', tool_use_id=tid, tool_name='Bash')
            event(f, 'PostToolUse', tool_use_id='one', tool_name='Bash')
            self.assertEqual(s.telemetry(f.root, 'p1', 'old')['tools'], {'two': 'Bash'})
            event(f, 'PostToolUse', tool_use_id='two', tool_name='Bash')
            self.assertEqual(s.telemetry(f.root, 'p1', 'old')['tools'], {})
            f.request()
            self.assertEqual(f.run_request()['outcome'], 'resumed')

    def test_failed_or_interrupted_parent_call_releases_own_entry(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted), fixture() as f:
                event(f, 'PreToolUse', tool_use_id='failed', tool_name='Bash')
                event(f, 'PostToolUseFailure', tool_use_id='failed', tool_name='Bash',
                      error='Controlled failure', is_interrupt=interrupted)
                self.assertEqual(s.telemetry(f.root, 'p1', 'old')['tools'], {})
                f.request()
                self.assertEqual(f.run_request()['outcome'], 'resumed')

    def test_permission_completion_or_parent_stop_releases_latch(self):
        for close in ('PostToolUse', 'PostToolUseFailure', 'Stop'):
            with self.subTest(close=close), fixture() as f:
                event(f, 'PreToolUse', tool_use_id='permission', tool_name='Write')
                event(f, 'PermissionRequest', tool_name='Write')
                self.assertTrue(s.telemetry(f.root, 'p1', 'old')['blocked'])
                if close != 'Stop':
                    event(f, close, tool_use_id='permission', tool_name='Write')
                    self.assertFalse(s.telemetry(f.root, 'p1', 'old')['blocked'])
                f.request()
                self.assertFalse(s.telemetry(f.root, 'p1', 'old')['blocked'])
                self.assertEqual(f.run_request()['outcome'], 'resumed')

    def test_unresolved_permission_remains_blocking(self):
        with fixture() as f:
            f.request()
            event(f, 'PermissionRequest', tool_name='Write')
            self.assertTrue(s.telemetry(f.root, 'p1', 'old')['blocked'])
            self.assertFalse(s.readiness(f.h, f.r, 'old')[0])
            self.assertEqual(f.run_request()['outcome'], 'not_cleared')
            self.assertEqual(f.h.sent, [])

    def test_child_tool_stop_and_permission_events_do_not_mutate_parent(self):
        with fixture() as f:
            event(f, 'PreToolUse', tool_use_id='parent', tool_name='Bash')
            event(f, 'PermissionRequest', tool_name='Bash')
            before = s.telemetry(f.root, 'p1', 'old')
            for name in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure',
                         'PermissionRequest', 'Stop', 'UserPromptSubmit'):
                event(f, name, agent_id='child', tool_use_id='child-tool', tool_name='Write')
                self.assertEqual(s.telemetry(f.root, 'p1', 'old'), before)

    def test_denied_child_tool_does_not_survive_completed_worker(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='child')
            event(f, 'PreToolUse', agent_id='child', tool_use_id='denied', tool_name='Write')
            # No child post follows a hook denial, but no parent tool was opened.
            f.request()
            self.assertEqual(s.telemetry(f.root, 'p1', 'old')['tools'], {})
            event(f, 'Stop', agent_id='child')
            self.assertFalse(s.readiness(f.h, f.r, 'old', after_stop=True)[0])
            event(f, 'SubagentStop', agent_id='child')
            self.assertEqual(f.run_request()['outcome'], 'resumed')

    def test_live_background_worker_outlives_parent_stop_and_deadline(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='live-worker')
            f.request()
            result = f.run_request()
            self.assertEqual(result['outcome'], 'not_cleared')
            self.assertIn('live-worker', result['reason'])
            self.assertIn('live-worker', s.telemetry(f.root, 'p1', 'old')['workers'])
            self.assertEqual(f.h.sent, [])

    def test_resumed_worker_is_live_until_its_next_terminal_event(self):
        for finish in (False, True):
            with self.subTest(finish=finish), fixture() as f:
                event(f, 'SubagentStart', agent_id='worker')
                first = s.telemetry(f.root, 'p1', 'old')['workers']['worker']
                event(f, 'SubagentStop', agent_id='worker')
                event(f, 'SubagentStart', agent_id='worker')
                self.assertGreater(s.telemetry(f.root, 'p1', 'old')['workers']['worker'], first)
                if finish:
                    event(f, 'SubagentStop', agent_id='worker')
                f.request()
                self.assertEqual(f.run_request()['outcome'], 'resumed' if finish else 'not_cleared')
                self.assertEqual(f.h.sent.count('/clear'), int(finish))

    def test_agent_call_failure_does_not_prove_worker_ended(self):
        for terminal in (False, True):
            with self.subTest(terminal=terminal), fixture() as f:
                event(f, 'PreToolUse', tool_use_id='agent', tool_name='Agent')
                event(f, 'SubagentStart', agent_id='unknown-worker')
                event(f, 'PostToolUseFailure', tool_use_id='agent', tool_name='Agent',
                      error='Agent call failed; child outcome unknown')
                if terminal:
                    event(f, 'SubagentStop', agent_id='unknown-worker')
                f.request()
                self.assertEqual(f.run_request()['outcome'], 'resumed' if terminal else 'not_cleared')
                self.assertEqual(f.h.sent.count('/clear'), int(terminal))

    def test_captured_child_failure_denial_completion_and_resume(self):
        capture = json.loads((Path(__file__).parent/'fixtures/blocker-hooks-2.1.283.json').read_text())
        self.assertEqual(capture['version'], '2.1.283')
        with fixture() as f:
            starts, stops, denied, post_ids, failures = [], [], [], set(), []
            for captured in capture['events']:
                e = dict(captured)
                observed = e.pop('_observed_at')
                e['session_id'] = 'old'  # Fixture IDs/times are synthetic; adapt session/cwd for isolation.
                if e['hook_event_name'] == 'SessionStart':
                    e['cwd'] = str(f.root)
                before = s.telemetry(f.root, 'p1', 'old')
                s.hook(f.root, 'p1', e, now=observed)
                after = s.telemetry(f.root, 'p1', 'old')
                name, agent = e['hook_event_name'], e.get('agent_id')
                if agent and name not in ('SubagentStart', 'SubagentStop'):
                    self.assertEqual(after, before)
                if name == 'SubagentStart':
                    starts.append(agent)
                    self.assertIn(agent, after['workers'])
                if name == 'SubagentStop':
                    stops.append(agent)
                    self.assertNotIn(agent, after['workers'])
                if name == 'PreToolUse' and e.get('tool_name') == 'Write':
                    denied.append(e['tool_use_id'])
                if name in ('PostToolUse', 'PostToolUseFailure'):
                    post_ids.add(e['tool_use_id'])
                if name == 'PostToolUseFailure':
                    failures.append(e)
            self.assertEqual(len(starts), 2)
            self.assertEqual(starts[0], starts[1])
            self.assertEqual(starts, stops)
            self.assertEqual(len(failures), 1)
            self.assertIs(failures[0]['is_interrupt'], False)
            self.assertEqual(len(denied), 1)
            self.assertNotIn(denied[0], post_ids)
            self.assertEqual(after['workers'], {})
            self.assertEqual(after['tools'], {})
            self.assertFalse(after['blocked'])
            # Keep the capture's mode across the fake reset, as acknowledgment requires.
            f.h.new_mode = after['permission_mode']
            f.request()
            self.assertEqual(f.run_request()['outcome'], 'resumed')
