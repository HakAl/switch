"""Subprocess fake, used only by the detached end-to-end test."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, os.environ['SWITCH_CODE'])
import switch as s

root = Path(os.environ['SWITCH_FAKE_ROOT'])
config = s.load(root / 'fake.json')
a = sys.argv[1:]
if a == ['agent', 'list']:
    print(json.dumps({'result': {'agents': [{'pane_id': 'p1', 'terminal_id': 'term-test',
        'agent': 'claude', 'agent_status': 'idle', 'agent_session': {'value': config['sid']}}]}}))
elif a[:2] == ['pane', 'get']:
    print(json.dumps({'result': {'pane': {'pane_id': 'p1', 'scroll': {'offset_from_bottom': 0}}}}))
elif a[:2] == ['pane', 'read']:
    print('body\n' + '─'*24 + '\n❯ \n' + '─'*24 + '\nmanual mode')
elif a[:2] == ['agent', 'prompt']:
    prompt = a[3]
    with open(root/'sends.jsonl', 'a') as f:
        f.write(json.dumps(prompt)+'\n')
    if prompt == '/clear':
        config['sid'] = 'new'
        s.atomic(root/'fake.json', config)
        s.hook(root, 'p1', {'hook_event_name':'SessionStart','session_id':'new',
                          'source':'clear','cwd':str(root),'permission_mode':'auto'})
    else:
        s.hook(root, 'p1', {'hook_event_name':'UserPromptSubmit','session_id':'new','prompt':prompt})
        rid = s.load(root/'panes/p1.pending.json')['request_id']
        r = s.load(s.request_dir(root, rid)/'request.json')
        s.acknowledge(s.Herdr(), root, r['request_id'], 'new', r['checkpoint_sha256'])
    print('{}')
else:
    sys.exit(2)
