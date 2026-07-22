import io
import os
import sys
import struct
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

odol = load_io("data_p3d_odol")

DRUM = r"P:\DZ\gear\containers\55galDrum.p3d"

# The drum's geometry LOD carries no per point mass array. This one does, and it is
# large enough to be LZO compressed, which is the only way to cover that branch.
HOUSE = r"P:\DZ\structures_sakhal\residential\houses\House_1W02_Blue.p3d"


COUNT_LODS = 2
BODY = 8000  # per LOD, so that addresses are as large as they are in real models


def make_header(version = 54, count_lods = COUNT_LODS, prefix = b""):
    # Minimal synthetic ODOL good enough for the signature/version checks.
    data = prefix + b"ODOL" + struct.pack("<II", version, count_lods)
    data += struct.pack("<%df" % count_lods, *[1.0] * count_lods)
    return io.BytesIO(data)


def make_model_info():
    # The DayZ v54 ModelInfo layout, written out field by field so that a change
    # to the reader's field widths shows up here as a failure rather than as a
    # silently shifted cursor.
    data = struct.pack("<6I", 0, 0, 0, 0, 0, 0)     # index .. or_hints
    data += struct.pack("<3f", 0.0, 0.0, 0.0)       # aiming_center
    data += struct.pack("<2If", 0, 0, -10.0)        # map colours, view_density
    data += struct.pack("<12f", *([0.0] * 12))      # bboxes, visual bboxes
    data += struct.pack("<9f", *([0.0] * 9))        # bounding, geometry, mass centres
    data += struct.pack("<9f", *([0.0] * 9))        # inv_inertia
    data += bytes([0, 0, 0, 1, 1])                  # autocenter .. allow_animation
    data += struct.pack("<6f", 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)  # thermal_profile
    data += struct.pack("<I", 0)                    # force_not_alpha (uint32 on DayZ)
    data += struct.pack("<i", 0)                    # sb_source
    data += bytes([0, 0])                           # prefer_shadow_volume, disable_cover
    data += struct.pack("<f", 1.0)                  # shadow_offset
    data += bytes([0])                              # animated
    data += b"\x00"                                 # skeleton, empty name
    data += bytes([0])                              # map_type
    data += struct.pack("<I", 0)                    # mass array, empty
    data += struct.pack("<4f", 1.0, 1.0, 1.0, 1.0)  # mass, inv_mass, armor, inv_armor
    data += bytes([255] * 13)                       # special_lod_indices
    data += struct.pack("<I", COUNT_LODS)           # min_shadow
    data += bytes([0])                              # can_blend
    data += b"\x00" + b"no\x00"                     # class, damage
    data += bytes([0])                              # frequent
    data += struct.pack("<I", 0)                    # unknown

    return data


def make_animations():
    return struct.pack("<II", 0, 0)  # no animation classes, no bone mapping


def make_model(middle):
    # `middle` is whatever sits between ModelInfo and the LOD address table.
    header = b"ODOL" + struct.pack("<II", 54, COUNT_LODS)
    header += struct.pack("<%df" % COUNT_LODS, *[1.0] * COUNT_LODS)

    table_end = len(header) + len(make_model_info()) + len(middle) + COUNT_LODS * 9
    starts = [table_end + i * BODY for i in range(COUNT_LODS)]
    ends = [start + BODY for start in starts]

    table = struct.pack("<%dI" % COUNT_LODS, *starts)
    table += struct.pack("<%dI" % COUNT_LODS, *ends)
    table += bytes([1] * COUNT_LODS)

    data = header + make_model_info() + middle + table + b"\x00" * (BODY * COUNT_LODS)
    return io.BytesIO(data), starts, ends


class TestCandidateSearch(unittest.TestCase):
    """The hasAnims byte is inconsistent in DayZ v54, so the reader locates the LOD
    address table by trying each shape and keeping the one that validates. All four
    shapes have to be found, whichever order they are attempted in."""

    def check(self, middle):
        file, starts, ends = make_model(middle)
        model = odol.ODOL_File.read(file)
        self.assertEqual(model.lod_starts, starts)
        self.assertEqual(model.lod_ends, ends)
        self.assertEqual(model.permanent, [True] * COUNT_LODS)

    def test_has_anims_set_with_animations(self):
        self.check(b"\x01" + make_animations())

    def test_animations_without_has_anims_byte(self):
        self.check(make_animations())

    def test_has_anims_clear_and_no_animations(self):
        self.check(b"\x00")

    def test_no_has_anims_byte_and_no_animations(self):
        self.check(b"")

    def test_unreadable_table_raises(self):
        file, _, _ = make_model(b"\x00" * 64)
        with self.assertRaises(odol.ODOL_Error) as caught:
            odol.ODOL_File.read(file)

        # The error has to name what was tried, that is the only debugging handle
        # when a new model trips the layout.
        self.assertIn("hasAnims", str(caught.exception))


class TestSignature(unittest.TestCase):
    def test_clean_file_has_zero_offset(self):
        self.assertEqual(odol.find_odol_offset(make_header()), 0)

    def test_container_offset_is_found(self):
        file = make_header(prefix = b"\x01\x02\x03\x04\x05")
        self.assertEqual(odol.find_odol_offset(file), 5)

    def test_missing_signature_raises(self):
        with self.assertRaises(odol.ODOL_Error):
            odol.find_odol_offset(io.BytesIO(b"MLOD\x00\x00\x00\x00"))

    def test_unsupported_version_raises(self):
        with self.assertRaises(odol.ODOL_Error):
            odol.ODOL_File.read(make_header(version = 73))


@unittest.skipUnless(os.path.isfile(DRUM), "test corpus not available")
class TestHeader(unittest.TestCase):
    def test_reads_header_and_lod_table(self):
        with open(DRUM, "rb") as file:
            model = odol.ODOL_File.read(file)

        size = os.path.getsize(DRUM)
        self.assertEqual(model.version, 54)
        self.assertEqual(model.offset, 0)
        self.assertGreater(len(model.resolutions), 0)
        self.assertEqual(len(model.lod_starts), len(model.resolutions))
        self.assertEqual(len(model.lod_ends), len(model.resolutions))
        self.assertEqual(len(model.permanent), len(model.resolutions))

        for start, end in zip(model.lod_starts, model.lod_ends):
            self.assertGreaterEqual(end, start)
            self.assertLessEqual(end, size)

        self.assertTrue(all(p in (True, False) for p in model.permanent))

    def test_lod_table_matches_measured_values(self):
        # Values measured directly from the corpus file, so a silent shift in the
        # ModelInfo layout cannot pass by landing on a merely plausible table.
        with open(DRUM, "rb") as file:
            model = odol.ODOL_File.read(file)

        self.assertEqual(len(model.resolutions), 9)
        self.assertEqual(model.lod_starts, [124410, 80501, 68174, 60218, 5924, 4728, 3579, 2417, 860])
        self.assertEqual(model.lod_ends, [195980, 124410, 80501, 68174, 60218, 5924, 4728, 3579, 2417])
        self.assertEqual(model.permanent, [False, False, False, True, False, True, True, True, True])

    def test_lod_table_spans_the_whole_body(self):
        with open(DRUM, "rb") as file:
            model = odol.ODOL_File.read(file)

        # Every byte between the first LOD and EOF belongs to exactly one LOD.
        spans = sorted(zip(model.lod_starts, model.lod_ends))
        self.assertEqual(spans[-1][1], os.path.getsize(DRUM))
        for (_, end), (start, _) in zip(spans, spans[1:]):
            self.assertEqual(end, start)

    def test_container_prefix_shifts_addresses(self):
        # A Fire Packer style container prepends bytes without rewriting the table,
        # so every address must come back shifted by the same amount.
        with open(DRUM, "rb") as file:
            clean = odol.ODOL_File.read(file)
            file.seek(0)
            padded = io.BytesIO(b"\x00" * 128 + file.read())

        model = odol.ODOL_File.read(padded)
        self.assertEqual(model.offset, 128)
        self.assertEqual(model.lod_starts, [a + 128 for a in clean.lod_starts])
        self.assertEqual(model.lod_ends, [a + 128 for a in clean.lod_ends])
        self.assertEqual(model.permanent, clean.permanent)


@unittest.skipUnless(os.path.isfile(HOUSE), "test corpus not available")
class TestCompressedMassArray(unittest.TestCase):
    def test_reads_past_a_compressed_mass_array(self):
        # ModelInfo holds a per point mass array that is LZO compressed once it
        # reaches 1024 bytes. It carries no size prefix, so walking past it means
        # decompressing it; getting that wrong desynchronises everything after.
        with open(HOUSE, "rb") as file:
            model = odol.ODOL_File.read(file)

        self.assertEqual(model.lod_starts, [318642, 143689, 137902, 117554, 115601, 112442, 110371, 89934, 2450])
        self.assertEqual(model.lod_ends, [643952, 318642, 143689, 137902, 117554, 115601, 112442, 110371, 89934])
        self.assertEqual(model.permanent, [False, False, True, True, True, True, True, True, True])


class TestTruncatedFile(unittest.TestCase):
    def test_truncated_mid_compressed_mass_array_raises_odol_error(self):
        # ModelInfo's mass array is LZO compressed once it reaches 1024 bytes, and
        # the decompressor signals end of file by doing file.read(1)[0], which
        # raises IndexError rather than EOFError. skip_model_info runs before the
        # candidate search in read_lod_table, so it has no exception handling of
        # its own; a truncated file must still surface as ODOL_Error, not IndexError.
        data = make_header().getvalue()
        data += b"\x00" * 212           # index .. animated (fixed size fields)
        data += b"\x00"                 # skeleton, empty name -> no bones to read
        data += b"\x00"                 # map_type
        data += struct.pack("<I", 300)  # mass array count: 300 * 4 = 1200 bytes, over
                                         # the 1024 byte compression threshold
        # No further bytes: the file ends before a single LZO opcode is available.

        file = io.BytesIO(data)
        try:
            odol.ODOL_File.read(file)
            self.fail("Expected ODOL_Error to be raised for a truncated file")
        except odol.ODOL_Error:
            pass
        except Exception as ex:
            self.fail("Expected ODOL_Error, got %s: %s" % (type(ex).__name__, ex))


class TestMassArrayGuard(unittest.TestCase):
    def test_implausible_length_is_rejected(self):
        # A length read from the wrong position would otherwise be decompressed
        # to, allocating gigabytes before failing.
        file = io.BytesIO(struct.pack("<I", 2 ** 31) + b"\x00" * 64)
        with self.assertRaises(odol.ODOL_Error):
            odol.skip_compressed_floats(file, 4096)

    def test_short_array_is_skipped_raw(self):
        file = io.BytesIO(struct.pack("<I", 4) + b"\x00" * 32)
        odol.skip_compressed_floats(file, 4096)
        self.assertEqual(file.tell(), 20)


# Everything above that does not depend on DRUM/HOUSE only proves the reader is
# internally consistent with itself (make_model() restates the same field widths
# the reader uses, so a change to both sides in the same wrong way would still
# pass). These two are the only guarantees actually pinned against real DayZ
# models, and both are gated on a private, non-repo corpus (Bohemia's data, never
# to be committed here). A `-v` skip reason is easy to miss, so the exact
# guarantees that did not run are also announced in a banner below, unconditionally.
CORPUS_GUARANTEES = (
    (DRUM, "TestHeader.test_lod_table_matches_measured_values (55galDrum.p3d) - "
           "exact LOD start/end/permanent values pinned against a real model"),
    (HOUSE, "TestCompressedMassArray.test_reads_past_a_compressed_mass_array (House_1W02_Blue.p3d) - "
            "walking past a real LZO-compressed per-point mass array without desyncing the LOD table"),
)


def print_corpus_banner():
    missing = [(path, guarantee) for path, guarantee in CORPUS_GUARANTEES if not os.path.isfile(path)]
    if not missing:
        return

    width = 78
    lines = [
        "!" * width,
        "!! CORPUS NOT AVAILABLE - THE FOLLOWING ODOL LAYOUT GUARANTEES WERE NOT",
        "!! VERIFIED THIS RUN (skipped, not proven):",
        "!" * width,
    ]
    for path, guarantee in missing:
        lines.append("!!")
        lines.append("!!  missing file: %s" % path)
        lines.append("!!  not verified: %s" % guarantee)

    lines.append("!" * width)
    lines.append("!! These are Bohemia's game files and must NEVER be committed to this")
    lines.append("!! GPL-3 repository. Point the DRUM/HOUSE paths at the top of tests/odol.py")
    lines.append("!! at a local copy of the DayZ P3D corpus to actually verify the layout.")
    lines.append("!" * width)

    print("\n" + "\n".join(lines) + "\n", file = sys.stderr)


if __name__ == "__main__":
    program = unittest.main(exit = False)
    print_corpus_banner()
    sys.exit(0 if program.result.wasSuccessful() else 1)
