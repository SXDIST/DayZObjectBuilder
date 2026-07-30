# Converts the parsed ODOL structures from data_p3d_odol.py into the add-on's
# in-memory MLOD model (data_p3d.py). The rest of the add-on only ever sees a
# P3D_MLOD, so once a binarized file has been read and passed through here it is
# imported by exactly the same code path as an editable .p3d.
#
# The four geometry transforms below carry all the risk. Each was settled by
# measurement against the DayZ v54 corpus (55galDrum.p3d). An earlier pass concluded
# vertices needed no axis swap and winding needed no reversal; both were wrong,
# because the "no swap" measurement (vertex cloud fills bbox_min..bbox_max) only
# checks the ODOL file's internal self-consistency - bbox and vertices come from the
# same raw frame, so that check passes trivially regardless of what "up" means in
# that frame, and can never distinguish "no swap needed" from "swap needed". The
# corrected measurement below instead checks the raw frame against real-world
# geometry directly.
#
#   Vertices  ODOL v54 stores them in absolute model coordinates (no centre offset:
#             the vertex cloud fills bbox_min..bbox_max exactly while bbox_center is
#             not the origin, e.g. drum LOD 0 centre (-0.059, 0.418, 0.0); adding the
#             centre would shift every vertex off the box). The raw frame is BI's
#             native Y-up - NOT already the in-memory MLOD (Blender Z-up) frame.
#             Measured on 55galDrum.p3d LOD 0: raw Y extent is 0.836 (a real
#             55-gallon drum's height) while raw X/Z extents are ~0.6-0.73 (its
#             diameter), and bbox_min.y is 0.0, i.e. the drum stands base-up from
#             Y = 0 in the raw frame - textbook Y-up. So the same axis swap
#             P3D_LOD.read_vert applies when reading MLOD off disk (swap Y and Z) is
#             required here too, to land in Blender's Z-up frame.
#
#   Normals   Axis-swapped the same way as vertices, NOT negated. Measured: the
#             decoded ODOL normal, swapped and dotted against the wall's outward
#             radial direction, points outward as often after the swap as before it
#             (1150 outward vs 292 inward either way, 55galDrum.p3d LOD 0 wall
#             faces) - a stored vector's alignment with a consistently-swapped
#             reference direction is unaffected by relabelling both the same way.
#             That already matches the outward orientation P3D_LOD.read yields, so
#             negating here would invert shading.
#
#   Winding   Reversed. Measured: with vertices left unswapped, the stored winding's
#             cross product points outward on the wall 1169/1442 times, agreeing
#             with the (also unswapped) stored normal. Swapping the vertex axes to
#             the corrected frame is an orientation-reversing transform (a
#             transposition, determinant -1) that flips every cross product's sign
#             without touching the stored normal vectors' alignment - so in the
#             corrected frame the same stored winding order now points outward only
#             273/1442 times. Reversing the per-face index order restores outward
#             winding in the corrected frame.
#
#   UVs       Stored as (u, 1 - v). read_uv_set in data_p3d_odol.py decodes the raw
#             ODOL v (top-left origin, the BI on-disk convention) without flipping,
#             and the add-on's in-memory convention is bottom-left, exactly as
#             P3D_LOD.read stores (u, 1 - v) for MLOD input. So a single flip is
#             applied here; it is not double-applied, because the reader applied none.
#             UVs are per-vertex data, unaffected by the position axis swap or the
#             winding reversal beyond following the same reversed index order.


from . import data_p3d as p3d


# Each ODOL section binds a run of faces to one texture and one material by index.
# Flatten that into a per-face (texture, material) pair, resolving the indices into
# the LOD's own texture and material name lists. Faces left uncovered by any section
# (there should be none in a well formed LOD) keep empty strings, which the add-on
# treats as the "no material" slot.
def face_materials(lod):
    textures = [""] * len(lod.faces)
    materials = [""] * len(lod.faces)

    for section in lod.sections:
        texture = ""
        if 0 <= section.texture_index < len(lod.textures):
            texture = lod.textures[section.texture_index]

        material = ""
        if 0 <= section.material_index < len(lod.materials):
            material = lod.materials[section.material_index]

        for face_index in range(section.face_start, section.face_end):
            if 0 <= face_index < len(lod.faces):
                textures[face_index] = texture
                materials[face_index] = material

    return textures, materials


def convert_face(lod, face_index, indices, textures, materials):
    # Winding reversed (see module header). ODOL holds one normal and one UV per
    # vertex, both arrays parallel to the vertex array, so a face corner's normal
    # index and UV both come straight from its vertex index; reversing the shared
    # index order up front keeps all three in sync.
    indices = list(reversed(indices))
    vertices = list(indices)
    normals = list(indices)

    uvs = []
    for vertex_index in indices:
        if 0 <= vertex_index < len(lod.uvs):
            u, v = lod.uvs[vertex_index]
        else:
            u, v = 0.0, 0.0

        uvs.append((u, 1 - v))

    # face[5] is the MLOD face flag; ODOL's per-face flags are not parsed, so 0.
    return [vertices, normals, uvs, textures[face_index], materials[face_index], 0]


def selection_tagg(lod, selection, count_verts, count_faces):
    tagg = p3d.P3D_TAGG()
    tagg.name = selection.name

    data = p3d.P3D_TAGG_DataSelection()
    data.count_verts = count_verts
    data.count_faces = count_faces

    if selection.vertices:
        # A skeleton-bone selection: per-vertex weights joined on from vertexBoneRef.
        data.weight_verts = [(vertex, weight) for vertex, weight
                             in zip(selection.vertices, selection.weights)
                             if 0 <= vertex < count_verts]
    elif selection.faces:
        # A hidden (texture) selection carries faces only. Select every vertex those
        # faces touch at full weight, so it survives as a usable vertex group.
        vertices = set()
        for face_index in selection.faces:
            if 0 <= face_index < len(lod.faces):
                vertices.update(lod.faces[face_index])

        data.weight_verts = [(vertex, 1.0) for vertex in sorted(vertices) if 0 <= vertex < count_verts]

    data.weight_faces = [(face_index, 1.0) for face_index in selection.faces if 0 <= face_index < count_faces]

    tagg.data = data
    return tagg


def convert_lod(lod):
    output = p3d.P3D_LOD()
    output.resolution = p3d.P3D_LOD_Resolution.from_float(lod.resolution)

    # Vertices absolute, no centre offset; axis swapped (Y/Z) to land in Blender's
    # Z-up frame, matching P3D_LOD.read_vert's swap of the on-disk MLOD frame.
    # Normals get the same axis swap, not negated (see module header).
    output.verts = [(x, z, y, 0) for x, y, z in lod.vertices]
    output.normals = [(x, z, y) for x, y, z in lod.normals]

    textures, materials = face_materials(lod)
    output.faces = [convert_face(lod, index, indices, textures, materials)
                    for index, indices in enumerate(lod.faces)]

    count_verts = len(output.verts)
    count_faces = len(output.faces)

    # UVSet 0 as a TAGG, per loop and flattened in face order. lod.uvsets() also
    # derives set 0 from the faces, so this is a redundant-but-consistent copy;
    # keeping the two identical is what makes the redundancy harmless.
    uv_tagg = p3d.P3D_TAGG()
    uv_tagg.name = "#UVSet#"
    uv_data = p3d.P3D_TAGG_DataUVSet()
    uv_data.id = 0
    uv_data.uvs = [uv for face in output.faces for uv in face[2]]
    uv_tagg.data = uv_data
    output.taggs.append(uv_tagg)

    for selection in lod.named_selections:
        if not selection.name:
            continue

        output.taggs.append(selection_tagg(lod, selection, count_verts, count_faces))

    return output


# Convert a whole parsed ODOL file. A single LOD that cannot be converted must not
# cost the rest of the model - this runs inside Blender, where one malformed LOD is
# still worth importing the others for - so each conversion is guarded and failures
# are collected on the result rather than raised.
def convert(odol_file):
    output = p3d.P3D_MLOD()
    output.version = odol_file.version
    output.failed_lods = []

    for lod in odol_file.lods:
        try:
            output.lods.append(convert_lod(lod))
        except Exception as ex:
            output.failed_lods.append((lod.index, str(ex)))

    return output
