import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

compression = load_io("compression")


class TestLZOStandardUnchanged(unittest.TestCase):
    # A literal-run followed by end-of-stream. Exercises the path PAA import relies on.
    def test_literal_run_roundtrip(self):
        stream = io.BytesIO(bytes([0x16]) + b"HELLO" + b"\x11\x00\x00")
        # lzo1x_decompress returns (bytes_consumed, output); only the output buffer
        # matters for this pin.
        _, out = compression.lzo1x_decompress(stream, 5)
        self.assertEqual(bytes(out), b"HELLO")

    def test_explicit_standard_matches_default(self):
        # The default and an explicit bi_variant=False must be the same path.
        # Distinct from the test above: that one pins the output, this one pins
        # the equivalence of the two ways of asking for standard behaviour.
        payload = bytes([0x16]) + b"HELLO" + b"\x11\x00\x00"

        _, implicit = compression.lzo1x_decompress(io.BytesIO(payload), 5)
        _, explicit = compression.lzo1x_decompress(io.BytesIO(payload), 5, False)

        self.assertEqual(bytes(implicit), bytes(explicit))


if __name__ == "__main__":
    unittest.main()
