import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import switch as s


def screen(text="", continuation=""):
    return "body\n" + "─" * 24 + "\n❯ " + text + "\n" + continuation + "─" * 24 + "\n  auto mode on\n"


class Clock:
    def __init__(self):
        self.t = 0
        self.on_sleep = None

    def now(self):
        return self.t

    def sleep(self, value):
        self.t += value
        if self.on_sleep:
            self.on_sleep()


class FakeHerdr:
    def __init__(self, root):
        self.root = root
        self.sid = "old"
        self.status = "idle"
        self.terminal = "term-test"
        self.agent_kind = "claude"
        self.output = screen()
        self.sent = []
        self.clear_effect = True
        self.clear_ok = True
        self.resume_ok = True
        self.submit = True
        self.ack = True
        self.read_effect = None
        self.clear_hook = "clear"
        self.post_clear_output = None
        self.new_mode = None
        self.agent_calls = 0
        self.agent_effect = None

    def agent(self, pane):
        self.agent_calls += 1
        if self.agent_effect:
            self.agent_effect(self)
        return {"pane_id": pane, "agent": self.agent_kind, "agent_status": self.status,
                "terminal_id": self.terminal, "agent_session": {"value": self.sid}}

    def read(self, pane):
        if self.read_effect:
            self.read_effect(self)
        return self.output

    def prompt(self, pane, text):
        self.sent.append(text)
        if text == "/clear":
            if self.clear_effect:
                self.clear()
            return self.clear_ok
        if self.submit:
            s.hook(self.root, pane, {"hook_event_name": "UserPromptSubmit", "session_id": self.sid,
                                    "prompt": text})
        if self.ack:
            r = next((Path(self.root) / "requests").glob("*/request.json"))
            data = s.load(r)
            s.acknowledge(self, self.root, data["request_id"], self.sid, data["checkpoint_sha256"])
        return self.resume_ok

    def clear(self):
        self.sid = "new"
        s.hook(self.root, "p1", {"hook_event_name": "SessionStart", "session_id": self.sid,
                               "source": self.clear_hook, "cwd": str(self.root),
                               "permission_mode": self.new_mode or "auto", "model": "test-model"})
        if self.post_clear_output is not None:
            self.output = self.post_clear_output


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.h = FakeHerdr(self.root)
        self.cp = self.root / "source.json"
        self.auth = self.root / "operator.md"
        self.auth.write_text("Operator authorizes this harmless test until it completes.")
        self.c = {"task": "test", "role": "builder", "worktree": str(self.root),
                  "refs": ["unversioned fixture"], "completed": [], "unfinished": ["write result"],
                  "next_action": "write result", "instructions": [], "authority_sources": [str(self.auth)],
                  "preparation": {"quiescent": True, "active_tools": [], "workers": [], "waits": []}}
        self.write_cp()
        s.hook(self.root, "p1", {"hook_event_name": "SessionStart", "session_id": "old",
                               "source": "startup", "cwd": str(self.root),
                               "permission_mode": "auto", "model": "test-model"})
        self.clock = Clock()

    def tearDown(self):
        self.temp.cleanup()

    def write_cp(self):
        self.cp.write_text(json.dumps(self.c))

    def request(self):
        self.r = s.create(self.h, self.root, "p1", "old", self.cp, "write result", 2, 2, 2)
        s.hook(self.root, "p1", {"hook_event_name": "Stop", "session_id": "old"})
        return self.r

    def run_request(self):
        return s.execute(self.h, self.root, self.r["request_id"], self.clock.now, self.clock.sleep)

    def test_happy_path_and_duplicate_worker_does_not_replay(self):
        self.request()
        result = self.run_request()
        self.assertEqual(result["outcome"], "resumed")
        self.assertEqual(self.h.sent[0], "/clear")
        self.assertEqual(len(self.h.sent), 2)
        self.assertIn("authority_sources", self.h.sent[1])
        self.assertIsNotNone(result["submitted_at"])
        self.run_request()
        self.assertEqual(len(self.h.sent), 2)

    def test_done_and_dim_suggestion(self):
        self.request()
        self.h.status = "done"
        self.h.output = screen("\x1b[2mSuggested next prompt\x1b[22m")
        self.assertEqual(self.run_request()["outcome"], "resumed")

    def test_preflight_read_only_and_unknown_is_unknown(self):
        self.h.output = "no prompt"
        before = sorted(str(p) for p in self.root.rglob("*"))
        info = s.preflight(self.h, self.root, "p1", "old", self.cp)
        self.assertEqual(info["input"], "unknown")
        self.assertIsNone(info["context_occupancy"])
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))
        self.assertEqual(self.h.sent, [])

    def test_missing_checkpoint_and_bad_fields(self):
        self.cp.unlink()
        with self.assertRaises(OSError):
            self.request()
        self.c["role"] = ""
        self.write_cp()
        with self.assertRaises(s.Refused):
            self.request()
        self.assertEqual(self.h.sent, [])

    def test_source_is_copied_and_validated_before_clear(self):
        self.request()
        self.cp.unlink()
        self.assertEqual(self.run_request()["outcome"], "resumed")

    def test_tampered_stored_checkpoint_refuses(self):
        self.request()
        p = s.request_dir(self.root, self.r["request_id"]) / "checkpoint.json"
        c = s.load(p)
        c["next_action"] = "different"
        s.atomic(p, c)
        self.assertEqual(self.run_request()["outcome"], "not_cleared")
        self.assertEqual(self.h.sent, [])

    def test_missing_original_authority_refuses(self):
        self.request()
        self.auth.unlink()
        self.assertEqual(self.run_request()["outcome"], "not_cleared")

    def test_unknown_or_outstanding_resources_refuse_preparation(self):
        for key in ("active_tools", "workers", "waits"):
            with self.subTest(key=key):
                self.c["preparation"][key] = ["running"]
                self.write_cp()
                with self.assertRaises(s.Refused):
                    self.request()
                self.c["preparation"][key] = []
        self.assertEqual(self.h.sent, [])

    def test_duplicate_session_claim_is_persistent(self):
        self.request()
        with self.assertRaisesRegex(s.Refused, "already claimed"):
            self.request()
        self.assertEqual(self.h.sent, [])

    def test_no_stop_after_scheduling_times_out(self):
        s.hook(self.root, "p1", {"hook_event_name": "Stop", "session_id": "old"})
        self.r = s.create(self.h, self.root, "p1", "old", self.cp, "next", 2, 2, 2)
        result = self.run_request()
        self.assertEqual(result["outcome"], "not_cleared")
        self.assertGreater(self.clock.t, 1.8)
        self.assertEqual(self.h.sent, [])

    def test_working_draft_unknown_blocked_and_stale_refuse(self):
        self.request()
        cases = [lambda: setattr(self.h, "status", "working"),
                 lambda: setattr(self.h, "output", screen("operator draft")),
                 lambda: setattr(self.h, "output", None),
                 lambda: setattr(self.h, "status", "blocked")]
        for setup in cases:
            with self.subTest(setup=setup):
                setup()
                ok, why = s.readiness(self.h, self.r, "old", after_stop=True)
                self.assertFalse(ok, why)
                self.h.status, self.h.output = "idle", screen()
        ok, why = s.readiness(self.h, self.r, "old", clock=lambda: time.time() + 200)
        self.assertFalse(ok)
        self.assertIn("stale", why)

    def test_active_tool_and_worker_even_when_herdr_idle(self):
        self.request()
        s.hook(self.root, "p1", {"hook_event_name": "PreToolUse", "session_id": "old",
                               "tool_use_id": "tool-1", "tool_name": "Bash"})
        s.hook(self.root, "p1", {"hook_event_name": "Stop", "session_id": "old"})
        self.assertFalse(s.readiness(self.h, self.r, "old", after_stop=True)[0])
        s.hook(self.root, "p1", {"hook_event_name": "PostToolUse", "session_id": "old", "tool_use_id": "tool-1"})
        s.hook(self.root, "p1", {"hook_event_name": "SubagentStart", "session_id": "old", "agent_id": "worker-1"})
        self.assertFalse(s.readiness(self.h, self.r, "old", after_stop=True)[0])
        s.hook(self.root, "p1", {"hook_event_name": "SubagentStop", "session_id": "old", "agent_id": "worker-1"})
        self.assertTrue(s.readiness(self.h, self.r, "old", after_stop=True)[0])

    def test_changed_target_and_final_recheck(self):
        self.request()
        self.h.read_effect = lambda h: setattr(h, "sid", "other")
        self.assertEqual(self.run_request()["outcome"], "not_cleared")
        self.assertEqual(self.h.sent, [])

    def test_late_old_hook_cannot_replace_new_session(self):
        self.h.clear()
        s.hook(self.root, "p1", {"hook_event_name": "Stop", "session_id": "old"})
        self.assertEqual(s.telemetry(self.root, "p1", "new")["session_id"], "new")

    def test_uncertain_clear_reconciles_and_never_retries(self):
        self.request()
        self.h.clear_ok = False
        self.assertEqual(self.run_request()["outcome"], "resumed")
        self.assertEqual(self.h.sent.count("/clear"), 1)

    def test_delayed_clear(self):
        self.request()
        self.h.clear_effect = False
        self.clock.on_sleep = lambda: self.h.clear() if self.clock.t == 1 else None
        self.assertEqual(self.run_request()["outcome"], "resumed")
        self.assertEqual(self.h.sent.count("/clear"), 1)

    def test_unconfirmed_clear_sends_no_bootstrap(self):
        self.request()
        self.h.clear_effect = False
        result = self.run_request()
        self.assertEqual(result["outcome"], "clear_uncertain")
        self.assertEqual(self.h.sent, ["/clear"])
        self.assertIn("may remain", result["recovery"])

    def test_external_restart_is_not_clear_confirmation(self):
        self.request()
        self.h.clear_hook = "startup"
        self.assertEqual(self.run_request()["outcome"], "clear_uncertain")
        self.assertEqual(self.h.sent, ["/clear"])

    def test_resume_checks_draft_again(self):
        self.request()
        self.h.post_clear_output = screen("new operator draft")
        result = self.run_request()
        self.assertEqual(result["outcome"], "cleared_not_resumed")
        self.assertEqual(self.h.sent, ["/clear"])
        self.assertIn("Do not /clear", result["recovery"])

    def test_failed_resume_send_can_still_be_acknowledged(self):
        self.request()
        self.h.resume_ok = False
        self.assertEqual(self.run_request()["outcome"], "resumed")
        self.assertEqual(len(self.h.sent), 2)

    def test_failed_resume_without_submission(self):
        self.request()
        self.h.submit, self.h.ack, self.h.resume_ok = False, False, False
        result = self.run_request()
        self.assertEqual(result["outcome"], "cleared_not_resumed")
        self.assertNotIn("submitted_at", result)
        self.assertEqual(len(self.h.sent), 2)

    def test_submitted_is_not_acknowledged(self):
        self.request()
        self.h.ack = False
        result = self.run_request()
        self.assertEqual(result["outcome"], "cleared_not_resumed")
        self.assertIn("submitted_at", result)
        self.assertNotIn("acknowledged_at", result)

    def test_wrong_ack_is_rejected(self):
        self.request()
        with self.assertRaises(s.Refused):
            s.acknowledge(self.h, self.root, self.r["request_id"], "old", self.r["checkpoint_sha256"])

    def test_deadlines_validation(self):
        for value in (float("nan"), float("inf"), -1, 0, 3601):
            with self.assertRaises(s.Refused):
                s.create(self.h, self.root, "p1", "old", self.cp, "next", idle=value)

    def test_interrupted_status_never_restarts(self):
        self.request()
        d = s.request_dir(self.root, self.r["request_id"])
        s.save(d, self.r, "clear_sending", clear_attempted=True)
        self.assertEqual(s.inspect(self.root, self.r["request_id"])["outcome"], "interrupted_uncertain")
        self.run_request()
        self.assertEqual(self.h.sent, [])

    def test_hook_config_is_additive_fragment_and_scoped(self):
        config = s.hooks_config(self.root)
        self.assertEqual(set(config), {"hooks"})
        self.assertEqual(set(config["hooks"]), set(s.EVENTS))
        self.assertIn(str(self.root), config["hooks"]["Stop"][0]["hooks"][0]["command"])

    def test_wrapped_bootstrap_submission_is_correlated(self):
        self.request()
        self.h.clear()
        rid = self.r["request_id"]
        text = s.MARKER + rid + "] continue"
        wrapped = '\n\n<pasted_content id="a17b">\n' + text + '\n</pasted_content id="a17b">\n'
        s.hook(self.root, "p1", {"hook_event_name": "UserPromptSubmit", "session_id": "new", "prompt": wrapped})
        submitted = s.telemetry(self.root, "p1", "new")["submitted"]
        self.assertIsNotNone(submitted)
        self.assertEqual(submitted["id"], rid)
        self.assertEqual(submitted["sha256"], s.digest(text.encode()))

    def test_clear_hook_context_is_scoped_to_pending_request(self):
        self.request()
        d = s.request_dir(self.root, self.r["request_id"])
        s.save(d, self.r, "clear_sending", clear_attempted=True, clear_at=time.time())
        s.atomic(self.root / "panes" / "p1.pending.json", {"request_id": self.r["request_id"]})
        event = {"hook_event_name": "SessionStart", "session_id": "new", "source": "clear", "cwd": str(self.root)}
        context = s.hook(self.root, "p1", event)
        self.assertIn(self.r["request_id"], context)
        self.assertIn("authority", context)
        # Repeating or unrelated starts must not resurrect this bootstrap.
        self.assertIsNone(s.hook(self.root, "p1", event))

    def test_pane_lock_conflict_records_terminal_outcome(self):
        self.request()
        with s.lock(self.root / "panes" / "p1.reset.lock"):
            result = self.run_request()
        self.assertEqual(result["outcome"], "not_cleared")
        self.assertEqual(self.h.sent, [])

    def test_busy_between_screen_and_last_identity_check(self):
        self.request()
        self.h.read_effect = lambda h: setattr(h, "status", "working")
        self.assertFalse(s.readiness(self.h, self.r, "old", after_stop=True)[0])

    def test_wrong_terminal_prevents_resume(self):
        self.request()
        old_prompt = self.h.prompt
        def prompt(pane, text):
            result = old_prompt(pane, text)
            if text == "/clear":
                self.h.terminal = "replacement-terminal"
            return result
        self.h.prompt = prompt
        self.assertEqual(self.run_request()["outcome"], "clear_uncertain")
        self.assertEqual(self.h.sent, ["/clear"])

    def test_permission_mode_change_is_not_acknowledged(self):
        self.request()
        self.h.new_mode = "manual"
        self.assertEqual(self.run_request()["outcome"], "cleared_not_resumed")

    def test_only_matching_paste_envelope_is_normalized(self):
        text = '<pasted_content id="a">\nhello\n</pasted_content id="b">'
        self.assertEqual(s.normalized_prompt(text), text)
        self.assertEqual(s.normalized_prompt('outside '+text), 'outside '+text)

    def test_adapter_refuses_scrolled_and_missing_scroll_metadata(self):
        h = s.Herdr()
        for data in ({"scroll": {"offset_from_bottom": 1}}, {}):
            with patch.object(h, "run", return_value=(True, json.dumps({"result": {"pane": dict(data, pane_id="p1")}}))):
                self.assertIsNone(h.read("p1"))

    def test_fifo_and_oversize_checkpoint_refuse_without_blocking(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(s.Refused):
            s.checkpoint(fifo)
        self.cp.write_bytes(b"x" * 32769)
        with self.assertRaises(s.Refused):
            s.checkpoint(self.cp)

    def test_obsolete_pending_hook_context_is_not_replayed(self):
        self.request()
        d = s.request_dir(self.root, self.r["request_id"])
        s.save(d, self.r, "finished", clear_attempted=True, clear_at=time.time(), outcome="clear_uncertain")
        s.atomic(self.root / "panes" / "p1.pending.json", {"request_id": self.r["request_id"]})
        context = s.hook(self.root, "p1", {"hook_event_name": "SessionStart", "session_id": "new", "source": "clear"})
        self.assertIsNone(context)

    def test_same_session_start_does_not_forget_active_workers(self):
        self.request()
        s.hook(self.root, "p1", {"hook_event_name": "SubagentStart", "session_id": "old", "agent_id": "worker-1"})
        s.hook(self.root, "p1", {"hook_event_name": "SessionStart", "session_id": "old", "source": "compact", "cwd": str(self.root)})
        s.hook(self.root, "p1", {"hook_event_name": "Stop", "session_id": "old"})
        self.assertFalse(s.readiness(self.h, self.r, "old", after_stop=True)[0])

    def test_null_session_telemetry_refuses(self):
        self.assertIsNone(s.session({"agent_session": None}))
        with self.assertRaises(s.Refused):
            s.target({"agent_session": None, "pane_id": "p1", "agent": "claude",
                      "terminal_id": "t1"}, "p1", "old", "t1")

    def test_new_user_turn_invalidates_scheduled_reset(self):
        self.request()
        s.hook(self.root, "p1", {"hook_event_name": "UserPromptSubmit", "session_id": "old", "prompt": "new work"})
        s.hook(self.root, "p1", {"hook_event_name": "Stop", "session_id": "old"})
        self.assertEqual(self.run_request()["outcome"], "not_cleared")
        self.assertEqual(self.h.sent, [])

    def test_permission_dialog_is_not_empty_input(self):
        self.request()
        s.hook(self.root, "p1", {"hook_event_name": "PermissionRequest", "session_id": "old"})
        self.assertFalse(s.readiness(self.h, self.r, "old")[0])

    def test_cli_detached_helper_survives_request_parent_exit(self):
        code = Path(s.__file__).parent
        binary = self.root / "bin"
        binary.mkdir()
        shim = binary / "herdr"
        fake = Path(__file__).parent / "fake_herdr.py"
        shim.write_text("#!" + sys.executable + "\n" + fake.read_text())
        shim.chmod(0o700)
        s.atomic(self.root / "fake.json", {"sid": "old"})
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                   SWITCH_CODE=str(code), SWITCH_FAKE_ROOT=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        parent = subprocess.run([sys.executable, "-B", str(code / "switch.py"), "request",
            "--state-dir", str(self.root), "--pane", "p1", "--session", "old",
            "--checkpoint", str(self.cp), "--resume", "write result", "--idle-deadline", "5",
            "--clear-deadline", "5", "--ack-deadline", "5"], env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(parent.returncode, 0, parent.stderr)
        rid = json.loads(parent.stdout)["request_id"]
        # The launching process has exited; the old Claude turn now stops.
        s.hook(self.root, "p1", {"hook_event_name": "Stop", "session_id": "old"})
        end = time.monotonic() + 10
        while time.monotonic() < end:
            result = s.load(s.request_dir(self.root, rid) / "request.json")
            if result.get("outcome"):
                break
            time.sleep(0.1)
        self.assertEqual(result.get("outcome"), "resumed", result)
        sends = (self.root / "sends.jsonl").read_text().splitlines()
        self.assertEqual(len(sends), 2)



class InputTests(unittest.TestCase):
    def test_real_and_multiline_drafts(self):
        for text, continuation in [("draft", ""), ("", "  wrapped draft\n"),
                                   ("\x1b[2mghost\x1b[22m typed", "")]:
            self.assertEqual(s.input_state(screen(text, continuation)), "draft")

    def test_sgr_rgb_and_reset(self):
        self.assertEqual(s.input_state(screen("\x1b[38;2;2;4;6mreal\x1b[0m")), "draft")
        self.assertEqual(s.input_state(screen("\x1b[2;38;2;2;4;6mghost\x1b[0m")), "empty")
        self.assertEqual(s.input_state(screen("\x1b[38;5;2mreal\x1b[0m")), "draft")
        self.assertEqual(s.input_state(screen("\x1b[2mghost\x1b[0mreal")), "draft")

    def test_missing_ambiguous_and_stale_prompt(self):
        for output in (None, "", "❯", "body\n❯ old prompt", screen() + "footer\n" * 10,
                       screen("\x1b[?25lunknown"), "Do you want to allow?\n1. Yes\n2. No"):
            self.assertEqual(s.input_state(output), "unknown")


if __name__ == "__main__":
    unittest.main()
