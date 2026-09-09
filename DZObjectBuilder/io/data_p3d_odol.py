# Reader for binarized (ODOL) P3D files.
#
# ODOL is the binarized counterpart of the MLOD format handled in data_p3d.py.
# This module only reads; ODOL is never written. Parsed data is converted into the
# MLOD model by odol_to_mlod.py, so the rest of the add-on sees one representation.
#
# Layout follows the publicly documented ODOL structure. DayZ ships three versions: the
# game's own files are version 54, the DayZ Tools binarizer writes 53, which is what
# almost every mod on disk actually contains (3279 against 70 over a 3356 model survey
# of an installed mod set), and the current AddonBuilder writes 55. All three differ
# from Arma 3 in ModelInfo field set, material version and an inconsistent hasAnims
# byte; those differences are handled explicitly below. Between themselves they differ
# in the material layout, a tolerated tail on the last LOD, and how many bytes separate
# ModelInfo from the LOD address table (none, one and two respectively), all documented
# where they are handled.
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
SUPPORTED_VERSIONS = (53, 54, 55)

# The LOD stored last in the file may declare an end address this far past both the end
# of the file and the end of its own rest data. Measured over 657 v53 models: 198 of them
# do it, always on the LOD with the highest start address, and always by exactly 16 bytes.
# Nothing the importer reads lives in that range, so it is tolerated rather than treated
# as a truncated file. Every other LOD is still held to the exact bounds, which is what
# keeps the rest data checksum a checksum.
TRAILING_SLACK = 16

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
#
# What is kept is what an editable model cannot be rebuilt without: the skeleton, which
# only exists here once a model has been binarized, and the per point mass array, which
# is the Geometry LOD's #Mass# tagg folded into the header. Everything else is walked.
class ODOL_ModelInfo():
    def __init__(self):
        self.skeleton = ODOL_Skeleton()
        self.masses = []


def read_model_info(file, version, file_size):
    output = ODOL_ModelInfo()

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

    output.skeleton = read_skeleton(file, version, file_size)

    file.seek(1, 1)                 # map_type
    output.masses = read_compressed_floats(file, file_size)  # per point, geometry LOD
    file.seek(4 * 4, 1)             # mass, inv_mass, armor, inv_armor
    file.seek(13, 1)                # special_lod_indices
    file.seek(4, 1)                 # min_shadow
    file.seek(1, 1)                 # can_blend
    binary.read_asciiz(file)        # class
    binary.read_asciiz(file)        # damage
    file.seek(1, 1)                 # frequent
    file.seek(4, 1)                 # unknown

    return output


# Below version 64 an array is LZO compressed whenever it would occupy at least
# 1024 bytes; smaller ones are stored raw. Compressed blocks carry no size prefix,
# so the only way past one is to actually decompress it and let the decompressor
# report where the input ended.
COMPRESSION_LIMIT = 1024

# Which LZO1X variant DayZ's ODOL data actually uses, measured rather than assumed.
#
# The two variants differ in exactly one place: the M4 match offset, where BI's
# reported variant omits the 16384 base term that standard LZO1X applies. Every other
# opcode is identical, so the question is only decidable on a block that contains a
# non-end-of-stream M4 match, and those are rare: over a 1200 model sample only 6 LODs
# decoded a different vertex array under the two variants.
#
# On those, the two disagree and the file itself says which is right. A LOD stores
# bbox_min/bbox_max as plain uncompressed floats, and the decompressed vertex cloud
# has to fill exactly that box. Standard LZO1X satisfied it in 4 of the 6 and was
# never contradicted; the BI variant satisfied it in 0. On the clearest case,
# Rail_Track_Passing_25_nolc.p3d LOD 0, the BI variant puts the Y extent at 9.56
# against a declared maximum of 0.718 and leaves normals 9% off unit length, while
# standard matches the box on all three axes and normals to within 0.15%.
#
# So the widely repeated claim that BI's LZO needs a modified M4 offset does not hold
# for DayZ v54 ODOL. It stays reachable as a parameter, but nothing here selects it.
LZO_BI_VARIANT = False


# Counts are read at positions that the candidate search is still only guessing at,
# so a wrong guess yields an arbitrary 32 bit number. Nothing in a model can be more
# numerous than the file has bytes, and that bound is enough to turn what would be a
# multi-gigabyte allocation or a billion iteration loop into an immediate rejection.
def read_count(file, file_size, label):
    count = binary.read_ulong(file)
    if count > file_size:
        raise ODOL_Error("Implausible %s count: %d (file is %d bytes)" % (label, count, file_size))

    return count


def read_compressed_floats(file, file_size):
    count = read_count(file, file_size, "float array")
    expected = 4 * count
    if expected < COMPRESSION_LIMIT:
        return list(binary.read_floats(file, count)) if count else []

    _, output = compression.lzo1x_decompress(file, expected, LZO_BI_VARIANT)
    return list(struct.unpack("<%df" % count, bytes(output)))


# Below version 64, a compressed block carries no size prefix of its own, so a
# truncated file can only be caught by the decompressor running off the end of
# the stream. lzo1x_decompress signals that with IndexError (file.read(1)[0] on
# an empty read), not EOFError, so both have to be converted here; this is the
# only place callers (elsewhere in this module and in the LOD body reader added
# in a later task) have to guard against.
def read_compressed_array(file, element_size, count, bi_variant = LZO_BI_VARIANT):
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
#
# The count is read from the stream, so on malformed input it is an arbitrary 32 bit
# number. The defaultFill branch would then build a bytes object of that many elements
# from a handful of input bytes, which is the one path in this module where a bad count
# turns into a large allocation without ever reading a matching amount of data. It is
# bounded the same way every other count in this module is, via read_count.
def read_condensed_array(file, element_size, file_size, bi_variant = LZO_BI_VARIANT):
    try:
        count = read_count(file, file_size, "condensed array")
        default_fill = binary.read_bool(file)
    except (IndexError, EOFError, struct.error) as ex:
        raise ODOL_Error("Failed to read condensed array header: %s" % ex) from ex

    if default_fill:
        value = file.read(element_size)
        if len(value) < element_size:
            raise ODOL_Error("Condensed array default value ran past the end of the file")

        return value * count

    return read_compressed_array(file, element_size, count, bi_variant)


# The skeleton bone names are captured, not just skipped: named selections carry no
# bone weights of their own in DayZ v54 (see the LOD reader), so the per-vertex
# skinning has to be joined onto them by matching a selection's name to a bone's, and
# that join needs this ordered list to turn a vertexBoneRef bone index into a name.
# The skeleton a model was binarized against. In an editable .p3d this lives in the
# model.cfg beside the file, not in the model; binarizing folds it in, so this is the
# only copy left in a binarized model and the only way to write that model.cfg back out.
class ODOL_Skeleton():
    def __init__(self):
        self.name = ""
        self.is_discrete = False
        # Bone names in file order, and the parent name of each. The parent is a name
        # rather than an index because that is how CfgSkeletons states it, and an empty
        # parent means the bone is a root.
        self.bones = []
        self.parents = []
        self.pivots = ""

    def __bool__(self):
        return bool(self.name)


def read_skeleton(file, version, file_size):
    output = ODOL_Skeleton()
    output.name = binary.read_asciiz(file)
    if not output.name:
        return output

    output.is_discrete = binary.read_byte(file) == 1
    count_bones = read_count(file, file_size, "skeleton bone")
    for _ in range(count_bones):
        if file.tell() >= file_size:
            raise ODOL_Error("Skeleton bone list ran past the end of the file")

        output.bones.append(binary.read_asciiz(file))
        output.parents.append(binary.read_asciiz(file))

    if version > 44:
        output.pivots = binary.read_asciiz(file)     # obsolete

    return output


# One animation class, as CfgModels declares it. The type decides which of the tail
# fields carry meaning; the rest stay at their defaults.
class ODOL_Animation():
    def __init__(self):
        self.type = 0
        self.name = ""
        self.source = ""
        self.min_value = 0.0
        self.max_value = 0.0
        self.min_phase = 0.0
        self.max_phase = 0.0
        self.source_address = 0
        self.hide_value = 0.0
        # angle0/angle1 for the rotations, offset0/offset1 for the translations.
        self.value0 = 0.0
        self.value1 = 0.0
        # Direct animations carry their axis inline. Every other type carries it per
        # LOD in the anims-to-bones mapping instead, which is why it is kept there.
        self.axis_position = (0.0, 0.0, 0.0)
        self.axis_direction = (0.0, 0.0, 0.0)
        self.angle = 0.0
        self.axis_offset = 0.0
        # Which bone this animation drives, one entry per LOD, -1 where it drives none.
        # The value indexes the model's skeleton bone list; a model.cfg states that bone
        # by name as the animation's selection.
        self.bones = []
        # The axis each LOD resolved for this animation, as (position, direction), or
        # None. A model.cfg names an axis instead of stating it numerically, so this is
        # what a name has to be matched back against.
        self.axes = []


class ODOL_Animations():
    def __init__(self):
        self.classes = []
        # Per LOD, per skeleton bone, the animation indices that drive it. Redundant
        # with ODOL_Animation.bones and kept only because it is what the file stores.
        self.bones_to_animations = []

    def __bool__(self):
        return bool(self.classes)


# Animation classes, followed by the bones-to-animations and animations-to-bones
# mappings.
#
# This walk doubles as one of the candidates read_lod_table tries when locating the LOD
# address table, so it has to keep failing loudly on anything that does not decode: a
# wrong candidate is told apart from the right one by whether this raises.
def read_animations(file, count_lods, file_size):
    output = ODOL_Animations()

    count_classes = binary.read_ulong(file)
    if count_classes > 10000:
        raise ODOL_Error("Implausible animation class count: %d" % count_classes)

    for _ in range(count_classes):
        if file.tell() >= file_size:
            raise ODOL_Error("Animation class list ran past the end of the file")

        animation = ODOL_Animation()
        animation.type = binary.read_ulong(file)
        animation.name = binary.read_asciiz(file)
        animation.source = binary.read_asciiz(file)
        (animation.min_value, animation.max_value,
         animation.min_phase, animation.max_phase) = binary.read_floats(file, 4)
        animation.source_address = binary.read_ulong(file)

        if animation.type == ANIM_HIDE:
            animation.hide_value = binary.read_float(file)
        elif animation.type == ANIM_DIRECT:
            animation.axis_position = tuple(binary.read_floats(file, 3))
            animation.axis_direction = tuple(binary.read_floats(file, 3))
            animation.angle = binary.read_float(file)
            animation.axis_offset = binary.read_float(file)
        elif animation.type < ANIM_DIRECT:
            animation.value0, animation.value1 = binary.read_floats(file, 2)
        else:
            raise ODOL_Error("Unknown animation type: %d" % animation.type)

        output.classes.append(animation)

    # Models that declare the hasAnims byte but carry no animation classes write
    # this count as zero rather than repeating the LOD count.
    count_bone_lods = binary.read_ulong(file)
    if count_bone_lods not in (0, count_lods):
        raise ODOL_Error("Animation bone mapping covers %d LODs, expected %d or 0" % (count_bone_lods, count_lods))

    for _ in range(count_bone_lods):
        count_bones = read_count(file, file_size, "animation bone")
        per_lod = []
        for _ in range(count_bones):
            count_anims = read_count(file, file_size, "bone animation")
            per_lod.append(list(binary.read_ulongs(file, count_anims)) if count_anims else [])

        output.bones_to_animations.append(per_lod)

    for _ in range(count_bone_lods):
        for animation in output.classes:
            index = binary.read_long(file)
            animation.bones.append(index)

            if index != -1 and animation.type != ANIM_HIDE:
                position = tuple(binary.read_floats(file, 3))
                direction = tuple(binary.read_floats(file, 3))
                animation.axes.append((position, direction))
            else:
                animation.axes.append(None)

    return output


def read_table_at(file, position, count_lods, file_size, offset):
    if position < 0 or position + count_lods * 9 > file_size:
        raise ODOL_Error("Table at %d does not fit in the file" % position)

    file.seek(position)
    starts = [address + offset for address in binary.read_ulongs(file, count_lods)]
    ends = [address + offset for address in binary.read_ulongs(file, count_lods)]
    flags = binary.read_bytes(file, count_lods)
    table_end = file.tell()

    # Only the LOD stored last may overrun, so the slack is granted to that one address
    # rather than to the file as a whole.
    last = starts.index(max(starts))

    for i in range(count_lods):
        if not table_end <= starts[i] <= file_size:
            raise ODOL_Error("LOD %d start address %d outside [%d, %d]" % (i, starts[i], table_end, file_size))

        limit = file_size + TRAILING_SLACK if i == last else file_size
        if not starts[i] <= ends[i] <= limit:
            raise ODOL_Error("LOD %d end address %d not in [%d, %d]" % (i, ends[i], starts[i], limit))

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
    # Each candidate returns the position the table would start at, and whatever
    # animation data it had to read to get there. Which candidate wins is what decides
    # whether the model has animations at all, so the two are settled together.
    def after_flag_and_animations():
        file.seek(base + 1)
        animations = read_animations(file, count_lods, file_size)
        return file.tell(), animations

    def after_animations():
        file.seek(base)
        animations = read_animations(file, count_lods, file_size)
        return file.tell(), animations

    candidates = [
        ("hasAnims byte then animations", after_flag_and_animations),
        ("animations without hasAnims byte", after_animations),
        ("hasAnims byte, no animations", lambda: (base + 1, ODOL_Animations())),
        ("no hasAnims byte, no animations", lambda: (base, ODOL_Animations())),
        # v55 puts TWO bytes here where v54 puts one and v53 none. ModelInfo itself is
        # the same length in all three - v53 pays for its missing geometrySimple byte
        # with an extra one before propertyClass - so this is the only change v55 needs.
        # Kept last on purpose: over the 631 ODOL models of the local corpus the four
        # shapes above still win everywhere they used to (D 567, A 44, B 9, C 9) and
        # this one is reached by exactly the 2 v55 files, which is what pins it as the
        # v55 shape rather than a looser fallback that happens to validate.
        ("no hasAnims byte, table two bytes on", lambda: (base + 2, ODOL_Animations())),
    ]

    failures = []
    for label, locate in candidates:
        try:
            position, animations = locate()
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
        model.animations = animations
        return

    raise ODOL_Error("Could not locate the LOD address table after ModelInfo (ends at %d).\n  %s" % (base, "\n  ".join(failures)))


# An EmbeddedMaterial, read inline in the LOD stream. Only the name is kept; the
# rest exists to be walked past, and walking past it correctly is the whole problem.
#
#   name              asciiz       version           uint32
#   emissive .. specular_copy      float[4] x 6
#   specular_power    float
#   extended          float[width]               <-- width set by the material version
#   pixel_shader, vertex_shader, main_light, fog_mode        uint32 x 4
#   surface_file      asciiz       render flags   uint32 x 2
#   count_stages      uint32       count_tex_gens uint32
#   stage textures    StageTexture[count_stages]
#   stage transforms  (uint32 uv_source + float[12]) x count_tex_gens
#   stage TI          StageTexture               <-- v >= 10 only
#
# The extended block is the only variable part, and its width follows no rule worth
# extrapolating: measured 10 floats at material version 15, 14 at 16 and 26 at 20
# (ODOL v53 writes 15 and 16, v54 writes 20). Guessing it is the expensive kind of
# wrong, because a material is read inline: a bad width does not fail where it happens,
# it silently shifts every following field in the LOD.
#
# So the width is recovered from the file rather than tabulated. Everything after the
# block is heavily constrained -- four small enumerated ids, a path or nothing, two
# bounded counts, then self-describing stage records -- so trying every width and
# keeping the one that validates decides it, and a material version this module has
# never seen costs nothing. Measured over 9310 materials drawn from both ODOL versions,
# exactly one width ever survives. The id bounds are what makes that true: dropped, a
# third of the same materials admit up to ten widths each.
MAX_EXTENDED_FLOATS = 48

# Set well clear of the corpus, whose highest values are pixel shader 129, vertex
# shader 35, main light 3 and fog mode 1.
MAX_PIXEL_SHADER = 200
MAX_VERTEX_SHADER = 200
MAX_MAIN_LIGHT = 8
MAX_FOG_MODE = 4
MAX_STAGE_FILTER = 16
MAX_STAGE_ID = 64
MAX_MATERIAL_STAGES = 64

# binary.read_asciiz walks a byte at a time until it finds a terminator or the file
# ends, so on a wrong width it would scan the rest of the model instead of failing.
# The candidate walk needs a bounded reader, and one that rejects what a path can
# never be, since that rejection is half of what makes the search decisive.
MAX_MATERIAL_STRING = 512

# Printable ASCII, and tab. The tab is not a courtesy: procedural texture strings carry
# a trailing one, as in "#(argb,8,8,3)color(1,1,1,1,co)\t". Rejecting it costs whole
# LODs, 59 of them over a 1018 model sweep of the game files.
MATERIAL_STRING_BYTES = frozenset([9]) | frozenset(range(32, 127))


def read_material_asciiz(file):
    position = file.tell()
    raw = file.read(MAX_MATERIAL_STRING)
    end = raw.find(b"\x00")
    if end < 0:
        raise ODOL_Error("Material string is not terminated within %d bytes" % MAX_MATERIAL_STRING)

    if any(byte not in MATERIAL_STRING_BYTES for byte in raw[:end]):
        raise ODOL_Error("Material string is not printable ASCII: %r" % raw[:end])

    file.seek(position + end + 1)

    return raw[:end]


def read_stage_texture(file):
    if binary.read_ulong(file) > MAX_STAGE_FILTER:
        raise ODOL_Error("Stage texture filter is out of range")

    texture = read_material_asciiz(file)

    if binary.read_ulong(file) > MAX_STAGE_ID:
        raise ODOL_Error("Stage texture id is out of range")

    if binary.read_byte(file) > 1:
        raise ODOL_Error("Stage texture world environment flag is not a boolean")

    return texture


# Everything after the extended block, walked and validated. Returns the position the
# material ends at, so an accepted candidate does not have to be replayed.
def read_material_tail(file, version, file_size):
    pixel, vertex, light, fog = binary.read_ulongs(file, 4)
    if pixel > MAX_PIXEL_SHADER or vertex > MAX_VERTEX_SHADER or light > MAX_MAIN_LIGHT or fog > MAX_FOG_MODE:
        raise ODOL_Error("Material ids out of range: pixel %d, vertex %d, light %d, fog %d"
                         % (pixel, vertex, light, fog))

    # No surface file is normal; one that is present is always a path.
    surface = read_material_asciiz(file)
    if surface and not (b"." in surface and b"\\" in surface):
        raise ODOL_Error("Material surface file is not a path: %r" % surface)

    file.seek(4 * 2, 1)             # render flag count and flags

    count_stages, count_tex_gens = binary.read_ulongs(file, 2)
    if count_stages > MAX_MATERIAL_STAGES or count_tex_gens > MAX_MATERIAL_STAGES:
        raise ODOL_Error("Implausible material stage counts: %d stages, %d tex gens" % (count_stages, count_tex_gens))

    for _ in range(count_stages):
        read_stage_texture(file)

    file.seek(count_tex_gens * (4 + 4 * 12), 1)     # uv source and transform matrix

    if version >= 10:
        read_stage_texture(file)                    # stage TI

    position = file.tell()
    if position > file_size:
        raise ODOL_Error("Material runs past the end of the file")

    return position


def read_material(file, file_size):
    name = binary.read_asciiz(file)
    version = binary.read_ulong(file)

    # The only cheap way to notice a desynchronised stream. A name read at the wrong
    # offset is arbitrary bytes, and the reader would carry on shifting everything
    # after it, so this has to fail the LOD rather than merely look suspicious.
    if any(not (32 <= ord(char) < 127) for char in name):
        raise ODOL_Error("Material name is not printable ASCII: %r (stream is desynchronised)" % name)

    file.seek(4 * 4 * 6, 1)         # emissive .. specular_copy
    file.seek(4, 1)                 # specular_power

    base = file.tell()
    accepted = []
    for width in range(MAX_EXTENDED_FLOATS + 1):
        file.seek(base + 4 * width)
        try:
            accepted.append(read_material_tail(file, version, file_size))
        except (ODOL_Error, EOFError, ValueError, struct.error):
            continue

    if not accepted:
        raise ODOL_Error("No layout fits material %r (version %d), so the stream is desynchronised"
                         % (name, version))

    if len(accepted) > 1:
        raise ODOL_Error("Material %r (version %d) fits %d layouts, so the stream is desynchronised"
                         % (name, version, len(accepted)))

    file.seek(accepted[0])

    return name


# A section binds a run of faces to one texture and one material. Its bounds are
# byte offsets into the face block, not face indices, so they are translated while
# the faces are read.
class ODOL_Section():
    def __init__(self):
        self.face_start = 0
        self.face_end = 0
        self.texture_index = -1
        self.material_index = -1


def read_section(file, offsets, file_size):
    output = ODOL_Section()

    start = binary.read_long(file)
    end = binary.read_long(file)
    file.seek(4 * 2, 1)             # min bone index, bone count
    file.seek(4, 1)                 # common point flags
    output.texture_index = binary.read_short(file)
    file.seek(4, 1)                 # common face flags
    output.material_index = binary.read_long(file)

    # A section with no material carries one extra byte in its place.
    if output.material_index == -1:
        file.seek(1, 1)

    count_stages = read_count(file, file_size, "section stage")
    file.seek(4 * count_stages, 1)  # area over texture, per stage

    # Byte offsets to face indices. Anything that is not on a face boundary means
    # the face block was read with the wrong index width.
    if start not in offsets or end not in offsets:
        raise ODOL_Error("Section face range (%d, %d) is not on a face boundary" % (start, end))

    output.face_start = offsets[start]
    output.face_end = offsets[end]

    return output


# A keyframe is a float time and a point array. Nothing in the importer uses them - MLOD
# has no place to put them - but the layout is known, so they are walked rather than
# treated as a broken LOD. No model in the local corpus carries any; this exists so that
# one that does still imports its geometry.
def skip_keyframes(file, file_size):
    count = read_count(file, file_size, "keyframe")
    for _ in range(count):
        binary.read_float(file)                             # time
        points = read_count(file, file_size, "keyframe point")
        file.seek(4 * 3 * points, 1)


def read_uv_set(file, file_size):
    min_u, min_v, max_u, max_v = binary.read_floats(file, 4)
    raw = read_condensed_array(file, 4, file_size)

    # UVs are quantised to two signed 16 bit values spanning the set's own bounds.
    values = struct.unpack("<%dh" % (len(raw) // 2), raw)
    span_u = (max_u - min_u) / 65535.0
    span_v = (max_v - min_v) / 65535.0

    return [(min_u + (values[i * 2] + 32768) * span_u,
             min_v + (values[i * 2 + 1] + 32768) * span_v) for i in range(len(values) // 2)]


# A named selection. In a binarized DayZ v54 LOD it names a run of faces (a hidden
# selection like "camofemale") or a skeleton bone (like "spine"). The per-vertex bone
# weights are NOT stored in this member: measured on BDU_Jacket_f.p3d, every named
# selection's own selectedVertices and weights arrays are empty across all five visual
# LODs. The skinning is held instead in the LOD's vertexBoneRef block, and is joined
# back onto the bone selections by name (see ODOL_LOD.read). So `faces` comes straight
# from this member, while `vertices` and `weights` are filled in from vertexBoneRef for
# selections whose name matches a skeleton bone, and stay empty for the rest.
class ODOL_NamedSelection():
    def __init__(self, name):
        self.name = name
        self.faces = []
        self.vertices = []
        self.weights = []
        # Set for a selection the engine keeps as a separate drawable run, which is
        # what a model.cfg names in its sections[] array. Binarizing consumes that
        # array into this flag, so the flag is the only way back to it.
        self.is_sectional = False


# vertexBoneRef weight byte -> weight float. Measured, NOT assumed: on BDU_Jacket_f.p3d
# every vertex's weight bytes sum to exactly 255 (all 4932 visual-LOD entries), and every
# fully bound vertex (one bone, one weight) carries the byte 255. So the encoding is a
# plain byte / 255, and full binding lands on 1.0. This is the ODOL vertexBoneRef
# skinning encoding; it is distinct from the MLOD selection-tagg byte encoding, which is
# the non-linear one (0 -> 0.0, 1 -> 1.0, else (256 - b) / 255) that the reference notes
# describe. That non-linear form never appears here because these bytes come from
# vertexBoneRef, where the bytes of a vertex are a partition of 255.
WEIGHT_SCALE = 255.0

# A vertex references at most four bones. Anything above that is a desynchronised stream
# rather than real skinning, and has to fail the LOD instead of over-reading the block.
MAX_VERTEX_BONES = 4


# The other weight encoding: the non-linear one a named selection's inline weight member
# uses, which is the same one MLOD selection taggs use (P3D_TAGG_DataSelection). Distinct
# from the linear vertexBoneRef byte above, and applied to a different array.
def decode_selection_weight(weight):
    if weight in (0, 1):
        return float(weight)

    return (255 - weight) / 254

# vertexBoneRef entry: uint32 weight count, then four (uint8 bone index, uint8 weight)
# pairs, always 12 bytes whether or not vertexBoneRefIsSimple is set. Measured on both
# 55galDrum.p3d (simple, every vertex a single full weight) and BDU_Jacket_f.p3d (up to
# four weights per vertex); in both the block decodes cleanly as count * 12 bytes.
VERTEX_BONE_REF_SIZE = 12


# Reads the vertexBoneRef block into one (bone index, weight float) list per vertex. The
# bone index is into the LOD's subSkeletonsToSkeleton table, not the skeleton directly.
def read_vertex_bone_ref(file, file_size):
    count = read_count(file, file_size, "vertex bone ref")
    raw = read_compressed_array(file, VERTEX_BONE_REF_SIZE, count)
    if len(raw) < VERTEX_BONE_REF_SIZE * count:
        raise ODOL_Error("Vertex bone ref array is %d bytes, expected %d"
                         % (len(raw), VERTEX_BONE_REF_SIZE * count))

    vertex_bones = []
    for i in range(count):
        base = i * VERTEX_BONE_REF_SIZE
        weight_count = struct.unpack_from("<I", raw, base)[0]
        if weight_count > MAX_VERTEX_BONES:
            raise ODOL_Error("Vertex references %d bones, at most %d exist (stream desynchronised)"
                             % (weight_count, MAX_VERTEX_BONES))

        pairs = []
        for k in range(weight_count):
            bone = raw[base + 4 + 2 * k]
            weight = raw[base + 4 + 2 * k + 1]
            pairs.append((bone, weight / WEIGHT_SCALE))

        vertex_bones.append(pairs)

    return vertex_bones


# Joins the vertexBoneRef skinning onto the named selections. A selection whose name is a
# skeleton bone gets every vertex bound to that bone, with the bound weight; the rest keep
# their faces and nothing else. The bone index carried per vertex is resolved through the
# LOD's subSkeletonsToSkeleton table and then the model's skeleton bone list.
def assign_bone_weights(selections, vertex_bones, sub_skeleton, bones):
    if not bones or not sub_skeleton:
        return

    bone_index = {name: index for index, name in enumerate(bones)}

    per_bone = {}
    for vertex, pairs in enumerate(vertex_bones):
        for sub_index, weight in pairs:
            if sub_index >= len(sub_skeleton):
                continue

            per_bone.setdefault(sub_skeleton[sub_index], []).append((vertex, weight))

    for selection in selections:
        skeleton_index = bone_index.get(selection.name)
        bound = per_bone.get(skeleton_index)
        if bound is None:
            continue

        selection.vertices = [vertex for vertex, _ in bound]
        selection.weights = [weight for _, weight in bound]


# One LOD body, read strictly in stream order. Everything up to sizeOfRestData is a
# single sequential walk in which no field is addressable, so a mis-sized field does
# not fail where it happens, it fails somewhere arbitrary later on. sizeOfRestData is
# the one built in checksum: it is the distance from its own position to the LOD end
# address from the file header, which was validated independently. Checking it turns
# any layout error above into an immediate, located failure.
class ODOL_LOD():
    def __init__(self):
        self.vertices = []
        self.normals = []
        # Every UV set the LOD carries, set 0 first. Kept in full rather than reduced to
        # the first: 520 of the 2716 LODs in the local corpus carry a second one, and an
        # MLOD holds each as its own #UVSet# tagg, so dropping them here loses data that
        # the rest of the add-on is already able to represent.
        self.uv_sets = []
        self.faces = []
        self.textures = []
        self.materials = []
        self.sections = []
        self.named_selections = []
        self.properties = {}
        # One per vertex, the same value MLOD stores as a vertex's fourth component.
        self.vertex_flags = []
        # bbox_min, bbox_max and bbox_center are in the same frame as the vertices,
        # which is what makes them a usable check on the decompressed vertex stream.
        self.bbox_min = (0.0, 0.0, 0.0)
        self.bbox_max = (0.0, 0.0, 0.0)
        self.bbox_center = (0.0, 0.0, 0.0)
        # Kept because a failed LOD is skipped rather than inserted as a placeholder,
        # so a LOD's position in ODOL_File.lods is not its position in the address table.
        self.index = -1
        self.resolution = 0.0

    # Set 0 by its old name. Face corners take their UV from it (see convert_face), and
    # the vertex/UV count check below is stated against it.
    @property
    def uvs(self):
        return self.uv_sets[0] if self.uv_sets else []

    @classmethod
    def read(cls, file, version, end, file_size, bones = (), slack = 0):
        # `bones` is the model's skeleton bone name list, indexed by the
        # subSkeletonsToSkeleton table when the skinning is joined on below.
        output = cls()

        # The proxy table holds a model path and a transform per proxy, and it is skipped
        # rather than read because it carries nothing the named selections do not. 4.2% of
        # the proxy selections in a binarized model keep their name but lose their face
        # (52 of 1228 over the local 633 model corpus), and the obvious idea is to recover
        # those triangles from this table. Measured 2026-09-09: it cannot be done, because
        # binarizing drops such a proxy from the table too. The table holds exactly 1176
        # records against exactly 1176 proxy selections that still have a face, and none
        # of the 52 empty ones is listed, by index or by path. The triangle is simply gone.
        count_proxies = read_count(file, file_size, "proxy")
        for _ in range(count_proxies):
            binary.read_asciiz(file)    # name
            file.seek(4 * 12, 1)        # transform
            file.seek(4 * 4, 1)         # sequence, named selection, bone and section indices

        # subSkeletonsToSkeleton: a vertexBoneRef bone index is an index into this table,
        # and the value it holds is the index into the model's skeleton bone list. Kept so
        # the skinning can be resolved back to bone names when the weights are assigned.
        count = read_count(file, file_size, "sub skeleton")
        sub_skeleton = list(binary.read_ulongs(file, count)) if count else []

        count = read_count(file, file_size, "skeleton bone")
        for _ in range(count):
            links = read_count(file, file_size, "sub skeleton link")
            file.seek(4 * links, 1)

        # Both fields exist in every version this module accepts; the gates record
        # where they came in, so a future version bump has the boundary written down.
        count_vertices_hint = binary.read_ulong(file) if version >= 50 else 0
        if version >= 51:
            binary.read_float(file)                     # face area

        file.seek(4 * 2, 1)                             # or_hints, and_hints
        output.bbox_min = binary.read_floats(file, 3)
        output.bbox_max = binary.read_floats(file, 3)
        output.bbox_center = binary.read_floats(file, 3)
        binary.read_float(file)                         # bbox radius

        count_textures = read_count(file, file_size, "texture")
        output.textures = [binary.read_asciiz(file) for _ in range(count_textures)]

        count_materials = read_count(file, file_size, "material")
        output.materials = [read_material(file, file_size) for _ in range(count_materials)]

        # Point/vertex cross references, not needed by the importer.
        read_compressed_array(file, 4, read_count(file, file_size, "point to vertex"))
        read_compressed_array(file, 4, read_count(file, file_size, "vertex to point"))

        # Face vertex indices widen once a LOD carries more vertices than an UNSIGNED
        # short can address; the threshold is 65535, not 32767. Measured on
        # Tisy_BigHangar_A_Grass_R.p3d LOD 0, which hints 63964 vertices and still
        # stores two byte indices: 15991 quads at 2 + 2 * 4 bytes is exactly the
        # 159910 it declares as offsetSections. The offsetSections check below is what
        # catches a wrong choice here, rather than it being silently kept.
        index_size = 4 if count_vertices_hint > 65535 else 2
        read_indices = binary.read_ulongs if index_size == 4 else binary.read_ushorts

        count_faces = read_count(file, file_size, "face")
        size_faces = binary.read_ulong(file)
        file.seek(2, 1)                                 # always zero

        # Section bounds are byte offsets into the face block, but they are not
        # offsets into the block as it is stored. On disk a face is a one byte corner
        # count followed by its indices; the offsets are computed as though that count
        # were two bytes wide, which is how the engine holds the table in memory. So
        # the cursor advances by the stored width while the offset map is built with
        # the wider one. Measured on the corpus: a 25 face block occupies 213 bytes
        # and declares offsetSections 238, which is exactly the two byte accounting.
        offsets = {}
        position = 0
        for _ in range(count_faces):
            offsets[position] = len(output.faces)
            count_corners = binary.read_byte(file)
            if count_corners not in (3, 4):
                raise ODOL_Error("Face has %d corners, only triangles and quads exist" % count_corners)

            output.faces.append(list(read_indices(file, count_corners)))
            position += 2 + index_size * count_corners

        offsets[position] = len(output.faces)
        if position != size_faces:
            raise ODOL_Error("Face block spans %d bytes, the header declared %d" % (position, size_faces))

        count_sections = read_count(file, file_size, "section")
        output.sections = [read_section(file, offsets, file_size) for _ in range(count_sections)]

        face_format = "<%dI" if index_size == 4 else "<%dH"

        count_selections = read_count(file, file_size, "named selection")
        for _ in range(count_selections):
            selection = ODOL_NamedSelection(binary.read_asciiz(file))

            count_selected_faces = read_count(file, file_size, "selected face")
            face_raw = read_compressed_array(file, index_size, count_selected_faces)
            if len(face_raw) < index_size * count_selected_faces:
                raise ODOL_Error("Selected face array is %d bytes, expected %d"
                                 % (len(face_raw), index_size * count_selected_faces))
            selection.faces = list(struct.unpack(face_format % count_selected_faces, face_raw)) if count_selected_faces else []

            file.seek(4, 1)             # always zero
            selection.is_sectional = binary.read_byte(file) == 1
            read_compressed_array(file, 4, read_count(file, file_size, "selected section"))
            # The inline vertex member. On a visual LOD it is empty and the skinning
            # arrives through vertexBoneRef instead, which is what gets joined on below.
            # A Memory LOD is the opposite case and the reason this is read rather than
            # walked: its selections have no faces, so these indices are the only record
            # of which points a named selection holds - the memory points a config
            # addresses, and the axes a model.cfg names for its animations. Measured on
            # mp443.p3d, whose Memory LOD carries 23 selections and not one face.
            count_selected_vertices = read_count(file, file_size, "selected vertex")
            vertex_raw = read_compressed_array(file, index_size, count_selected_vertices)
            if len(vertex_raw) < index_size * count_selected_vertices:
                raise ODOL_Error("Selected vertex array is %d bytes, expected %d"
                                 % (len(vertex_raw), index_size * count_selected_vertices))

            if count_selected_vertices:
                selection.vertices = list(struct.unpack(face_format % count_selected_vertices, vertex_raw))

            # One byte of weight per selected vertex, in the non-linear MLOD selection
            # encoding rather than vertexBoneRef's linear one. An empty array means every
            # selected vertex is fully bound, which is what a memory point selection is.
            count_weights = read_count(file, file_size, "selection weight")
            weight_raw = read_compressed_array(file, 1, count_weights)
            selection.weights = [decode_selection_weight(byte) for byte in weight_raw[:count_weights]]
            if len(selection.weights) < len(selection.vertices):
                selection.weights += [1.0] * (len(selection.vertices) - len(selection.weights))

            output.named_selections.append(selection)

        count_properties = read_count(file, file_size, "named property")
        for _ in range(count_properties):
            key = binary.read_asciiz(file)
            output.properties[key] = binary.read_asciiz(file)

        skip_keyframes(file, file_size)

        file.seek(4 * 3, 1)             # icon colour, colour, special
        file.seek(1, 1)                 # vertex bone reference is simple

        # The checksum described above.
        position = file.tell()
        size_rest = binary.read_ulong(file)
        if not end - slack <= position + size_rest <= end:
            raise ODOL_Error("Rest data at %d is %d bytes, which ends at %d, not in [%d, %d] before the LOD end"
                             % (position, size_rest, position + size_rest, end - slack, end))

        # Per-vertex clip flags. MLOD keeps the same value as the fourth component of a
        # vertex, and it is not decoration: the bits carry the texture clamp modes and the
        # lighting mode the engine applies. Dropping them writes every vertex as flag 0,
        # which Buldozer does not show - it draws the mesh - while the game does.
        raw_flags = read_condensed_array(file, 4, file_size)
        output.vertex_flags = list(struct.unpack("<%dI" % (len(raw_flags) // 4), raw_flags)) if raw_flags else []

        # The first UV set is always present. The count that follows it is the total
        # number of sets, so it is one greater than the number still to come.
        output.uv_sets = [read_uv_set(file, file_size)]
        count_uv_sets = read_count(file, file_size, "UV set")
        for _ in range(max(0, count_uv_sets - 1)):
            output.uv_sets.append(read_uv_set(file, file_size))

        count_vertices = read_count(file, file_size, "vertex")
        raw = read_compressed_array(file, 12, count_vertices)
        if len(raw) < 12 * count_vertices:
            raise ODOL_Error("Vertex array is %d bytes, expected %d" % (len(raw), 12 * count_vertices))

        values = struct.unpack("<%df" % (count_vertices * 3), raw)
        output.vertices = [values[i * 3:i * 3 + 3] for i in range(count_vertices)]

        raw = read_condensed_array(file, 4, file_size)  # normals
        output.normals = [decode_normal(value) for value in struct.unpack("<%dI" % (len(raw) // 4), raw)]

        # ST coordinates (two packed normals, 8 bytes per vertex) sit between the normals
        # and vertexBoneRef. They are unused by the importer, but have to be walked past to
        # reach the skinning; the count precedes them exactly like the vertex array's does.
        read_compressed_array(file, 8, read_count(file, file_size, "ST coordinate"))

        # vertexBoneRef: the per-vertex skinning DayZ v54 keeps out of the named selection
        # member. One 12-byte entry per vertex, joined onto the bone selections below.
        vertex_bones = read_vertex_bone_ref(file, file_size)
        assign_bone_weights(output.named_selections, vertex_bones, sub_skeleton, bones)

        # neighborBoneRef follows, but nothing past the skinning is used and the LOD end
        # address already bounds it, so it is not read.

        for index, uvs in enumerate(output.uv_sets):
            if output.vertices and len(uvs) != len(output.vertices):
                raise ODOL_Error("LOD has %d vertices but UV set %d has %d pairs"
                                 % (len(output.vertices), index, len(uvs)))

        if output.vertices and len(output.normals) != len(output.vertices):
            raise ODOL_Error("Normal count %d does not match vertex count %d" % (len(output.normals), len(output.vertices)))

        for face in output.faces:
            for index in face:
                if index >= len(output.vertices):
                    raise ODOL_Error("Face references vertex %d of %d" % (index, len(output.vertices)))

        return output


# Normals are packed into 32 bits as three 10 bit two's complement values, X in the
# low bits. Both the component order and the sign were checked against geometry rather
# than taken from convention, because every combination yields unit vectors and so
# looks equally correct: on 55galDrum.p3d LOD 0, restricted to the vertices that lie on
# the cylindrical wall, this decode points radially outward on 425 of them and inward
# on 82 (the rest being interior surfaces), while negating it inverts that ratio and
# reading X from the high bits instead gives 174 against 178, ie. no signal at all.
def decode_normal(value):
    x = value & 0x3ff
    y = (value >> 10) & 0x3ff
    z = (value >> 20) & 0x3ff

    return tuple((component - 1024) / 511.0 if component > 511 else component / 511.0
                 for component in (x, y, z))


class ODOL_File():
    def __init__(self):
        self.version = 0
        self.offset = 0
        # What binarizing folded in from the model.cfg beside the source model, and so
        # what writing that model.cfg back out has to be rebuilt from.
        self.skeleton = ODOL_Skeleton()
        self.animations = ODOL_Animations()
        self.masses = []
        self.resolutions = []
        self.lod_starts = []
        self.lod_ends = []
        self.permanent = []
        self.lods = []
        self.failed_lods = []

    # Kept as the skeleton's own list under its old name, because a bone index anywhere
    # in a model - vertexBoneRef, the animation mapping - indexes exactly this.
    @property
    def bones(self):
        return self.skeleton.bones

    @classmethod
    def read(cls, file):
        output = cls()
        output.offset = find_odol_offset(file)
        file_size = file.seek(0, 2)

        # A file can be short enough that even the fixed size header runs off the end,
        # eg. one truncated to just past the signature, so these reads need the same
        # guard as everything below them.
        file.seek(output.offset + 4)
        try:
            output.version = binary.read_ulong(file)
        except (EOFError, struct.error) as ex:
            raise ODOL_Error("File ends inside the ODOL header: %s" % ex) from ex

        if output.version not in SUPPORTED_VERSIONS:
            raise ODOL_Error("Unsupported ODOL version: %d (only %s are supported)"
                             % (output.version, " and ".join(str(item) for item in SUPPORTED_VERSIONS)))

        try:
            count_lods = read_count(file, file_size, "LOD")
            output.resolutions = list(binary.read_floats(file, count_lods))
        except (EOFError, struct.error) as ex:
            raise ODOL_Error("File ends inside the LOD resolution table: %s" % ex) from ex

        # ModelInfo runs ahead of the candidate search in read_lod_table, so it is
        # not covered by that loop's own exception handling. A truncated file can
        # still end mid LZO stream in here (eg. inside skip_compressed_floats),
        # where the decompressor's file.read(1)[0] raises IndexError, not EOFError.
        # Every failure on malformed input has to leave ODOL_File.read as ODOL_Error.
        try:
            model_info = read_model_info(file, output.version, file_size)
        except (IndexError, EOFError, ValueError, struct.error, compression.LZO_Error) as ex:
            raise ODOL_Error("Failed to read past ModelInfo: %s" % ex) from ex

        output.skeleton = model_info.skeleton
        output.masses = model_info.masses

        read_lod_table(file, output, count_lods, file_size)

        # Only the LOD stored last is allowed the trailing tail, matching the address
        # table's own allowance for it.
        last = output.lod_starts.index(max(output.lod_starts)) if output.lod_starts else -1

        # One unreadable LOD must not cost the ones that can be read: a model whose
        # shadow volume trips the layout is still worth importing for its visuals.
        # Every failure mode of the body reader is collected here, including the ones
        # the decompressor raises as IndexError at end of file.
        for index, (start, end) in enumerate(zip(output.lod_starts, output.lod_ends)):
            try:
                file.seek(start)
                slack = TRAILING_SLACK if index == last else 0
                lod = ODOL_LOD.read(file, output.version, end, file_size, output.bones, slack)
                lod.index = index
                lod.resolution = output.resolutions[index]
                output.lods.append(lod)
            except (ODOL_Error, compression.LZO_Error, EOFError, IndexError,
                    ValueError, struct.error, MemoryError) as ex:
                output.failed_lods.append((index, str(ex)))

        return output
