# Converts the parsed ODOL structures from data_p3d_odol.py into the add-on's
# in-memory MLOD model (data_p3d.py). The rest of the add-on only ever sees a
# P3D_MLOD, so once a binarized file has been read and passed through here it is
# imported by exactly the same code path as an editable .p3d.
#
# The four geometry transforms below carry all the risk. Each was settled by
# measurement against the DayZ v54 corpus (55galDrum.p3d), NOT by copying the
# pre-measurement conversion sketch in the task brief, which is wrong on three of
# the four. What matters is that the values stored here are already correct for the
# downstream consumer; the objects bypass P3D_LOD.read entirely, so whatever byte
# level flips that reader performs on MLOD input are irrelevant here.
#
#   Vertices  ODOL v54 stores them in absolute model coordinates. Measured: the
#             vertex cloud fills bbox_min..bbox_max exactly while bbox_center is not
#             the origin (drum LOD 0: centre (-0.059, 0.418, 0.0)). Adding the
#             centre, as the brief sketch does, would shift every vertex off the box.
#             So no centre offset is applied. The frame is Y-up, the same as the
#             in-memory MLOD vertex, so no axis swap either.
#
#   Normals   Stored unchanged, NOT negated. Measured (Task 5, reconfirmed here): the
#             decoded ODOL normal already points outward on the drum's cylindrical
#             wall (834 outward vs 242 inward, the drum also modelling its inner
#             surface). That is the same outward orientation P3D_LOD.read yields, so
#             negating here - as the brief sketch does - would invert shading.
#
#   Winding   Kept as stored, NOT reversed. Measured: the stored winding's cross
#             product points outward on the wall (859 vs 217) and agrees with the
#             stored per-vertex normal on every one of the 1076 wall faces (0 agree
#             when reversed). Since the normals are not sign-flipped, the stored
#             winding already produces an outward face; reversing it would invert
#             every polygon.
#
#   UVs       Stored as (u, 1 - v). read_uv_set in data_p3d_odol.py decodes the raw
#             ODOL v (top-left origin, the BI on-disk convention) without flipping,
#             and the add-on's in-memory convention is bottom-left, exactly as
#             P3D_LOD.read stores (u, 1 - v) for MLOD input. So a single flip is
#             applied here; it is not double-applied, because the reader applied none.


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
    # Winding kept as stored (see module header). ODOL holds one normal and one UV
    # per vertex, both arrays parallel to the vertex array, so a face corner's normal
    # index and UV both come straight from its vertex index.
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

    # Vertices absolute, no centre offset; normals unchanged, not negated.
    output.verts = [(x, y, z, 0) for x, y, z in lod.vertices]
    output.normals = [(x, y, z) for x, y, z in lod.normals]

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
