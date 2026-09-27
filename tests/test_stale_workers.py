import json
import time
import unittest
from datetime import datetime, timezone

from test_review_fixes import fixture
import switch as s


def event(f, name, **kw):
    return s.hook(f.root, 'p1', dict(hook_event_name=name, session_id='old', **kw))


def stopped(wid='worker-1'):
    return {'message': 'Successfully stopped task: ' + wid + ' (test)',
            'task_id': wid, 'task_type': 'local_agent'}


def stop_call(f, response=None, failure=False):
    event(f, 'PreToolUse', tool_use_id='stop-1', tool_name='TaskStop', tool_input={'task_id': 'worker-1'})
    event(f, 'PostToolUseFailure' if failure else 'PostToolUse', tool_use_id='stop-1',
          tool_name='TaskStop', tool_input={'task_id': 'worker-1'}, tool_response=response or stopped())


def stamp(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def transcript(f):
    path = f.root / 'old.jsonl'
    t = time.time()
    rows = [dict(type='assistant', sessionId='old', uuid='a1', timestamp=stamp(t),
                 message={'content': [{'type': 'tool_use', 'id': 't1', 'name': 'TaskStop', 'input': {'task_id': 'worker-1'}}]}),
            dict(type='user', sessionId='old', timestamp=stamp(t + .001),
                 sourceToolAssistantUUID='a1', toolUseResult=stopped(),
                 message={'content': [{'type': 'tool_result', 'tool_use_id': 't1'}]})]
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    event(f, 'Stop', transcript_path=str(path))
    return path, rows


class StaleWorkerTests(unittest.TestCase):
    def test_successful_taskstop_without_subagentstop_unblocks(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='worker-1')
            stop_call(f)
            self.assertEqual(s.telemetry(f.root, 'p1', 'old')['workers'], {})
            f.request()
            self.assertEqual(f.run_request()['outcome'], 'resumed')

    def test_stop_failures_and_wrong_identity_remain_blocked(self):
        cases = [(stopped(), True), ({**stopped(), 'task_type': 'local_bash'}, False),
                 (stopped('worker-2'), False), ({**stopped(), 'message': 'failed'}, False), ('stopped', False)]
        for response, failure in cases:
            with self.subTest(response=response), fixture() as f:
                event(f, 'SubagentStart', agent_id='worker-1')
                stop_call(f, response, failure)
                f.request()
                self.assertIn('worker-1', f.run_request()['reason'])
                self.assertEqual(f.h.sent, [])

    def test_late_stop_result_does_not_remove_new_generation(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'PreToolUse', tool_use_id='stop-1', tool_name='TaskStop', tool_input={'task_id': 'worker-1'})
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'PostToolUse', tool_use_id='stop-1', tool_name='TaskStop', tool_input={'task_id': 'worker-1'}, tool_response=stopped())
            self.assertIn('worker-1', s.telemetry(f.root, 'p1', 'old')['workers'])

    def test_completed_agent_result_clears_missing_stop(self):
        with fixture() as f:
            event(f, 'PreToolUse', tool_use_id='agent-1', tool_name='Agent')
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'PostToolUse', tool_use_id='agent-1', tool_name='Agent', tool_response={'status': 'completed', 'agentId': 'worker-1'})
            f.request()
            self.assertEqual(f.run_request()['outcome'], 'resumed')

    def test_late_agent_completion_does_not_remove_new_generation(self):
        with fixture() as f:
            event(f, 'PreToolUse', tool_use_id='agent-1', tool_name='Agent')
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'PostToolUse', tool_use_id='agent-1', tool_name='Agent', tool_response={'status':'completed', 'agentId':'worker-1'})
            self.assertIn('worker-1', s.telemetry(f.root, 'p1', 'old')['workers'])

    def test_stop_without_matching_pre_event_keeps_worker(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'PostToolUse', tool_use_id='missing', tool_name='TaskStop', tool_input={'task_id':'worker-1'}, tool_response=stopped())
            self.assertIn('worker-1', s.telemetry(f.root, 'p1', 'old')['workers'])

    def test_unverified_agent_completion_preserves_worker(self):
        for kind in ('async_completed', 'wrong_resume', 'missing_pre'):
            with self.subTest(kind=kind), fixture() as f:
                if kind != 'missing_pre':
                    event(f, 'PreToolUse', tool_use_id='agent-1', tool_name='Agent')
                event(f, 'SubagentStart', agent_id='worker-1')
                response = {'status':'completed', 'agentId':'worker-1'}
                if kind == 'async_completed':
                    response['isAsync'] = True
                event(f, 'PostToolUse', tool_use_id='agent-1', tool_name='Agent',
                      tool_input={'resume':'worker-2'} if kind == 'wrong_resume' else {},
                      tool_response=response)
                self.assertIn('worker-1', s.telemetry(f.root, 'p1', 'old')['workers'])

    def test_async_launch_never_means_finished(self):
        with fixture() as f:
            event(f, 'PreToolUse', tool_use_id='agent-1', tool_name='Agent')
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'PostToolUse', tool_use_id='agent-1', tool_name='Agent', tool_response={'status': 'async_launched', 'agentId': 'worker-1'})
            f.request()
            self.assertEqual(f.run_request()['outcome'], 'not_cleared')

    def test_parent_transcript_repairs_legacy_without_mutating_evidence(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='worker-1')
            path, _ = transcript(f)
            before = path.read_bytes()
            f.request()
            self.assertEqual(f.run_request()['outcome'], 'resumed')
            self.assertEqual(path.read_bytes(), before)

    def test_transcript_unknown_never_retires_worker(self):
        for kind in ('missing', 'bad_json', 'partial', 'wrong_session', 'sidechain', 'error', 'unpaired', 'wrong_source', 'oversize', 'quoted', 'interrupted'):
            with self.subTest(kind=kind), fixture() as f:
                event(f, 'SubagentStart', agent_id='worker-1')
                path, rows = transcript(f)
                if kind == 'missing': path.unlink()
                elif kind == 'bad_json': path.write_text('{bad}\n')
                elif kind == 'partial': path.write_text(path.read_text().rstrip('\n'))
                elif kind == 'oversize': path.write_bytes(b' ' * (s.WORKER_TRANSCRIPT_LIMIT + 1))
                elif kind == 'quoted': path.write_text(json.dumps(dict(type='user', sessionId='old', message={'content': str(rows)}))+'\n')
                elif kind == 'interrupted': path.write_text(json.dumps(dict(type='user', sessionId='old', message={'content':'[Request interrupted by user]'}))+'\n')
                else:
                    if kind == 'wrong_session': rows[1]['sessionId'] = 'other'
                    if kind == 'sidechain': rows[1]['isSidechain'] = True
                    if kind == 'error': rows[1]['message']['content'][0]['is_error'] = True
                    if kind == 'unpaired': rows.pop(0)
                    if kind == 'wrong_source': rows[1]['sourceToolAssistantUUID'] = 'other'
                    path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                f.request()
                self.assertEqual(f.run_request()['outcome'], 'not_cleared')
                self.assertEqual(f.h.sent, [])

    def test_later_resume_or_new_generation_invalidates_old_terminal(self):
        for kind in ('Agent', 'SendMessage', 'generation'):
            with self.subTest(kind=kind), fixture() as f:
                event(f, 'SubagentStart', agent_id='worker-1')
                path, rows = transcript(f)
                if kind == 'generation':
                    s.hook(f.root, 'p1', dict(hook_event_name='SubagentStart',session_id='old',agent_id='worker-1'), now=time.time()+.01)
                else:
                    rows.append(dict(type='assistant', sessionId='old', uuid='a2', timestamp=stamp(time.time()+.01), message={'content':[dict(type='tool_use',id='resume-1',name=kind,input={'resume':'worker-1'} if kind=='Agent' else {'to':'worker-1'})]}))
                    path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
                f.request()
                self.assertEqual(f.run_request()['outcome'], 'not_cleared')

    def test_transcript_changes_during_input_read_refuse(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='worker-1')
            path, _ = transcript(f)
            f.request()
            f.h.read_effect = lambda _: path.write_text(path.read_text()+'{}\n')
            self.assertFalse(s.readiness(f.h, f.r, 'old', after_stop=True)[0])

    def test_stale_telemetry_still_names_workers_at_deadline(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='worker-1')
            f.request()
            path = s.telemetry_path(f.root, 'p1', 'old')
            t = s.load(path); t['updated_at'] -= 130; s.atomic(path, t)
            result = f.run_request()
            self.assertIn('stale', result['reason'])
            self.assertIn('worker-1', result['reason'])
            self.assertEqual(f.h.sent, [])

    def test_stop_preserves_others_and_records_identity(self):
        with fixture() as f:
            event(f, 'SubagentStart', agent_id='worker-1')
            event(f, 'SubagentStop', agent_id='summary-agent', agent_type='away_summary')
            t = s.telemetry(f.root, 'p1', 'old')
            self.assertIn('worker-1', t['workers'])
            self.assertEqual(t['last_worker_stop']['agent_id'], 'summary-agent')

    def _assert_transcript_resume_order(self, tool, layout, fresh=None, completed_first=False):
        with fixture() as f:
            at = time.time() - 10
            s.hook(f.root, 'p1', dict(hook_event_name='SubagentStart',
                   session_id='old', agent_id='worker-1'), now=at-1)
            stop = dict(type='tool_use', id='stop-1', name='TaskStop',
                        input={'task_id': 'worker-1'})
            resume = dict(type='tool_use', id='resume-1', name=tool,
                          input={'resume': 'worker-1'} if tool == 'Agent' else {'to': 'worker-1'})

            def assistant(uid, when, blocks):
                return dict(type='assistant', sessionId='old', uuid=uid,
                            timestamp=stamp(when), message={'content': blocks})

            def result(uid, call, when):
                return dict(type='user', sessionId='old', timestamp=stamp(when),
                            sourceToolAssistantUUID=uid, toolUseResult=stopped(),
                            message={'content': [dict(type='tool_result', tool_use_id=call)]})

            rows = [assistant('a1', at, [stop])]
            old_result = result('a1', 'stop-1', at+1)
            if completed_first:
                rows.append(old_result)
            if layout == 'same_row':
                rows[0]['message']['content'].append(resume)
            else:
                rows.append(assistant('a2', at, [resume]))
            if not completed_first:
                rows.append(old_result)
            if fresh is not None:
                call_time = at if fresh == 'equal_time' else at+2
                result_time = at+3
                if fresh == 'clock_rollback':
                    call_time = at-.5
                elif fresh == 'result_before_call':
                    result_time = at+1
                elif fresh == 'future_result':
                    result_time = time.time()+60
                rows += [assistant('a3', call_time, [{**stop, 'id': 'stop-2'}]),
                         result('a3', 'stop-2', result_time)]
            path = f.root / 'old.jsonl'
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            original = path.read_bytes()
            event(f, 'Stop', transcript_path=str(path))
            f.request()
            expected_ready = fresh in ('equal_time', 'later_time')
            workers, version = s.remaining_workers(s.telemetry(f.root, 'p1', 'old'))
            self.assertIsNotNone(version)
            self.assertEqual('worker-1' not in workers, expected_ready)
            ready, reason = s.readiness(f.h, f.r, 'old', after_stop=True)
            self.assertEqual(ready, expected_ready, reason)
            outcome = f.run_request()
            self.assertEqual(outcome['outcome'], 'resumed' if expected_ready else 'not_cleared')
            self.assertEqual(f.h.sent.count('/clear'), int(expected_ready))
            if not expected_ready:
                self.assertEqual(f.h.sent, [])
                self.assertIn('worker-1', outcome['reason'])
            self.assertEqual(path.read_bytes(), original)

    def test_same_row_resume_invalidates_pending_stop(self):
        for tool in ('Agent', 'SendMessage'):
            with self.subTest(tool=tool):
                self._assert_transcript_resume_order(tool, 'same_row')

    def test_equal_time_resume_row_invalidates_pending_stop(self):
        for tool in ('Agent', 'SendMessage'):
            with self.subTest(tool=tool):
                self._assert_transcript_resume_order(tool, 'separate_row')

    def test_fresh_stop_after_resume_can_reset(self):
        for tool in ('Agent', 'SendMessage'):
            for layout in ('same_row', 'separate_row'):
                for fresh in ('equal_time', 'later_time'):
                    with self.subTest(tool=tool, layout=layout, fresh=fresh):
                        self._assert_transcript_resume_order(tool, layout, fresh)

    def test_equal_time_resume_invalidates_completed_stop(self):
        for tool in ('Agent', 'SendMessage'):
            with self.subTest(tool=tool):
                self._assert_transcript_resume_order(tool, 'separate_row', completed_first=True)

    def test_position_order_does_not_replace_timestamp_guards(self):
        for tool in ('Agent', 'SendMessage'):
            for fresh in ('clock_rollback', 'result_before_call', 'future_result'):
                with self.subTest(tool=tool, fresh=fresh):
                    self._assert_transcript_resume_order(tool, 'same_row', fresh)
