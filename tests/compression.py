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

    def test_default_is_standard_variant(self):
        # Calling without the new argument must behave exactly as before.
        stream = io.BytesIO(bytes([0x16]) + b"HELLO" + b"\x11\x00\x00")
        _, out = compression.lzo1x_decompress(stream, 5)
        self.assertEqual(bytes(out), b"HELLO")


if __name__ == "__main__":
    unittest.main()
