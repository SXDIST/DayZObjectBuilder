import io
import os
import sys
import random
import struct
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

odol, compression = load_io("data_p3d_odol", "compression")

DRUM = r"P:\DZ\gear\containers\55galDrum.p3d"

# One of the few models whose vertex array decodes differently under the two LZO1X
# variants, which makes it the only kind of file that can settle which one ODOL uses.
RAIL = r"P:\DZ\structures\rail\Tracks\Rail_Track_Passing_25_nolc.p3d"

# Hints 63964 vertices and still stores two byte face indices, which pins the index
# width threshold at 65535 rather than 32767. At 32767 this model's every visual LOD
# fails to parse.
HANGAR = r"P:\DZ\structures_sakhal\military\tisy\proxy\Tisy_BigHangar_A_Grass_R.p3d"

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


class TestArrays(unittest.TestCase):
    def test_short_array_is_raw(self):
        payload = bytes(range(16))
        stream = io.BytesIO(payload)
        self.assertEqual(odol.read_compressed_array(stream, 1, 16), payload)

    def test_condensed_default_fill_repeats_value(self):
        stream = io.BytesIO(struct.pack("<I", 4) + b"\x01" + b"\x07\x00\x00\x00")
        self.assertEqual(odol.read_condensed_array(stream, 4, 4096), b"\x07\x00\x00\x00" * 4)

    def test_condensed_implausible_count_is_rejected(self):
        # defaultFill builds count elements out of a single stored value, so an
        # unbounded count turns four bytes of input into a multi-gigabyte allocation.
        # It has to be bounded by the file size like every other count in the module.
        stream = io.BytesIO(struct.pack("<I", 2 ** 31) + b"\x01" + b"\x07\x00\x00\x00")
        with self.assertRaises(odol.ODOL_Error):
            odol.read_condensed_array(stream, 4, 4096)

    def test_truncated_compressed_array_raises_odol_error(self):
        # 1024 bytes is exactly the LZO threshold, so this goes through the
        # decompressor, which hits EOF via file.read(1)[0] -> IndexError, not
        # EOFError. That has to surface as ODOL_Error, same as everywhere else
        # a compressed block is read in this module.
        stream = io.BytesIO(b"")
        with self.assertRaises(odol.ODOL_Error):
            odol.read_compressed_array(stream, 1, 1024)

    def test_condensed_array_falls_through_to_compressed(self):
        # defaultFill = 0 means the real data follows in the same encoding
        # read_compressed_array uses, so a short (raw) array round-trips.
        payload = bytes(range(8))
        stream = io.BytesIO(struct.pack("<I", 8) + b"\x00" + payload)
        self.assertEqual(odol.read_condensed_array(stream, 1, 4096), payload)


class TestLODIsolation(unittest.TestCase):
    def test_unreadable_lod_bodies_are_collected_not_raised(self):
        # make_model fills the LOD bodies with zeros, which is a valid walk right up
        # to sizeOfRestData and then fails its end address check. A body that cannot
        # be parsed must be recorded rather than lose the whole model.
        file, _, _ = make_model(b"\x00")
        model = odol.ODOL_File.read(file)

        self.assertEqual(model.lods, [])
        self.assertEqual([index for index, _ in model.failed_lods], list(range(COUNT_LODS)))
        for _, reason in model.failed_lods:
            self.assertIn("LOD end", reason)


@unittest.skipUnless(os.path.isfile(DRUM), "test corpus not available")
class TestLODBody(unittest.TestCase):
    def read_drum(self):
        with open(DRUM, "rb") as file:
            return odol.ODOL_File.read(file)

    def test_every_lod_parses(self):
        model = self.read_drum()
        self.assertEqual(model.failed_lods, [])
        self.assertEqual(len(model.lods), len(model.lod_starts))

    def test_first_lod_has_consistent_geometry(self):
        model = self.read_drum()
        lod = model.lods[0]

        self.assertGreater(len(lod.vertices), 0)
        self.assertEqual(len(lod.uvs), len(lod.vertices))

        for face in lod.faces:
            self.assertIn(len(face), (3, 4))
            for index in face:
                self.assertLess(index, len(lod.vertices))

    def test_first_lod_matches_measured_values(self):
        # Pinned against the real model, so a layout change cannot pass by merely
        # producing something self-consistent.
        lod = self.read_drum().lods[0]

        self.assertEqual(len(lod.vertices), 1810)
        self.assertEqual(len(lod.normals), 1810)
        self.assertEqual(len(lod.faces), 2580)
        self.assertEqual(lod.textures, ["dz\\gear\\containers\\data\\barrel_green_co.paa"])
        self.assertEqual(lod.materials, ["dz\\gear\\containers\\data\\barrel_green.rvmat"])
        self.assertEqual(len(lod.sections), 3)
        self.assertEqual(lod.properties.get("lodnoshadow"), "1")

        # Sections partition the faces, in order and without gaps.
        self.assertEqual(lod.sections[0].face_start, 0)
        self.assertEqual(lod.sections[-1].face_end, len(lod.faces))
        for previous, section in zip(lod.sections, lod.sections[1:]):
            self.assertEqual(previous.face_end, section.face_start)

        for section in lod.sections:
            self.assertEqual(section.texture_index, 0)
            self.assertEqual(section.material_index, 0)

    def test_vertices_fill_the_declared_bounding_box(self):
        # The decisive check on the whole decode chain, and the one that settles the
        # LZO variant. bbox_min/max/center are plain floats read straight from the
        # header; the vertices come out of an LZO stream. Requiring the decompressed
        # cloud to fill exactly that box ties the two together: any decompression or
        # framing error produces coordinates that cannot possibly land on it.
        for lod in self.read_drum().lods:
            if not lod.vertices:
                continue

            for axis in range(3):
                low = min(vertex[axis] for vertex in lod.vertices)
                high = max(vertex[axis] for vertex in lod.vertices)

                self.assertAlmostEqual(low, lod.bbox_min[axis], places = 4)
                self.assertAlmostEqual(high, lod.bbox_max[axis], places = 4)
                self.assertAlmostEqual((low + high) / 2, lod.bbox_center[axis], places = 4)

    def test_first_lod_is_drum_sized(self):
        # Independent of the file's own header: the numbers have to be a 55 gallon
        # drum, about 0.85 m tall and about 0.6 m across. Y is up in the ODOL frame.
        lod = self.read_drum().lods[0]

        height = max(v[1] for v in lod.vertices) - min(v[1] for v in lod.vertices)
        diameter = max(v[2] for v in lod.vertices) - min(v[2] for v in lod.vertices)

        self.assertAlmostEqual(height, 0.84, delta = 0.05)
        self.assertAlmostEqual(diameter, 0.61, delta = 0.05)

    def test_uvs_and_normals_are_well_formed(self):
        lod = self.read_drum().lods[0]

        for u, v in lod.uvs:
            self.assertGreaterEqual(u, -0.01)
            self.assertLessEqual(u, 1.01)
            self.assertGreaterEqual(v, -0.01)
            self.assertLessEqual(v, 1.01)

        for normal in lod.normals:
            length = sum(component ** 2 for component in normal) ** 0.5
            self.assertAlmostEqual(length, 1.0, delta = 0.02)

    def test_normals_point_outward(self):
        # Unit length does not pin the decode: negating it, or reading X from the high
        # bits, still yields unit vectors. Orientation is what distinguishes them, and
        # a flipped normal is an inverted-shading bug that nothing else here catches.
        # The drum's cylindrical wall has to face away from its own axis.
        lod = self.read_drum().lods[0]
        centre_x, _, centre_z = lod.bbox_center

        outward = inward = 0
        for vertex, normal in zip(lod.vertices, lod.normals):
            radius_x, radius_z = vertex[0] - centre_x, vertex[2] - centre_z
            radius = (radius_x ** 2 + radius_z ** 2) ** 0.5

            # Only vertices clearly on the side wall, away from the lid and the base.
            if radius < 0.25 or not 0.15 < vertex[1] < 0.7:
                continue

            projection = (normal[0] * radius_x + normal[2] * radius_z) / radius
            if projection > 0.5:
                outward += 1
            elif projection < -0.5:
                inward += 1

        # The drum models its inner surface too, so this is a majority, not a sweep.
        self.assertGreater(outward, 3 * inward)


@unittest.skipUnless(os.path.isfile(RAIL), "test corpus not available")
class TestLZOVariant(unittest.TestCase):
    """Which LZO1X variant ODOL uses, pinned against a model that can tell them apart.

    The variants differ only in the M4 match offset, so almost every block decodes
    identically under both and proves nothing. This model is one of the few whose
    vertex array actually differs, and the LOD's own uncompressed bbox_min/bbox_max
    say which decode is the real geometry."""

    def fill_error(self, lod):
        worst = 0.0
        for axis in range(3):
            low = min(vertex[axis] for vertex in lod.vertices)
            high = max(vertex[axis] for vertex in lod.vertices)
            worst = max(worst, abs(low - lod.bbox_min[axis]), abs(high - lod.bbox_max[axis]))

        return worst

    def read_forcing(self, bi_variant):
        original = compression.lzo1x_decompress
        compression.lzo1x_decompress = lambda file, expected, _ = False: original(file, expected, bi_variant)
        try:
            with open(RAIL, "rb") as file:
                return odol.ODOL_File.read(file)
        finally:
            compression.lzo1x_decompress = original

    def test_module_uses_the_standard_variant(self):
        self.assertFalse(odol.LZO_BI_VARIANT)

    def test_standard_variant_reproduces_the_declared_bounding_box(self):
        with open(RAIL, "rb") as file:
            model = odol.ODOL_File.read(file)

        self.assertLess(self.fill_error(model.lods[0]), 1e-3)

    def test_bi_variant_does_not(self):
        # The other half of the claim. Without this, a future change back to the BI
        # variant would only break the test above with no explanation of why.
        self.assertGreater(self.fill_error(self.read_forcing(True).lods[0]), 1.0)
        self.assertLess(self.fill_error(self.read_forcing(False).lods[0]), 1e-3)

    def test_normals_are_unit_length_only_under_the_standard_variant(self):
        def worst_normal_error(model):
            return max(abs(sum(c ** 2 for c in normal) ** 0.5 - 1.0) for normal in model.lods[0].normals)

        self.assertLess(worst_normal_error(self.read_forcing(False)), 0.01)
        self.assertGreater(worst_normal_error(self.read_forcing(True)), 0.05)


@unittest.skipUnless(os.path.isfile(HANGAR), "test corpus not available")
class TestFaceIndexWidth(unittest.TestCase):
    def test_lod_between_the_two_thresholds_parses(self):
        # Face indices widen at 65535 vertices, not at 32767. This LOD sits between
        # the two, so the wrong threshold reads its face block at the wrong width and
        # loses every visual LOD in the model.
        with open(HANGAR, "rb") as file:
            model = odol.ODOL_File.read(file)

        self.assertEqual(model.failed_lods, [])

        lod = model.lods[0]
        self.assertGreater(len(lod.vertices), 32767)
        self.assertLess(len(lod.vertices), 65536)
        self.assertEqual(len(lod.faces), 15991)
        for face in lod.faces:
            self.assertIn(len(face), (3, 4))
            for index in face:
                self.assertLess(index, len(lod.vertices))


@unittest.skipUnless(os.path.isfile(DRUM), "test corpus not available")
class TestMalformedInput(unittest.TestCase):
    def test_corrupted_models_only_ever_raise_odol_error(self):
        # This runs inside Blender, where an IndexError, struct.error or MemoryError
        # escaping the reader is an add-on crash rather than a rejected file. The
        # decompressor in particular signals end of stream with IndexError, and the
        # sequential LOD walk reaches struct.unpack with whatever bytes it is given.
        with open(DRUM, "rb") as file:
            original = file.read()

        random.seed(3)
        for trial in range(300):
            data = bytearray(original)
            if trial % 3 == 0:
                data = data[:random.randrange(1, len(data))]
            elif trial % 3 == 1:
                for _ in range(random.randrange(1, 40)):
                    data[random.randrange(len(data))] = random.randrange(256)
            else:
                at = random.randrange(len(data) - 4)
                data[at:at + 4] = bytes(random.randrange(256) for _ in range(4))

            try:
                odol.ODOL_File.read(io.BytesIO(bytes(data)))
            except odol.ODOL_Error:
                pass
            except Exception as ex:
                self.fail("trial %d raised %s instead of ODOL_Error: %s" % (trial, type(ex).__name__, ex))


class TestMaterialGuard(unittest.TestCase):
    def test_unprintable_material_name_is_rejected(self):
        # A desynchronised stream reads a material name out of arbitrary bytes. That
        # has to fail rather than shift every following field in the LOD.
        stream = io.BytesIO(b"\x01\x02\x03\x00" + struct.pack("<I", 20) + b"\x00" * 512)
        with self.assertRaises(odol.ODOL_Error) as caught:
            odol.read_material(stream)

        self.assertIn("desynchronised", str(caught.exception))


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
    (DRUM, "TestLODBody (55galDrum.p3d) - the LOD body layout: geometry, UVs, faces, sections and "
           "materials, checked by requiring the decoded vertex cloud to fill the LOD's declared bbox"),
    (RAIL, "TestLZOVariant (Rail_Track_Passing_25_nolc.p3d) - which LZO1X variant ODOL uses. Almost "
           "every block decodes identically under both; this is one of the few models that can "
           "distinguish them, so without it the variant is assumed, not verified"),
    (HANGAR, "TestFaceIndexWidth (Tisy_BigHangar_A_Grass_R.p3d) - that face indices widen at 65535 "
             "vertices and not at 32767, which only a LOD sitting between the two can show"),
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
    lines.append("!! GPL-3 repository. Point the path constants at the top of tests/odol.py")
    lines.append("!! at a local copy of the DayZ P3D corpus to actually verify the layout.")
    lines.append("!" * width)

    print("\n" + "\n".join(lines) + "\n", file = sys.stderr)


if __name__ == "__main__":
    program = unittest.main(exit = False)
    print_corpus_banner()
    sys.exit(0 if program.result.wasSuccessful() else 1)
