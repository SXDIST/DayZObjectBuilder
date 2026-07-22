# Reader for binarized (ODOL) P3D files.
#
# ODOL is the binarized counterpart of the MLOD format handled in data_p3d.py.
# This module only reads; ODOL is never written. Parsed data is converted into the
# MLOD model by odol_to_mlod.py, so the rest of the add-on sees one representation.
#
# Layout follows the publicly documented ODOL structure. DayZ ships version 54,
# which differs from Arma 3 in ModelInfo field set, material version and an
# inconsistent hasAnims byte; those differences are handled explicitly below.
#
# The ModelInfo layout below was derived by measurement against DayZ v54 models,
# because the published documentation covers the Arma 3 field set only. Rather
# than trust it blindly, the position it produces is used as the base for a small
# search: the LOD address table is only accepted where it is internally consistent
# (see read_lod_table). A layout error therefore surfaces as a read failure
# instead of silently producing garbage addresses.


import struct

from . import binary_handler as binary
from . import compression


class ODOL_Error(Exception):
    def __str__(self):
        return "ODOL - %s" % super().__str__()


SIGNATURE = b"ODOL"
VERSION = 54

# Animation types that carry no bone axis data in the anims-to-bones mapping.
ANIM_HIDE = 9
ANIM_DIRECT = 8


def find_odol_offset(file):
    file.seek(0)
    if file.read(4) == SIGNATURE:
        return 0

    # Container formats (eg. Fire Packer) prepend data without rewriting the LOD
    # address table, so the offset has to be added back to every address later.
    file.seek(0)
    data = file.read()
    index = data.find(SIGNATURE)
    if index < 0:
        raise ODOL_Error("No ODOL signature found")

    return index


# ModelInfo for DayZ ODOL v54. Only the byte widths matter here; the values are
# recovered later by the converter, so this walk merely advances the cursor.
#
#   index                 uint32       aiming_center         float[3]
#   mem_lod_sphere        float        map_icon_color        uint32
#   geometry_sphere       float        map_selected_color    uint32
#   remarks               uint32       view_density          float
#   and_hints             uint32       bbox_min/max          float[3] x2
#   or_hints              uint32       bbox_min/max_visual   float[3] x2
#   bounding_center       float[3]     geometry_center       float[3]
#   centre_of_mass        float[3]     inv_inertia           float[9]
#   autocenter            bool         lock_autocenter       bool
#   can_occlude           bool         can_be_occluded       bool
#   allow_animation       bool     <-- DayZ only
#   thermal_profile       float[6]
#   force_not_alpha       uint32   <-- DayZ widens this from bool
#   sb_source             int32        prefer_shadow_volume  bool
#   disable_cover         bool     <-- DayZ only
#   shadow_offset         float        animated              bool
#   skeleton              struct       map_type              byte
#   mass_array            uint32 count + float[count], LZO compressed past 1024 bytes
#   mass, inv_mass, armor, inv_armor    float x4
#   special_lod_indices   byte[13]     min_shadow            uint32
#   can_blend             bool         class, damage         asciiz x2
#   frequent              bool         unknown               uint32
#
# The three DayZ additions total five bytes over the Arma 3 field set.
def skip_model_info(file, version, file_size):
    file.seek(4 * 6, 1)             # index .. or_hints
    file.seek(4 * 3, 1)             # aiming_center
    file.seek(4 * 3, 1)             # map colours, view_density
    file.seek(4 * 3 * 4, 1)         # bbox min/max, visual min/max
    file.seek(4 * 3 * 3, 1)         # bounding, geometry and mass centres
    file.seek(4 * 9, 1)             # inv_inertia
    file.seek(5, 1)                 # autocenter .. allow_animation
    file.seek(4 * 6, 1)             # thermal_profile
    file.seek(4, 1)                 # force_not_alpha (uint32 on DayZ)
    file.seek(4, 1)                 # sb_source
    file.seek(2, 1)                 # prefer_shadow_volume, disable_cover
    file.seek(4, 1)                 # shadow_offset
    file.seek(1, 1)                 # animated

    skip_skeleton(file, version, file_size)

    file.seek(1, 1)                 # map_type
    skip_compressed_floats(file, file_size)  # per point masses of the geometry LOD
    file.seek(4 * 4, 1)             # mass, inv_mass, armor, inv_armor
    file.seek(13, 1)                # special_lod_indices
    file.seek(4, 1)                 # min_shadow
    file.seek(1, 1)                 # can_blend
    binary.read_asciiz(file)        # class
    binary.read_asciiz(file)        # damage
    file.seek(1, 1)                 # frequent
    file.seek(4, 1)                 # unknown


# Below version 64 an array is LZO compressed whenever it would occupy at least
# 1024 bytes; smaller ones are stored raw. Compressed blocks carry no size prefix,
# so the only way past one is to actually decompress it and let the decompressor
# report where the input ended.
COMPRESSION_LIMIT = 1024


# Counts are read at positions that the candidate search is still only guessing at,
# so a wrong guess yields an arbitrary 32 bit number. Nothing in a model can be more
# numerous than the file has bytes, and that bound is enough to turn what would be a
# multi-gigabyte allocation or a billion iteration loop into an immediate rejection.
def read_count(file, file_size, label):
    count = binary.read_ulong(file)
    if count > file_size:
        raise ODOL_Error("Implausible %s count: %d (file is %d bytes)" % (label, count, file_size))

    return count


def skip_compressed_floats(file, file_size):
    count = read_count(file, file_size, "float array")
    expected = 4 * count
    if expected < COMPRESSION_LIMIT:
        file.seek(expected, 1)
        return

    compression.lzo1x_decompress(file, expected, True)


# Below version 64, a compressed block carries no size prefix of its own, so a
# truncated file can only be caught by the decompressor running off the end of
# the stream. lzo1x_decompress signals that with IndexError (file.read(1)[0] on
# an empty read), not EOFError, so both have to be converted here; this is the
# only place callers (elsewhere in this module and in the LOD body reader added
# in a later task) have to guard against.
def read_compressed_array(file, element_size, count, bi_variant = True):
    expected = element_size * count
    if expected < COMPRESSION_LIMIT:
        return file.read(expected)

    try:
        # lzo1x_decompress returns (bytes_consumed, output). The consumed count
        # is derived from the file position, so the stream is already positioned
        # after the block; the count is only informational here.
        _, output = compression.lzo1x_decompress(file, expected, bi_variant)
    except (IndexError, EOFError, ValueError, struct.error, compression.LZO_Error) as ex:
        raise ODOL_Error("Failed to read compressed array: %s" % ex) from ex

    return bytes(output)


# A condensed array is count(u32) + defaultFill(bool) + data, where defaultFill
# means a single value is stored and has to be repeated count times rather than
# count values following individually.
def read_condensed_array(file, element_size, bi_variant = True):
    try:
        count = binary.read_ulong(file)
        default_fill = binary.read_bool(file)
    except (IndexError, EOFError, struct.error) as ex:
        raise ODOL_Error("Failed to read condensed array header: %s" % ex) from ex

    if default_fill:
        value = file.read(element_size)
        if len(value) < element_size:
            raise ODOL_Error("Condensed array default value ran past the end of the file")

        return value * count

    return read_compressed_array(file, element_size, count, bi_variant)


def skip_skeleton(file, version, file_size):
    name = binary.read_asciiz(file)
    if not name:
        return

    file.seek(1, 1)                 # is_discrete
    count_bones = read_count(file, file_size, "skeleton bone")
    for _ in range(count_bones):
        if file.tell() >= file_size:
            raise ODOL_Error("Skeleton bone list ran past the end of the file")

        binary.read_asciiz(file)    # bone name
        binary.read_asciiz(file)    # parent name

    if version > 44:
        binary.read_asciiz(file)    # obsolete pivots name


# Animation classes, followed by the bones-to-animations and animations-to-bones
# mappings. Only lengths matter, the data is not used by the importer.
def skip_animations(file, count_lods, file_size):
    count_classes = binary.read_ulong(file)
    if count_classes > 10000:
        raise ODOL_Error("Implausible animation class count: %d" % count_classes)

    types = []
    for _ in range(count_classes):
        if file.tell() >= file_size:
            raise ODOL_Error("Animation class list ran past the end of the file")

        anim_type = binary.read_ulong(file)
        types.append(anim_type)

        binary.read_asciiz(file)    # name
        binary.read_asciiz(file)    # source
        file.seek(4 * 4, 1)         # min/max value, min/max phase
        file.seek(4, 1)             # source address

        if anim_type == ANIM_HIDE:
            file.seek(4, 1)         # hide value
        elif anim_type == ANIM_DIRECT:
            file.seek(4 * 3 * 2 + 4 * 2, 1)  # axis position, direction, angle, offset
        elif anim_type < ANIM_DIRECT:
            file.seek(4 * 2, 1)     # rotation angles or translation offsets
        else:
            raise ODOL_Error("Unknown animation type: %d" % anim_type)

    # Models that declare the hasAnims byte but carry no animation classes write
    # this count as zero rather than repeating the LOD count.
    count_bone_lods = binary.read_ulong(file)
    if count_bone_lods not in (0, count_lods):
        raise ODOL_Error("Animation bone mapping covers %d LODs, expected %d or 0" % (count_bone_lods, count_lods))

    for _ in range(count_bone_lods):
        count_bones = read_count(file, file_size, "animation bone")
        for _ in range(count_bones):
            count_anims = read_count(file, file_size, "bone animation")
            file.seek(4 * count_anims, 1)

    for _ in range(count_bone_lods):
        for anim_type in types:
            index = binary.read_long(file)
            if index != -1 and anim_type != ANIM_HIDE:
                file.seek(4 * 3 * 2, 1)  # axis position and direction


def read_table_at(file, position, count_lods, file_size, offset):
    if position < 0 or position + count_lods * 9 > file_size:
        raise ODOL_Error("Table at %d does not fit in the file" % position)

    file.seek(position)
    starts = [address + offset for address in binary.read_ulongs(file, count_lods)]
    ends = [address + offset for address in binary.read_ulongs(file, count_lods)]
    flags = binary.read_bytes(file, count_lods)
    table_end = file.tell()

    for i in range(count_lods):
        if not table_end <= starts[i] <= file_size:
            raise ODOL_Error("LOD %d start address %d outside [%d, %d]" % (i, starts[i], table_end, file_size))

        if not starts[i] <= ends[i] <= file_size:
            raise ODOL_Error("LOD %d end address %d not in [%d, %d]" % (i, ends[i], starts[i], file_size))

    for i, flag in enumerate(flags):
        if flag not in (0, 1):
            raise ODOL_Error("LOD %d permanent flag is %d, not a boolean" % (i, flag))

    return starts, ends, [flag == 1 for flag in flags]


def read_lod_table(file, model, count_lods, file_size):
    base = file.tell()

    # DayZ v54 is inconsistent about the hasAnims byte that Arma 3 always writes,
    # and whether animation data follows it at all, so each combination is tried
    # in turn and the first one that yields a consistent table wins. The four
    # candidates, in the priority order documented for DayZ v54:
    #   B: hasAnims byte = 1, animations follow, table after them
    #   C: no hasAnims byte, animations directly here
    #   A: hasAnims byte = 0, table immediately after the byte
    #   D: table directly here, no animations at all
    def after_flag_and_animations():
        file.seek(base + 1)
        skip_animations(file, count_lods, file_size)
        return file.tell()

    def after_animations():
        file.seek(base)
        skip_animations(file, count_lods, file_size)
        return file.tell()

    candidates = [
        ("hasAnims byte then animations", after_flag_and_animations),
        ("animations without hasAnims byte", after_animations),
        ("hasAnims byte, no animations", lambda: base + 1),
        ("no hasAnims byte, no animations", lambda: base),
    ]

    failures = []
    for label, locate in candidates:
        try:
            position = locate()
            starts, ends, permanent = read_table_at(file, position, count_lods, file_size, model.offset)
        # A wrong candidate can walk skip_animations() straight off the end of a
        # truncated file. IndexError included because compression.lzo1x_decompress
        # signals EOF that way (file.read(1)[0]), not with EOFError.
        except (ODOL_Error, compression.LZO_Error, EOFError, IndexError, ValueError, struct.error) as ex:
            failures.append("%s: %s" % (label, ex))
            continue

        model.lod_starts = starts
        model.lod_ends = ends
        model.permanent = permanent
        return

    raise ODOL_Error("Could not locate the LOD address table after ModelInfo (ends at %d).\n  %s" % (base, "\n  ".join(failures)))


class ODOL_File():
    def __init__(self):
        self.version = 0
        self.offset = 0
        self.resolutions = []
        self.lod_starts = []
        self.lod_ends = []
        self.permanent = []

    @classmethod
    def read(cls, file):
        output = cls()
        output.offset = find_odol_offset(file)
        file_size = file.seek(0, 2)

        file.seek(output.offset + 4)
        output.version = binary.read_ulong(file)
        if output.version != VERSION:
            raise ODOL_Error("Unsupported ODOL version: %d (only %d is supported)" % (output.version, VERSION))

        count_lods = read_count(file, file_size, "LOD")
        output.resolutions = list(binary.read_floats(file, count_lods))

        # ModelInfo runs ahead of the candidate search in read_lod_table, so it is
        # not covered by that loop's own exception handling. A truncated file can
        # still end mid LZO stream in here (eg. inside skip_compressed_floats),
        # where the decompressor's file.read(1)[0] raises IndexError, not EOFError.
        # Every failure on malformed input has to leave ODOL_File.read as ODOL_Error.
        try:
            skip_model_info(file, output.version, file_size)
        except (IndexError, EOFError, ValueError, struct.error, compression.LZO_Error) as ex:
            raise ODOL_Error("Failed to read past ModelInfo: %s" % ex) from ex

        read_lod_table(file, output, count_lods, file_size)

        return output
