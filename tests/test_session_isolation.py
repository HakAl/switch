import contextlib
import copy
import json
from pathlib import Path
import time
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch

import switch as s
import switch_auto as a
import test_switch as base
import test_switch_auto as auto_base
from test_review_fixes import fixture


@contextlib.contextmanager
def auto_fixture():
    f = auto_base.AutoTests()
    f.setUp()
    try:
        yield f
    finally:
        f.doCleanups()


def child_events(root, pane, sid='child', source='startup'):
    s.hook(root, pane, {'hook_event_name':'SessionStart','session_id':sid,'source':source,'cwd':str(root)})
    s.hook(root, pane, {'hook_event_name':'Stop','session_id':sid})


class IsolationTests(unittest.TestCase):
    def test_parent_lifecycle_survives_nested_session_and_resets(self):
        with fixture() as f:
            f.request()
            s.hook(f.root,'p1',{'hook_event_name':'PreToolUse','session_id':'old','tool_use_id':'nested','tool_name':'Bash'})
            child_events(f.root,'p1')
            self.assertFalse(s.readiness(f.h,f.r,'old',after_stop=True)[0])
            s.hook(f.root,'p1',{'hook_event_name':'PostToolUse','session_id':'old','tool_use_id':'nested'})
            s.hook(f.root,'p1',{'hook_event_name':'Stop','session_id':'old'})
            self.assertTrue(s.readiness(f.h,f.r,'old',after_stop=True)[0])
            self.assertEqual(f.run_request()['outcome'],'resumed')
            self.assertEqual(f.h.sent.count('/clear'),1)

    def test_nested_start_during_reset_does_not_steal_continuation(self):
        for source in ('startup','clear'):
            with self.subTest(source=source), fixture() as f:
                f.request()
                original = f.h.prompt
                def interleaved(pane,text):
                    if text == '/clear': child_events(f.root,pane,source=source)
                    return original(pane,text)
                with patch.object(f.h,'prompt',side_effect=interleaved):
                    result=f.run_request()
                self.assertEqual(result['outcome'],'resumed',result.get('reason'))
                pending=s.load(f.root/'panes/p1.pending.json')
                self.assertEqual(pending['consumed_session'],'new')
                self.assertEqual(len(f.h.sent),2)

    def test_parent_measurement_survives_child_status_updates(self):
        with auto_fixture() as f:
            f.start()
            parent_data=f.sample()
            a.handle_hook(f.manifest,f.event('SessionStart','child',source='startup'))
            child=copy.deepcopy(parent_data); child['session_id']='child'
            child['context_window']['current_usage']['input_tokens']=100
            a.observe(f.c,'p1',child,f.now)
            self.assertIsNotNone(f.auto('PostToolUse'))
            self.assertEqual(f.state()['trigger_measurement']['tokens'],250000)

    def test_malformed_current_observation_invalidates_older_high_sample(self):
        variants=[('cost',1),('cost',[1]),('context_window',[1]),('context_window',1),
                  ('context_window',None)]
        for key,value in variants:
            with self.subTest(key=key,value=value), auto_fixture() as f:
                f.start(); data=f.sample()
                data[key]=value
                with patch.object(a.time,'time',return_value=f.now):
                    a.render_statusline(f.manifest,json.dumps(data).encode())
                self.assertIsNone(f.auto('Stop'))
                self.assertEqual(f.state()['status'],'measurement_unknown_or_stale')

    def test_malformed_other_session_does_not_invalidate_parent(self):
        with auto_fixture() as f:
            f.start(); data=f.sample()
            data.update(session_id='not-started',cost=1)
            a.render_statusline(f.manifest,json.dumps(data).encode())
            self.assertIsNotNone(f.auto('Stop'))

    def test_malformed_observation_preserves_original_statusline_output(self):
        with auto_fixture() as f:
            s.atomic(f.settings,{'statusLine':{'type':'command','command':'cat'}})
            f.start(); data=f.sample(); data['cost']=1
            raw=json.dumps(data).encode()
            with patch.object(a.time,'time',return_value=f.now):
                self.assertEqual(a.render_statusline(f.manifest,raw),raw)
            self.assertIsNone(f.auto('Stop'))

    def test_duplicate_clear_start_preserves_candidate_without_reemitting(self):
        with fixture() as f:
            f.request()
            d=s.request_dir(f.root,f.r['request_id'])
            s.save(d,f.r,'clear_wait',clear_attempted=True,clear_at=time.time())
            pending=f.root/'panes/p1.pending.json'
            s.atomic(pending,{'request_id':f.r['request_id']})
            event={'hook_event_name':'SessionStart','session_id':'new','source':'clear','cwd':str(f.root)}
            self.assertIsNotNone(s.hook(f.root,'p1',event))
            self.assertIsNone(s.hook(f.root,'p1',event))
            self.assertEqual(s.telemetry(f.root,'p1','new')['continuation_request'],f.r['request_id'])
            self.assertNotIn('consumed_session',s.load(pending))

    def test_legacy_pane_record_is_not_adopted_without_new_session_start(self):
        with fixture() as f:
            legacy=s.telemetry(f.root,'p1','old')
            s.atomic(f.root/'panes/p1.json',dict(legacy,session_id='legacy'))
            self.assertEqual(s.telemetry(f.root,'p1','legacy'),{})
            s.hook(f.root,'p1',{'hook_event_name':'Stop','session_id':'legacy'})
            self.assertEqual(s.telemetry(f.root,'p1','legacy'),{})

    def test_non_target_candidate_reports_other_session_confirmation(self):
        with auto_fixture() as f:
            f.start(source='clear')
            state=f.state(); state['bootstrap_request']='r1'
            a.save_auto(f.root,'p1','s1',state)
            s.atomic(s.request_dir(f.root,'r1')/'ack.json',{'session_id':'actual-target','at':90})
            f.sample(10000)
            self.assertIsNone(f.auto('PostToolUse'))
            self.assertEqual(f.state()['status'],'continuation_confirmed_in_other_session')

    def test_installer_discloses_prompt_retention_and_retained_claim(self):
        with auto_fixture() as f:
            dry=a.install('project',f.project,'250k',f.root,True)
            installed=a.install('project',f.project,'250k',f.root)
            updated=a.install('project',f.project,'200k',f.root)
            for result in (dry,installed,updated):
                text=' '.join(result['notices'])
                self.assertIn('verbatim',text)
                self.assertIn('512 KiB',text)
                self.assertIn('not_cleared',text)

    def test_emitted_non_git_checkpoint_contract_passes_request_preflight(self):
        with auto_fixture() as f:
            protocol=f.start()
            self.assertIn('refs (nonempty list',protocol)
            self.assertIn('unversioned',protocol)
            authority=f.project/'operator.md'; authority.write_text('Authorized fixture task until completion.')
            cp=f.root/'auto-checkpoints/s1.json'
            s.atomic(cp,{'task':'fixture','role':'builder','worktree':str(f.project),
                'refs':['unversioned workspace: '+str(f.project)], 'completed':[],
                'unfinished':['write result'],'next_action':'write result','instructions':[],
                'authority_sources':[str(authority)],
                'preparation':{'quiescent':True,'active_tools':[],'workers':[],'waits':[]}})
            h=base.FakeHerdr(f.root); h.sid='s1'
            request=s.create(h,f.root,'p1','s1',cp,'write result')
            self.assertEqual(request['stage'],'scheduled')
