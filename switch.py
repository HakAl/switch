#!/usr/bin/env python3
"""A bounded, explicit Claude/Herdr context reset. Python 3.9+, POSIX."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

VERSION = "0.2.0"
EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "PreToolUse", "PostToolUse",
          "PostToolUseFailure", "SubagentStart", "SubagentStop", "PermissionRequest")
ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,160}$")
SGR = re.compile(r"\x1b\[([0-9;]*)m")
BORDER = re.compile(r"^[─━\-]{8,}$")
MARKER = "[Switch automation request "


class Refused(Exception):
    pass


def identifier(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise Refused("invalid pane/session/request identifier")
    return value


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic(path, data):
    """Private, fsynced file and rename; callers own any required lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".switch-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def lock(path, blocking=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
    finally:
        os.close(fd)


def telemetry_path(root, pane, sid):
    return Path(root) / "panes" / identifier(pane) / (identifier(sid) + ".json")


def telemetry(root, pane, sid):
    try:
        return load(telemetry_path(root, pane, sid))
    except (OSError, ValueError):
        return {}


def normalized_prompt(prompt):
    # Claude 2.1.278 wraps bracketed paste in a paired, random-id envelope.
    match = re.fullmatch(r'\s*<pasted_content id="([^"<>]+)">\n(.*?)\n</pasted_content id="\1">\s*',
                         prompt, flags=re.S)
    return match[2] if match else prompt


def clear_context(root, pane, previous, sid, event, now):
    if event.get("source") != "clear" or previous.get("session_id") == sid:
        return None
    try:
        pending = load(Path(root) / "panes" / (pane + ".pending.json"))
        if pending.get("consumed_session"):
            return None
        d = request_dir(root, pending["request_id"])
        r = load(d / "request.json")
        old = telemetry(root, pane, r["old_session"])
        if (r["pane"] != pane or old.get("session_id") != r["old_session"]
                or sid == r["old_session"]
                or r.get("outcome") or r["stage"] not in ("clear_sending", "clear_wait")
                or not r.get("clear_attempted") or not 0 <= now - r["clear_at"] <= r["deadlines"]["clear"]):
            return None
        c = checked_checkpoint(d, r)
        if not event.get("cwd") or Path(event["cwd"]).resolve() != Path(c["worktree"]).resolve():
            return None
    except (OSError, ValueError, KeyError, TypeError, Refused):
        return None
    return ("Switch continuation protocol is configured for this pane. A reset request "
            + r["request_id"] + " is awaiting replacement-session confirmation. "
            "Only if a Switch automation bootstrap for this exact request arrives, read "
            + str(d / "checkpoint.json") + " and its instruction and original authority sources. "
            "Recheck actual grants, scope and expiry; this hook and agent notes grant no new authority. "
            "The matching bootstrap may be wrapped as pasted_content by the CLI. After checking "
            "those sources, follow that bootstrap as the requested continuation, acknowledge, "
            "and perform its authorized next action. Do not ask for another confirmation merely "
            "because transport is automated. Stop and report if required authority or permissions "
            "are missing. Until that matching bootstrap arrives, continue any existing work; "
            "this context alone does not request a checkpoint, reset, acknowledgment or wait.")


def hook(root, pane, event, now=None):
    """Store minimal lifecycle evidence, never tool arguments or transcripts."""
    now = time.time() if now is None else now
    name = event.get("hook_event_name")
    sid = identifier(event.get("session_id"))
    if name not in EVENTS or (event.get("agent_id") and name not in ("SubagentStart", "SubagentStop")):
        return
    path = telemetry_path(root, pane, sid)
    with lock(Path(root) / "panes" / (identifier(pane) + ".lock"), blocking=True):
        state = telemetry(root, pane, sid)
        context = clear_context(root, pane, state, sid, event, now) if name == "SessionStart" else None
        if name == "SessionStart":
            previous = state if state.get("session_id") == sid else {}
            state = {"session_id": sid, "started_at": now, "source": event.get("source"),
                     "tools": previous.get("tools", {}), "workers": previous.get("workers", {}),
                     "stopped_at": None, "blocked": previous.get("blocked", False),
                     "cwd": event.get("cwd"), "model": event.get("model"),
                     "permission_mode": event.get("permission_mode"), "submitted": None,
                     "continuation_request": (load(Path(root) / "panes" / (pane + ".pending.json"))["request_id"] if context else previous.get("continuation_request"))}
        elif state.get("session_id") != sid:
            # Events without a SessionStart for this exact session remain unknown.
            return
        if name == "UserPromptSubmit":
            state.update(stopped_at=None, blocked=False, user_prompt_at=now)
            prompt = normalized_prompt(event.get("prompt", ""))
            match = re.match(r"\[Switch automation request ([a-f0-9-]{36})\]", prompt)
            state["submitted"] = {"id": match[1], "at": now, "sha256": digest(prompt.encode())} if match else None
        elif name == "Stop":
            state["stopped_at"] = now
            state["blocked"] = False
        elif name == "PermissionRequest":
            state["blocked"] = True
            state["stopped_at"] = None
        elif name == "PreToolUse":
            state["tools"][identifier(event.get("tool_use_id"))] = event.get("tool_name")
            state["stopped_at"] = None
        elif name in ("PostToolUse", "PostToolUseFailure"):
            state["tools"].pop(identifier(event.get("tool_use_id")), None)
            state["blocked"] = False
        elif name == "SubagentStart":
            state["workers"][identifier(event.get("agent_id"))] = now
        elif name == "SubagentStop":
            state["workers"].pop(identifier(event.get("agent_id")), None)
        if event.get("permission_mode"):
            state["permission_mode"] = event["permission_mode"]
        state["updated_at"] = now
        state["last_event"] = name
        atomic(path, state)
        return context


def styled_lines(screen):
    """Return (plain, non-dim) lines. Unsupported escape evidence is unknown."""
    if not screen or "\x1b" in SGR.sub("", screen):
        return None
    result, dim = [], False
    for line in screen.splitlines():
        plain, solid, pos = [], [], 0
        for match in SGR.finditer(line):
            text = line[pos:match.start()]
            plain.append(text)
            if not dim:
                solid.append(text)
            params = (match[1] or "0").split(";")
            i = 0
            while i < len(params):
                p = params[i]
                if p in ("38", "48", "58"):
                    if i + 1 >= len(params) or params[i + 1] not in ("2", "5"):
                        return None
                    i += 5 if params[i + 1] == "2" else 3
                    if i > len(params):
                        return None
                    continue
                if p in ("", "0", "22"):
                    dim = False
                elif p == "2":
                    dim = True
                i += 1
            pos = match.end()
        plain.append(line[pos:])
        if not dim:
            solid.append(line[pos:])
        result.append(("".join(plain).replace("\u00a0", " "),
                       "".join(solid).replace("\u00a0", " ")))
    return result


def input_state(screen):
    """Recognize the final bordered Claude input box, including wrapped drafts."""
    lines = styled_lines(screen)
    if not lines:
        return "unknown"
    # Current prompt must be a whole box close to the tail, not echoed history.
    borders = [i for i, (plain, _) in enumerate(lines) if BORDER.fullmatch(plain.strip())]
    if len(borders) < 2:
        return "unknown"
    top, bottom = borders[-2:]
    if bottom - top < 2 or len(lines) - bottom > 8:
        return "unknown"
    box = lines[top + 1:bottom]
    if not box[0][0].lstrip().startswith("❯"):
        return "unknown"
    # Only remove the actual leading prompt; all continuation text is protected.
    first = box[0][1].lstrip()
    if not first.startswith("❯"):
        return "unknown"
    if first[1:].strip() or any(solid.strip() for _, solid in box[1:]):
        return "draft"
    tail = "\n".join(plain for plain, _ in lines[bottom + 1:]).lower()
    if any(word in tail for word in ("esc to cancel", "do you want", "allow once", "permission")):
        return "unknown"
    return "empty"


class Herdr:
    def __init__(self, binary="herdr"):
        self.binary = binary
        self.limit = None

    def run(self, args):
        timeout = 5.0 if self.limit is None else min(5.0, self.limit - time.monotonic())
        if timeout <= 0:
            return False, "deadline expired"
        try:
            p = subprocess.run([self.binary, *args], capture_output=True, text=True,
                               timeout=timeout)
            return p.returncode == 0, p.stdout if p.returncode == 0 else p.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)

    def agent(self, pane):
        ok, out = self.run(["agent", "list"])
        if ok:
            try:
                return next((r for r in json.loads(out)["result"]["agents"]
                             if r.get("pane_id") == pane), None)
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
        return None

    def at_bottom(self, pane):
        ok, out = self.run(["pane", "get", pane])
        if not ok:
            return False
        try:
            data = json.loads(out)["result"]["pane"]
            return (data.get("pane_id") == pane and
                    data["scroll"]["offset_from_bottom"] == 0)
        except (ValueError, KeyError, TypeError):
            return False

    def read(self, pane):
        # Installed 0.7.5 can return empty/stale recent history while visible is
        # current. Never fall back to a possibly scrolled-up viewport unchecked.
        if not self.at_bottom(pane):
            return None
        ok, out = self.run(["pane", "read", pane, "--source", "visible", "--ansi"])
        return out if ok and self.at_bottom(pane) else None

    def prompt(self, pane, prompt):
        return self.run(["agent", "prompt", pane, prompt])[0]


def session(row):
    data = (row or {}).get("agent_session")
    return data.get("value") if isinstance(data, dict) else None


def target(row, pane, sid, terminal=None):
    if not row:
        raise Refused("Herdr telemetry missing")
    if row.get("pane_id") != pane or row.get("agent") != "claude" or session(row) != sid:
        raise Refused("target or session changed")
    if not row.get("terminal_id") or (terminal and row["terminal_id"] != terminal):
        raise Refused("terminal identity missing or changed")
    return row


def read_regular(path, limit):
    # Nonblocking open prevents a FIFO checkpoint/source from hanging a helper.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Refused("source must be a bounded regular file: " + str(path))
        data = f.read(limit + 1)
        if len(data) > limit:
            raise Refused("source grew beyond size limit: " + str(path))
        return data


def checkpoint(path):
    raw = read_regular(path, 32768)
    if not raw or len(raw) > 32768:
        raise Refused("checkpoint must contain 1..32768 readable bytes")
    c = json.loads(raw)
    if not isinstance(c, dict):
        raise Refused("checkpoint must be a JSON object")
    for key in ("task", "role", "worktree", "next_action"):
        if not isinstance(c.get(key), str) or not c[key].strip():
            raise Refused("checkpoint missing " + key)
    if not Path(c["worktree"]).is_absolute() or not Path(c["worktree"]).is_dir():
        raise Refused("checkpoint worktree must be an existing absolute directory")
    for key in ("refs", "completed", "unfinished", "instructions", "authority_sources"):
        if not isinstance(c.get(key), list):
            raise Refused("checkpoint missing list: " + key)
    if not c["refs"] or not c["unfinished"] or not c["authority_sources"]:
        raise Refused("refs, unfinished work and original authority sources are required")
    preparation = c.get("preparation")
    if not isinstance(preparation, dict):
        raise Refused("checkpoint preparation must be a JSON object")
    for key in ("active_tools", "workers", "waits"):
        if preparation.get(key) != []:
            raise Refused("prepare first: outstanding or unknown " + key)
    if preparation.get("quiescent") is not True:
        raise Refused("preparation must attest quiescent: true")
    for key in ("instructions", "authority_sources"):
        for item in c[key]:
            if not isinstance(item, str) or not Path(item).is_absolute():
                raise Refused(key + " must contain absolute paths")
            if not read_regular(item, 1048576).decode("utf-8").strip():
                raise Refused("empty source: " + item)
    return c, raw


def preflight(h, root, pane, sid, cp):
    c, raw = checkpoint(cp)
    row = target(h.agent(pane), pane, sid)
    t = telemetry(root, pane, sid)
    if t.get("session_id") != sid or not t.get("started_at"):
        raise Refused("SessionStart telemetry missing for expected session; configure hooks first")
    if Path(t.get("cwd", "")).resolve() != Path(c["worktree"]).resolve():
        raise Refused("checkpoint worktree does not match hook cwd")
    return {"terminal_id": row["terminal_id"], "checkpoint_sha256": digest(raw),
            "agent_status": row.get("agent_status"), "input": input_state(h.read(pane)),
            "tools": t.get("tools"), "workers": t.get("workers"),
            "model": t.get("model"), "permission_mode": t.get("permission_mode"),
            "context_occupancy": None, "context_reason": "threshold telemetry not enabled"}


def request_dir(root, rid):
    return Path(root) / "requests" / identifier(rid)


def save(d, r, stage=None, **fields):
    now = time.time()
    r.update(fields, updated_at=now)
    if stage:
        r["stage"] = stage
        r.setdefault("history", []).append({"stage": stage, "at": now})
    atomic(d / "request.json", r)


def create(h, root, pane, sid, cp, resume, idle=300, clear=60, ack=120):
    identifier(pane)
    identifier(sid)
    if not resume.strip() or len(resume) > 4000 or any(ord(c) < 32 and c not in "\n\t" for c in resume):
        raise Refused("resume instruction must contain 1..4000 characters")
    for value in (idle, clear, ack):
        if not math.isfinite(value) or not 1 <= value <= 3600:
            raise Refused("deadlines must be finite seconds in 1..3600")
    info = preflight(h, root, pane, sid, cp)
    _, raw = checkpoint(cp)
    if digest(raw) != info["checkpoint_sha256"]:
        raise Refused("checkpoint changed during preflight")
    root = Path(root).resolve()
    rid = str(uuid.uuid4())
    d = request_dir(root, rid)
    claim = root / "claims" / (digest((pane + "\0" + sid).encode()) + ".json")
    with lock(root / "claim.lock"):
        if claim.exists():
            old = load(claim)
            raise Refused("session already claimed by " + old["request_id"] + "; inspect status; do not re-clear")
        d.mkdir(parents=True, mode=0o700)
        atomic(d / "checkpoint.json", json.loads(raw))
        # Digest the actual durable copy; its formatting can differ from the source.
        stored = (d / "checkpoint.json").read_bytes()
        r = {"request_id": rid, "pane": pane, "old_session": sid, "new_session": None,
             "terminal_id": info["terminal_id"], "root": str(root),
             "checkpoint_sha256": digest(stored), "resume": resume,
             "deadlines": {"idle": idle, "clear": clear, "ack": ack},
             "requested_at": time.time(), "before": info, "outcome": None,
             "worker_pid": None, "clear_attempted": False, "resume_attempted": False}
        save(d, r, "scheduled")
        atomic(claim, {"request_id": rid})
    return r


def checked_checkpoint(d, r):
    c, raw = checkpoint(d / "checkpoint.json")
    if digest(raw) != r["checkpoint_sha256"]:
        raise Refused("durable checkpoint changed")
    return c


def readiness(h, r, sid, after_stop=False, clock=time.time):
    row = h.agent(r["pane"])
    if row is None:
        return False, "herdr telemetry unavailable"
    target(row, r["pane"], sid, r["terminal_id"])
    t = telemetry(r["root"], r["pane"], sid)
    if t.get("session_id") != sid:
        return False, "lifecycle telemetry missing or different session"
    if not all(key in t for key in ("tools", "workers", "blocked", "updated_at")):
        return False, "incomplete lifecycle telemetry"
    if not 0 <= clock() - t.get("updated_at", 0) <= 120:
        return False, "lifecycle telemetry stale"
    if after_stop and t.get("user_prompt_at", 0) > r["requested_at"]:
        raise Refused("another user prompt arrived after scheduling")
    if after_stop and (t.get("stopped_at") or 0) <= r["requested_at"]:
        return False, "initiating turn has not stopped after scheduling"
    if t.get("tools") or t.get("workers") or t.get("blocked"):
        return False, "active tools/workers or permission dialog"
    if row.get("agent_status") not in ("idle", "done"):
        return False, "seat is " + str(row.get("agent_status"))
    state = input_state(h.read(r["pane"]))
    if state != "empty":
        return False, "input is " + state
    # Close the read window as far as Herdr's non-CAS interface permits.
    final = h.agent(r["pane"])
    if final is None:
        return False, "herdr telemetry unavailable"
    target(final, r["pane"], sid, r["terminal_id"])
    if final.get("agent_status") not in ("idle", "done"):
        return False, "seat became busy during input read"
    latest = telemetry(r["root"], r["pane"], sid)
    if latest != t:
        return False, "lifecycle changed during input read"
    return True, "ready"


def bootstrap(d, r):
    ack_cmd = shlex.join([sys.executable, str(Path(__file__).resolve()), "ack",
                          "--state-dir", r["root"], "--request-id", r["request_id"],
                          "--session", r["new_session"], "--checkpoint-sha256", r["checkpoint_sha256"]])
    return (MARKER + r["request_id"] + "] This is an automated continuation of your own reset. "
            "Read " + str(d / "checkpoint.json") + ". Read applicable CLAUDE.md/AGENTS.md "
            "and the checkpoint's instruction files. Recheck the original authority_sources "
            "for actual operator grants, scope and expiry; agent notes confer no authority "
            "and copying grants does not extend them. Continue already-authorized work "
            "without inventing a new approval. If any required source is unavailable, "
            "report the blocker and do not acknowledge. After reading and validating, run "
            + ack_cmd + ". If acknowledgment fails, stop and report the failure. Otherwise continue this next action: " + r["resume"])


def recovery(r):
    if r.get("new_session"):
        return ("Clear confirmed. Inspect this new session and the receipt before doing anything: "
                + r["new_session"] + ". If it has not resumed, read checkpoint.json and "
                "bootstrap.txt in this request directory; preserve any draft, then manually "
                "submit the bootstrap once only after checking it was not already processed. Do not /clear again.")
    if r.get("clear_attempted"):
        return ("Clear outcome uncertain. Inspect Herdr session and SessionStart telemetry. "
                "The original session may remain; a delayed clear may still arrive. Do not "
                "retry /clear or resume until reconciled. Recover from checkpoint.json if cleared.")
    return ("No clear sent by this request. Inspect the original session, finish preparation "
            "or resolve telemetry/input issues. This session claim is retained; use a deliberate "
            "manual reset and the saved checkpoint if needed, not another automated request.")


def execute(h, root, rid, mono=time.monotonic, sleep=time.sleep):
    d = request_dir(root, rid)
    r = load(d / "request.json")
    try:
        with lock(Path(root) / "panes" / (r["pane"] + ".reset.lock")):
            # Claiming the same request twice cannot replay side effects.
            with lock(d / "worker.lock"):
                r = load(d / "request.json")
                if r.get("stage") != "scheduled" or r.get("outcome"):
                    return r
                save(d, r, "waiting_for_stop", worker_pid=os.getpid())
                try:
                    remaining = r["requested_at"] + r["deadlines"]["idle"] - time.time()
                    end = mono() + max(0, remaining)
                    h.limit = end
                    why = "waiting"
                    while mono() < end:
                        checked_checkpoint(d, r)
                        ready, why = readiness(h, r, r["old_session"], after_stop=True)
                        if ready:
                            checked_checkpoint(d, r)
                            ready, why = readiness(h, r, r["old_session"], after_stop=True)
                            if ready and mono() < end:
                                break
                        sleep(min(0.5, max(0, end - mono())))
                    else:
                        raise Refused("safe-boundary deadline: " + why)
                    save(d, r, "clear_sending", clear_attempted=True, clear_at=time.time())
                    atomic(Path(root) / "panes" / (r["pane"] + ".pending.json"), {"request_id": rid})
                    end = mono() + r["deadlines"]["clear"]
                    h.limit = end
                    sent = h.prompt(r["pane"], "/clear")
                    save(d, r, "clear_wait", clear_send_returned=sent)
                    # Failed/timeout sends may still have reached Herdr. Never replay.
                    while mono() < end:
                        row = h.agent(r["pane"])
                        if row and row.get("terminal_id") != r["terminal_id"]:
                            raise Refused("terminal replaced during clear")
                        sid = session(row)
                        if sid and sid != r["old_session"]:
                            target(row, r["pane"], sid, r["terminal_id"])
                            t = telemetry(root, r["pane"], sid)
                            if (t.get("session_id") == sid and t.get("source") == "clear"
                                    and t.get("started_at", 0) >= r["clear_at"]):
                                save(d, r, "cleared", new_session=sid, after=t)
                                if t.get("continuation_request") != rid:
                                    raise Refused("clear hook did not activate this continuation protocol")
                                with lock(Path(root) / "panes" / (r["pane"] + ".lock"), blocking=True):
                                    pending_path = Path(root) / "panes" / (r["pane"] + ".pending.json")
                                    pending = load(pending_path)
                                    if pending.get("request_id") != rid or pending.get("consumed_session"):
                                        raise Refused("pending continuation changed before confirmation")
                                    atomic(pending_path, {"request_id": rid, "consumed_session": sid})
                                break
                        sleep(min(0.5, max(0, end - mono())))
                    else:
                        raise Refused("clear unconfirmed before deadline")
                    # Confirmation and replacement readiness each get one full
                    # clear-duration interval. Only this transition resets it.
                    end = mono() + r["deadlines"]["clear"]
                    h.limit = end
                    while mono() < end:
                        ready, why = readiness(h, r, r["new_session"])
                        if ready:
                            checked_checkpoint(d, r)
                            ready, why = readiness(h, r, r["new_session"])
                            if ready and mono() < end:
                                break
                        sleep(min(0.5, max(0, end - mono())))
                    else:
                        raise Refused("cleared but resume readiness deadline: " + why)
                    prompt = bootstrap(d, r)
                    # Recovery text is data, never run as shell code by the helper.
                    fd = os.open(d / "bootstrap.txt", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(prompt + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    save(d, r, "resume_sending", resume_attempted=True, resume_at=time.time(), bootstrap_sha256=digest(prompt.encode()))
                    end = mono() + r["deadlines"]["ack"]
                    h.limit = end
                    sent = h.prompt(r["pane"], prompt)
                    save(d, r, "resume_wait", resume_send_returned=sent)
                    while mono() < end:
                        row = h.agent(r["pane"])
                        if row is None:
                            sleep(min(0.5, max(0, end - mono())))
                            continue
                        target(row, r["pane"], r["new_session"], r["terminal_id"])
                        t = telemetry(root, r["pane"], r["new_session"])
                        submitted = t.get("submitted") or {}
                        if (submitted.get("id") == rid and submitted.get("at", 0) >= r["resume_at"]
                                and submitted.get("sha256") == r["bootstrap_sha256"]):
                            if not r.get("submitted_at"):
                                save(d, r, "submitted", submitted_at=submitted["at"])
                        receipt_path = d / "ack.json"
                        if receipt_path.exists():
                            receipt = load(receipt_path)
                            if (receipt.get("session_id") == r["new_session"]
                                    and receipt.get("request_id") == rid
                                    and receipt.get("checkpoint_sha256") == r["checkpoint_sha256"]
                                    and receipt.get("at", 0) >= r["resume_at"] and r.get("submitted_at")):
                                save(d, r, "finished", outcome="resumed", acknowledged_at=receipt["at"])
                                return r
                        sleep(min(0.5, max(0, end - mono())))
                    raise Refused("resume submitted but not acknowledged" if r.get("submitted_at")
                                  else "resume send not confirmed by UserPromptSubmit")
                except (Exception, KeyboardInterrupt) as exc:
                    outcome = "cleared_not_resumed" if r.get("new_session") else (
                        "clear_uncertain" if r.get("clear_attempted") else "not_cleared")
                    save(d, r, "finished", outcome=outcome, reason=str(exc), recovery=recovery(r))
                    return r
    except BlockingIOError:
        # A duplicate worker never writes over the real owner. A different
        # request blocked by a pane owner does get its own terminal result.
        try:
            with lock(d / "worker.lock"):
                current = load(d / "request.json")
                if current.get("stage") == "scheduled":
                    save(d, current, "finished", outcome="not_cleared",
                         reason="another request holds the pane lock", recovery=recovery(current))
                return current
        except BlockingIOError:
            return dict(r, observer_note="another helper holds this request lock")


def acknowledge(h, root, rid, sid, sha):
    d = request_dir(root, rid)
    r = load(d / "request.json")
    if (r.get("new_session") != sid or sha != r.get("checkpoint_sha256")
            or not r.get("resume_attempted")):
        raise Refused("ack does not match a resume attempt")
    target(h.agent(r["pane"]), r["pane"], sid, r["terminal_id"])
    t = telemetry(root, r["pane"], r["new_session"])
    if (t.get("session_id") != sid or (t.get("submitted") or {}).get("id") != rid
            or (t.get("submitted") or {}).get("sha256") != r.get("bootstrap_sha256")):
        raise Refused("bootstrap submission not observed in this session")
    checked_checkpoint(d, r)
    before_mode = r.get("before", {}).get("permission_mode")
    if before_mode and t.get("permission_mode") and before_mode != t["permission_mode"]:
        raise Refused("permission mode changed across reset; inspect before continuing")
    receipt = {"request_id": rid, "session_id": sid, "checkpoint_sha256": sha, "at": time.time(),
               "permission_mode": t.get("permission_mode"), "model": t.get("model"),
               "meaning": "agent attests it read checkpoint/instructions and rechecked original authority"}
    atomic(d / "ack.json", receipt)
    return receipt


def inspect(root, rid):
    d = request_dir(root, rid)
    r = load(d / "request.json")
    if r.get("outcome"):
        return r
    try:
        with lock(d / "worker.lock"):
            r = load(d / "request.json")
            if r.get("outcome"):
                return r
            age = time.time() - r["requested_at"]
            if r["stage"] != "scheduled" or age > 10:
                # Read-only derived status. Never re-drive an interrupted request.
                return dict(r, outcome="interrupted_uncertain", recovery=recovery(r))
    except BlockingIOError:
        pass
    return r


def hooks_config(root):
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), "hook",
                          "--state-dir", str(Path(root).resolve())])
    return {"hooks": {name: [{"hooks": [{"type": "command", "command": command,
                                          "timeout": 5}]}] for name in EVENTS}}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("preflight", "request", "status", "ack", "hook", "hooks", "_run"):
        q = sub.add_parser(name)
        q.add_argument("--state-dir", required=True, type=Path)
        if name in ("preflight", "request"):
            q.add_argument("--pane", required=True)
            q.add_argument("--session", required=True)
            q.add_argument("--checkpoint", required=True, type=Path)
        if name == "request":
            q.add_argument("--resume", required=True)
            q.add_argument("--idle-deadline", type=float, default=300)
            q.add_argument("--clear-deadline", type=float, default=60,
                           help="seconds each for clear confirmation and subsequent readiness (default: 60 each)")
            q.add_argument("--ack-deadline", type=float, default=120)
        if name in ("status", "ack", "_run"):
            q.add_argument("--request-id", required=True)
        if name == "ack":
            q.add_argument("--session", required=True)
            q.add_argument("--checkpoint-sha256", required=True)
    args = p.parse_args(argv)
    root = args.state_dir.resolve()
    h = Herdr()
    try:
        if args.command == "hook":
            pane = os.environ.get("HERDR_PANE_ID")
            if pane:
                context = hook(root, pane, json.load(sys.stdin))
                if context:
                    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                            "additionalContext": context}}))
            return 0
        if args.command == "hooks":
            result = hooks_config(root)
        elif args.command == "preflight":
            result = preflight(h, root, args.pane, args.session, args.checkpoint)
        elif args.command == "request":
            r = create(h, root, args.pane, args.session, args.checkpoint, args.resume,
                       args.idle_deadline, args.clear_deadline, args.ack_deadline)
            d = request_dir(root, r["request_id"])
            try:
                with open(d / "helper.log", "ab", buffering=0) as log:
                    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_run",
                                      "--state-dir", str(root), "--request-id", r["request_id"]],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True, close_fds=True)
            except OSError as exc:
                save(d, r, "finished", outcome="not_cleared", reason=str(exc), recovery=recovery(r))
                raise
            result = {"request_id": r["request_id"], "stage": "scheduled", "state_dir": str(root),
                      "next": "End this turn now. Do not launch tools, workers, or waits."}
        elif args.command == "_run":
            def terminate(signum, frame):
                raise KeyboardInterrupt("helper received signal " + str(signum))
            signal.signal(signal.SIGTERM, terminate)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            result = execute(h, root, args.request_id)
        elif args.command == "ack":
            result = acknowledge(h, root, args.request_id, args.session, args.checkpoint_sha256)
        else:
            result = inspect(root, args.request_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("outcome") in (None, "resumed") else 4
    except (OSError, ValueError, Refused, TypeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
