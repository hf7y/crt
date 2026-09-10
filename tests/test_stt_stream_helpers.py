#!/usr/bin/env python3
# Offline tests for crt-stt-stream.py's pure LocalAgreement-2 commit logic
# and read_exact() -- no mic/VM/tmux needed, same posture as
# test_stt_solo_helpers.py. The streaming engine itself (main()'s capture
# loop, whisper-cli/sox subprocess calls) is NOT hardware-verified and stays
# untested here; this only witnesses the algorithm crt#48 flagged as having
# no test coverage.
import importlib.util
import io
import os
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_stt_stream_helpers", os.path.join(BIN_DIR, "crt-stt-stream.py"))
stt_stream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stt_stream)


class LocalAgreementCommitTest(unittest.TestCase):
    """Witnesses the file header's WHY claim: 'commits a word once two
    consecutive decodes agree' (LocalAgreement-2)."""

    def test_agreeing_prefix_is_committed(self):
        out = stt_stream.local_agreement_commit([], ["turn", "on"], ["turn", "on", "the"], 2)
        self.assertEqual(out, ["turn", "on"])

    def test_full_agreement_commits_everything(self):
        out = stt_stream.local_agreement_commit([], ["turn", "on"], ["turn", "on"], 2)
        self.assertEqual(out, ["turn", "on"])

    def test_disagreement_stops_commit_at_the_divergence(self):
        out = stt_stream.local_agreement_commit([], ["turn", "on"], ["turn", "off", "the"], 2)
        self.assertEqual(out, ["turn"])

    def test_no_shared_prefix_commits_nothing(self):
        out = stt_stream.local_agreement_commit([], ["hello"], ["goodbye"], 2)
        self.assertEqual(out, [])

    def test_already_committed_words_are_frozen_even_if_a_later_decode_disagrees(self):
        # committed_words is never revised once emitted -- a later hypothesis
        # that would have changed an already-committed word is ignored;
        # comparison only starts past what's already committed.
        out = stt_stream.local_agreement_commit(["turn", "on"], ["turn", "on", "the"], ["turn", "off", "lights"], 2)
        self.assertEqual(out, ["turn", "on"])

    def test_committed_prefix_is_reused_verbatim_not_recomputed(self):
        out = stt_stream.local_agreement_commit(["turn", "on"], ["turn", "on", "the"], ["turn", "on", "light"], 2)
        self.assertEqual(out, ["turn", "on"])

    def test_empty_decodes_commit_nothing(self):
        self.assertEqual(stt_stream.local_agreement_commit([], [], [], 2), [])


class ReadExactTest(unittest.TestCase):
    def test_reads_exactly_n_bytes_across_short_reads(self):
        # BufferedReader may satisfy a read() in fewer bytes than asked;
        # read_exact must keep pulling until it has n or hits EOF.
        f = io.BufferedReader(io.BytesIO(b"abcdefgh"), buffer_size=1)
        self.assertEqual(stt_stream.read_exact(f, 5), b"abcde")

    def test_eof_before_n_bytes_returns_the_short_buffer(self):
        f = io.BytesIO(b"abc")
        self.assertEqual(stt_stream.read_exact(f, 10), b"abc")

    def test_zero_bytes_requested_returns_empty(self):
        f = io.BytesIO(b"abc")
        self.assertEqual(stt_stream.read_exact(f, 0), b"")


if __name__ == "__main__":
    unittest.main()
