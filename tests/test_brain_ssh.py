#!/usr/bin/env python3
# Offline tests for the SSH-direct brain path (2026-07-28) -- the wiring
# that replaced the mandark reverse-tunnel bridge. See DEXTER-MOVE.md
# section 2 and bin/crt-brain-shell.py's header.
#
# These run anywhere: no dexter, no potato, no tmux session, no network.
# The point is the DEGRADE contract, because that is what actually decides
# whether a dead brain is a short honest reply or a console that waits two
# minutes and then lies about having sent something. Every case below is one
# of the ways this path can fail in the house.
import importlib.util
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin")
BRAIN_SHELL = os.path.join(BIN, "crt-brain-shell.py")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_brain_shell(stdin_text, env=None, args=()):
    """Drive crt-brain-shell.py the way sshd does: request on stdin."""
    e = dict(os.environ)
    # Point it at a tmux session that cannot exist, so every tmux call fails
    # the way it would against a dead brain host.
    e["CRT_BRAIN_SESSION"] = "crt-test-nonexistent-session"
    e.update(env or {})
    return subprocess.run([sys.executable, BRAIN_SHELL] + list(args),
                          input=stdin_text, capture_output=True, text=True,
                          timeout=60, env=e)


class BrainShellProtocol(unittest.TestCase):
    def test_print_session_is_the_single_source(self):
        """crt-brain-session.sh asks for the name rather than retyping it.
        If this stops printing exactly one bare word, that script silently
        starts managing a differently-named session than the one sshd's
        forced command drives -- a healthy brain nobody is talking to."""
        r = _run_brain_shell("", args=["--print-session"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "crt-test-nonexistent-session")
        self.assertNotIn(" ", r.stdout.strip())

    def test_unknown_verb_refuses_loudly_with_empty_body(self):
        """Empty body keeps potato's contract (it reads "" as unreachable),
        but the exit code and stderr must not pretend nothing happened --
        the old bridge answered every unknown request with exit 0 and
        silence, making a typo look identical to a dead tmux."""
        r = _run_brain_shell("WHAT\n")
        self.assertEqual(r.stdout, "")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown request", r.stderr)

    def test_capture_of_dead_session_returns_no_body(self):
        """A dead session must NOT come back as an empty-but-successful
        pane. potato's capture_pane() treats "" as unreadable on purpose:
        a live Claude Code pane is never legitimately blank."""
        r = _run_brain_shell("CAPTURE\n")
        self.assertEqual(r.stdout, "")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CAPTURE failed", r.stderr)

    def test_send_to_dead_session_reports_ERR_not_OK(self):
        """The failure that mattered most on the socket path: a SEND that
        did not land must never look like one that did, or the console
        fires the thinking earcon and waits out the full idle timeout for a
        reply that cannot come."""
        r = _run_brain_shell("SEND hello there\n")
        self.assertTrue(r.stdout.startswith("ERR "), r.stdout)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("OK", r.stdout.split("ERR ")[0])

    def test_send_payload_is_never_shell_interpreted(self):
        """There is no shell on the far side, and this proves the claim
        rather than asserting it in a comment. A payload full of shell
        metacharacters must come back as a tmux failure about the missing
        session -- not as evidence anything was expanded or executed."""
        nasty = "SEND $(touch /tmp/crt-brain-pwned); rm -rf /; `id`\n"
        r = _run_brain_shell(nasty)
        self.assertTrue(r.stdout.startswith("ERR "), r.stdout)
        self.assertFalse(os.path.exists("/tmp/crt-brain-pwned"),
                         "command substitution in a SEND payload was executed")


class SecretaryTransportSelection(unittest.TestCase):
    """brain_mode() is the one place precedence is decided. If it regresses,
    a console with both knobs set gets two brains answering one utterance."""

    def _secretary_with(self, **env):
        for k in ("CRT_CLAUDE_SSH_HOST", "CRT_CLAUDE_REMOTE_PORT"):
            os.environ.pop(k, None)
        os.environ.update(env)
        return _load("secretary_under_test", "crt-secretary.py")

    def test_ssh_host_wins_over_remote_port(self):
        s = self._secretary_with(CRT_CLAUDE_SSH_HOST="dexter",
                                 CRT_CLAUDE_REMOTE_PORT="8993")
        self.assertEqual(s.brain_mode(), "ssh")

    def test_port_only_still_selects_the_bridge(self):
        s = self._secretary_with(CRT_CLAUDE_REMOTE_PORT="8993")
        self.assertEqual(s.brain_mode(), "port")

    def test_neither_is_local(self):
        s = self._secretary_with()
        self.assertEqual(s.brain_mode(), "local")

    def test_ssh_request_returns_empty_string_when_host_is_unreachable(self):
        """The tolerant-degrade contract every caller depends on: never
        raise into the capture loop, however badly ssh fails."""
        s = self._secretary_with(CRT_CLAUDE_SSH_HOST="dexter",
                                 CRT_CLAUDE_REMOTE_SSH_TIMEOUT="1")
        # An alias that cannot resolve -- the ssh equivalent of a dropped
        # tunnel, and the exact shape of a mistyped host in ~/.crt config.
        self.assertEqual(s._ssh_request("CAPTURE", "crt-test-no-such-host-xyz"), "")

    def test_send_to_unreachable_brain_returns_False(self):
        """Not merely "does not crash": send_to_claude() must report that
        the utterance did NOT land, so handle() gives an honest line
        instead of "I sent that to Claude but didn't catch a reply"."""
        s = self._secretary_with(CRT_CLAUDE_SSH_HOST="crt-test-no-such-host-xyz",
                                 CRT_CLAUDE_REMOTE_SSH_TIMEOUT="1")
        s.log_brain_unreachable = lambda *a, **k: None   # no writes from a test
        self.assertFalse(s.send_to_claude("are you there"))


class WakeRouterFollowsTheSamePrecedence(unittest.TestCase):
    """A router that disagrees with the thing it routes for is worse than no
    router: it would send a wake to a brain the secretary will not use."""

    def _router_with(self, **env):
        for k in ("CRT_CLAUDE_SSH_HOST", "CRT_CLAUDE_REMOTE_PORT"):
            os.environ.pop(k, None)
        os.environ.update(env)
        return _load("wake_router_under_test", "crt-wake-router.py")

    def test_ssh_mode_reported(self):
        wr = self._router_with(CRT_CLAUDE_SSH_HOST="dexter")
        self.assertEqual(wr.brain_configured_on(), ("ssh", "dexter"))

    def test_ssh_wins_over_port_here_too(self):
        wr = self._router_with(CRT_CLAUDE_SSH_HOST="dexter",
                               CRT_CLAUDE_REMOTE_PORT="8993")
        self.assertEqual(wr.brain_configured_on()[0], "ssh")

    def test_nothing_configured_is_no_remote_brain(self):
        wr = self._router_with()
        self.assertEqual(wr.brain_configured_on(), (None, None))

    def test_probe_ssh_is_false_for_unreachable_host(self):
        wr = self._router_with(CRT_CLAUDE_SSH_HOST="crt-test-no-such-host-xyz")
        self.assertFalse(wr.probe_ssh("crt-test-no-such-host-xyz", timeout=2))

    def test_probe_ssh_is_false_for_empty_host(self):
        """Guard against the config-typo case reaching ssh at all."""
        wr = self._router_with()
        self.assertFalse(wr.probe_ssh(""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
