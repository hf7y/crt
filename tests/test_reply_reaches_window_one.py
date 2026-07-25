#!/usr/bin/env python3
# Offline test: with the brain on mandark, Claude's answer has to reach the
# tube as well as the earpiece (2026-07-25, nineteenth nightly cycle).
#
# handle() switches the tube to `mono` the moment a request escalates,
# because that is the one window that shows a Claude exchange. What fills it
# is ~/.crt/thoughts.log: log_user_thought() writes the person's own words
# there, and bin/crt-claude-bridge.py writes Claude's -- by tailing Claude
# Code's LOCAL session transcript under ~/.claude/projects/.
#
# Since 2026-07-23 the brain runs on mandark (CRT_CLAUDE_REMOTE_PORT), so
# that transcript is on mandark; potato's bridge window tails a directory
# nothing writes to. The reply was spoken and never written down, on a screen
# the console had just switched to on purpose.
#
# The other half of the test matters just as much: with a LOCAL brain the
# bridge IS doing this job, and mirroring here too would double every line.
import importlib.util
import os
import unittest

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

REMOTE_ENV = {"CRT_CLAUDE_REMOTE_PORT": "8993"}
LOCAL_ENV = {}                                   # CRT_CLAUDE_REMOTE_PORT unset


def load_secretary(env):
    saved = {k: os.environ.get(k) for k in
             ("CRT_CLAUDE_REMOTE_PORT", "CRT_IDLE_FACE_WINDOW", "CRT_TMUX_PANE")}
    for k in saved:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(
            "crt_secretary_window_one", os.path.join(BIN_DIR, "crt-secretary.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ReplyRoutingBase(unittest.TestCase):
    ENV = REMOTE_ENV

    def setUp(self):
        self.mod = load_secretary(dict(self.ENV))
        self.thought_lines = []
        self.spoken = []
        self.printed = []

        def fake_sh(cmd, **kw):
            if cmd and cmd[0].endswith("crt-think.sh"):
                self.thought_lines.append(cmd[1])

            class _R:
                returncode = 0
                stdout = ""
                stderr = ""
            return _R()

        self.mod.sh = fake_sh
        self.mod.speak = lambda text, device="handset": (self.spoken.append(text), True)[1]
        self.mod.print_full = lambda text: self.printed.append(text)


class TestRemoteBrain(ReplyRoutingBase):
    ENV = REMOTE_ENV

    def test_a_short_reply_reaches_the_tube(self):
        self.mod.route_claude_reply("The kettle is on.")
        self.assertEqual(self.spoken, ["The kettle is on."])
        self.assertEqual(self.thought_lines, ["The kettle is on."],
                         "the reply was spoken into the earpiece and never written down")

    def test_the_tube_shows_what_was_said_not_the_whole_answer(self):
        # Window 1 is 40x15 and fades from the top -- dumping a long answer
        # there is the flooding crt-claude-bridge.py's marker filter exists to
        # prevent. The full text goes to the printer, as it already did.
        long_reply = "word " * 200
        self.mod.route_claude_reply(long_reply)
        self.assertEqual(len(self.thought_lines), 1)
        self.assertEqual(self.thought_lines[0], self.spoken[0])
        self.assertIn("printing the rest", self.thought_lines[0])
        self.assertLess(len(self.thought_lines[0]), 200)
        self.assertEqual(len(self.printed), 1)

    def test_an_unseen_reply_says_so_on_the_screen_it_points_at(self):
        # "check the screen" is only useful if the screen says something.
        self.mod.route_claude_reply("")
        self.assertEqual(len(self.thought_lines), 1)
        self.assertEqual(self.thought_lines[0], self.spoken[0])

    def test_a_broken_mirror_does_not_cost_the_spoken_answer(self):
        def raising_sh(cmd, **kw):
            raise OSError("crt-think.sh is not there")
        self.mod.sh = raising_sh
        self.mod.route_claude_reply("The kettle is on.")
        self.assertEqual(self.spoken, ["The kettle is on."])


class TestLocalBrain(ReplyRoutingBase):
    ENV = LOCAL_ENV

    def test_the_transcript_bridge_is_not_doubled(self):
        # With a local brain, crt-claude-bridge.py already forwards Claude's
        # own lines to thoughts.log. Writing them here too would print every
        # reply twice on a fifteen-row screen.
        self.mod.route_claude_reply("The kettle is on.")
        self.assertEqual(self.spoken, ["The kettle is on."])
        self.assertEqual(self.thought_lines, [])

    def test_still_prints_a_long_reply(self):
        self.mod.route_claude_reply("word " * 200)
        self.assertEqual(self.thought_lines, [])
        self.assertEqual(len(self.printed), 1)


if __name__ == "__main__":
    unittest.main()
