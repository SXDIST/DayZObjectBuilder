"""
python tests/p3d_weights.py

Pins the selection weight codec of the MLOD P3D format. A selection stores one byte
per vertex, so precision loss is expected, but a vertex that carries a weight must
never come back weightless: byte 0 means "not in this selection" and byte 255 decodes
to 0, so both ends of the encoder have to stay clear of them.
"""


import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

p3d = load_io("data_p3d")

Selection = p3d.P3D_TAGG_DataSelection

# The codec quantises to 254 steps, so a round trip may not drift further than half
# a step in either direction.
STEP = 1 / 254


class TestSelectionWeightCodec(unittest.TestCase):
    def weights(self):
        # Dense sweep plus the values that sit right at the ends of the range, where
        # the rounding decides between a real weight and "not in selection".
        sweep = [i / 10000 for i in range(1, 10001)]
        return sweep + [1e-6, 1e-5, 0.0001, 0.00098, 0.00196, 0.00197, 0.998, 0.9999]

    def test_zero_stays_zero(self):
        self.assertEqual(Selection.encode_weight(0), 0)
        self.assertEqual(Selection.decode_weight(0), 0)

    def test_full_weight_survives(self):
        self.assertEqual(Selection.encode_weight(1), 1)
        self.assertEqual(Selection.decode_weight(1), 1)

    def test_encoded_bytes_stay_in_range(self):
        for weight in self.weights():
            value = Selection.encode_weight(weight)
            self.assertGreaterEqual(value, 0, "weight %r encoded below a byte" % weight)
            self.assertLessEqual(value, 255, "weight %r encoded above a byte" % weight)

    def test_nonzero_weight_never_encodes_to_an_unselected_vertex(self):
        # Byte 0 drops the vertex from the selection entirely on the next read.
        for weight in self.weights():
            self.assertNotEqual(Selection.encode_weight(weight), 0, "weight %r encoded to byte 0" % weight)

    def test_nonzero_weight_never_decodes_back_to_zero(self):
        # Byte 255 decodes to 0, so a vertex would stay in the selection with no
        # influence at all - the silent weight loss this pins against.
        for weight in self.weights():
            value = Selection.encode_weight(weight)
            self.assertGreater(Selection.decode_weight(value), 0, "weight %r round tripped to 0" % weight)

    def test_round_trip_stays_within_one_quantisation_step(self):
        for weight in self.weights():
            result = Selection.decode_weight(Selection.encode_weight(weight))
            self.assertLessEqual(abs(result - weight), STEP, "weight %r drifted to %r" % (weight, result))


if __name__ == "__main__":
    unittest.main()
