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


def skip_compressed_floats(file, file_size):
    count = read_count(file, file_size, "float array")
    expected = 4 * count
    if expected < COMPRESSION_LIMIT:
        file.seek(expected, 1)
        return

    compression.lzo1x_decompress(file, expected, LZO_BI_VARIANT)


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


# An EmbeddedMaterial, read inline in the LOD stream. Only the name is kept; the
# rest exists to be walked past, and walking past it correctly is the whole problem.
#
# DayZ writes material version 20, which inserts two fields the Arma 3 layout does
# not have: 25 floats of extended PBR data after pixel_shader, and one uint32 after
# fog_mode. That is 104 bytes. Materials are read inline, so getting the width wrong
# does not fail here, it silently shifts every following field in the LOD.
#
#   name              asciiz       version           uint32
#   emissive .. specular_copy      float[4] x 6
#   specular_power    float        pixel_shader      uint32
#   dayz_extended     float[25]  <-- v >= 20 only
#   vertex_shader, main_light, fog_mode              uint32 x 3
#   dayz_unknown      uint32     <-- v >= 20 only
#   surface_file      asciiz       render flags      uint32 x 2
#   count_stages      uint32       count_tex_gens    uint32
#   stage textures    StageTexture[count_stages]
#   stage transforms  (uint32 uv_source + float[12]) x count_tex_gens
#   stage TI          StageTexture               <-- v >= 10 only
MATERIAL_VERSION_DAYZ = 20


def read_stage_texture(file):
    binary.read_ulong(file)         # filter
    texture = binary.read_asciiz(file)
    binary.read_ulong(file)         # stage id
    file.seek(1, 1)                 # use world environment map

    return texture


def read_material(file):
    name = binary.read_asciiz(file)
    version = binary.read_ulong(file)

    # The only cheap way to notice a desynchronised stream. A name read at the wrong
    # offset is arbitrary bytes, and the reader would carry on shifting everything
    # after it, so this has to fail the LOD rather than merely look suspicious.
    if any(not (32 <= ord(char) < 127) for char in name):
        raise ODOL_Error("Material name is not printable ASCII: %r (stream is desynchronised)" % name)

    file.seek(4 * 4 * 6, 1)         # emissive .. specular_copy
    file.seek(4, 1)                 # specular_power
    file.seek(4, 1)                 # pixel_shader

    if version >= MATERIAL_VERSION_DAYZ:
        file.seek(4 * 25, 1)        # DayZ extended PBR block

    file.seek(4 * 3, 1)             # vertex_shader, main_light, fog_mode

    if version >= MATERIAL_VERSION_DAYZ:
        file.seek(4, 1)             # DayZ only

    binary.read_asciiz(file)        # surface file
    file.seek(4 * 2, 1)             # render flag count and flags

    count_stages = binary.read_ulong(file)
    count_tex_gens = binary.read_ulong(file)
    if count_stages > 64 or count_tex_gens > 64:
        raise ODOL_Error("Implausible material stage counts: %d stages, %d tex gens" % (count_stages, count_tex_gens))

    for _ in range(count_stages):
        read_stage_texture(file)

    for _ in range(count_tex_gens):
        binary.read_ulong(file)     # uv source
        file.seek(4 * 12, 1)        # transform matrix

    if version >= 10:
        read_stage_texture(file)    # stage TI

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


def read_uv_set(file, file_size, keep):
    min_u, min_v, max_u, max_v = binary.read_floats(file, 4)
    raw = read_condensed_array(file, 4, file_size)
    if not keep:
        return []

    # UVs are quantised to two signed 16 bit values spanning the set's own bounds.
    values = struct.unpack("<%dh" % (len(raw) // 2), raw)
    span_u = (max_u - min_u) / 65535.0
    span_v = (max_v - min_v) / 65535.0

    return [(min_u + (values[i * 2] + 32768) * span_u,
             min_v + (values[i * 2 + 1] + 32768) * span_v) for i in range(len(values) // 2)]


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
        self.uvs = []
        self.faces = []
        self.textures = []
        self.materials = []
        self.sections = []
        self.properties = {}
        # bbox_min, bbox_max and bbox_center are in the same frame as the vertices,
        # which is what makes them a usable check on the decompressed vertex stream.
        self.bbox_min = (0.0, 0.0, 0.0)
        self.bbox_max = (0.0, 0.0, 0.0)
        self.bbox_center = (0.0, 0.0, 0.0)
        # Kept because a failed LOD is skipped rather than inserted as a placeholder,
        # so a LOD's position in ODOL_File.lods is not its position in the address table.
        self.index = -1
        self.resolution = 0.0

    @classmethod
    def read(cls, file, version, end, file_size):
        output = cls()

        count_proxies = read_count(file, file_size, "proxy")
        for _ in range(count_proxies):
            binary.read_asciiz(file)    # name
            file.seek(4 * 12, 1)        # transform
            file.seek(4 * 4, 1)         # sequence, named selection, bone and section indices

        count = read_count(file, file_size, "sub skeleton")
        file.seek(4 * count, 1)         # sub skeletons to skeleton

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
        output.materials = [read_material(file) for _ in range(count_materials)]

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

        count_selections = read_count(file, file_size, "named selection")
        for _ in range(count_selections):
            binary.read_asciiz(file)    # name
            read_compressed_array(file, index_size, read_count(file, file_size, "selected face"))
            file.seek(4, 1)             # always zero
            file.seek(1, 1)             # is sectional
            read_compressed_array(file, 4, read_count(file, file_size, "selected section"))
            read_compressed_array(file, index_size, read_count(file, file_size, "selected vertex"))
            read_compressed_array(file, 1, read_count(file, file_size, "selection weight"))

        count_properties = read_count(file, file_size, "named property")
        for _ in range(count_properties):
            key = binary.read_asciiz(file)
            output.properties[key] = binary.read_asciiz(file)

        count_frames = read_count(file, file_size, "keyframe")
        if count_frames:
            raise ODOL_Error("Keyframes are not supported (%d present)" % count_frames)

        file.seek(4 * 3, 1)             # icon colour, colour, special
        file.seek(1, 1)                 # vertex bone reference is simple

        # The checksum described above.
        position = file.tell()
        size_rest = binary.read_ulong(file)
        if position + size_rest != end:
            raise ODOL_Error("Rest data at %d is %d bytes, which ends at %d, not at the LOD end %d"
                             % (position, size_rest, position + size_rest, end))

        read_condensed_array(file, 4, file_size)        # clip flags

        # The first UV set is always present. The count that follows it is the total
        # number of sets, so it is one greater than the number still to come; the
        # importer only keeps the first.
        output.uvs = read_uv_set(file, file_size, True)
        count_uv_sets = read_count(file, file_size, "UV set")
        for _ in range(max(0, count_uv_sets - 1)):
            read_uv_set(file, file_size, False)

        count_vertices = read_count(file, file_size, "vertex")
        raw = read_compressed_array(file, 12, count_vertices)
        if len(raw) < 12 * count_vertices:
            raise ODOL_Error("Vertex array is %d bytes, expected %d" % (len(raw), 12 * count_vertices))

        values = struct.unpack("<%df" % (count_vertices * 3), raw)
        output.vertices = [values[i * 3:i * 3 + 3] for i in range(count_vertices)]

        raw = read_condensed_array(file, 4, file_size)  # normals
        output.normals = [decode_normal(value) for value in struct.unpack("<%dI" % (len(raw) // 4), raw)]

        # Everything past here (ST coordinates, bone references) is unused by the
        # importer, and the LOD end address already bounds it, so it is not read.

        if output.vertices and len(output.uvs) != len(output.vertices):
            raise ODOL_Error("LOD has %d vertices but %d UV pairs" % (len(output.vertices), len(output.uvs)))

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
        self.resolutions = []
        self.lod_starts = []
        self.lod_ends = []
        self.permanent = []
        self.lods = []
        self.failed_lods = []

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

        if output.version != VERSION:
            raise ODOL_Error("Unsupported ODOL version: %d (only %d is supported)" % (output.version, VERSION))

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
            skip_model_info(file, output.version, file_size)
        except (IndexError, EOFError, ValueError, struct.error, compression.LZO_Error) as ex:
            raise ODOL_Error("Failed to read past ModelInfo: %s" % ex) from ex

        read_lod_table(file, output, count_lods, file_size)

        # One unreadable LOD must not cost the ones that can be read: a model whose
        # shadow volume trips the layout is still worth importing for its visuals.
        # Every failure mode of the body reader is collected here, including the ones
        # the decompressor raises as IndexError at end of file.
        for index, (start, end) in enumerate(zip(output.lod_starts, output.lod_ends)):
            try:
                file.seek(start)
                lod = ODOL_LOD.read(file, output.version, end, file_size)
                lod.index = index
                lod.resolution = output.resolutions[index]
                output.lods.append(lod)
            except (ODOL_Error, compression.LZO_Error, EOFError, IndexError,
                    ValueError, struct.error, MemoryError) as ex:
                output.failed_lods.append((index, str(ex)))

        return output
