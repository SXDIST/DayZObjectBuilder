# Build Blender objects (armature, mesh, skin weights) from a parsed DayZ .xob
# model. The heavy binary parsing lives in the bpy-free data_xob module.


import os

import bpy
from mathutils import Vector, Quaternion, Matrix

from . import data_xob
from ..utilities.logger import ProcessLogger
from ..utilities import dayz_naming


# Enfusion is Y-up; convert to Blender Z-up with a proper rotation (no mirroring
# so face winding and left/right stay intact).
def _conv(v):
    return Vector((v[0], -v[2], v[1]))


def _world_heads(bones):
    world = [None] * len(bones)

    def resolve(i):
        if world[i] is None:
            b = bones[i]
            q = Quaternion((b.rot[3], b.rot[0], b.rot[1], b.rot[2]))
            local = Matrix.Translation(b.pos) @ q.to_matrix().to_4x4()
            base = resolve(b.parent) if b.parent >= 0 else Matrix.Identity(4)
            world[i] = base @ local
        return world[i]

    return [resolve(i).to_translation() for i in range(len(bones))]


def build_armature(bones, name, collection):
    heads = [_conv(h) for h in _world_heads(bones)]
    bone_names = [dayz_naming.to_pascal_case(b.name) for b in bones]

    children = {}
    for i, b in enumerate(bones):
        children.setdefault(b.parent, []).append(i)

    armature = bpy.data.armatures.new(name)
    armature.display_type = 'STICK'
    obj = bpy.data.objects.new(name, armature)
    obj.show_in_front = True
    collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = []
    for i in range(len(bones)):
        eb = armature.edit_bones.new(bone_names[i])
        head = heads[i]
        tail = None
        for c in children.get(i, []):
            if (heads[c] - head).length > 1e-5:
                tail = heads[c]
                break
        if tail is None:
            tail = head + Vector((0.0, 0.0, 0.05))
        eb.head = head
        eb.tail = tail
        edit_bones.append(eb)

    for i, b in enumerate(bones):
        if b.parent >= 0:
            edit_bones[i].parent = edit_bones[b.parent]

    bpy.ops.object.mode_set(mode='OBJECT')

    return obj, bone_names


def _get_material(name):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    return mat


def build_mesh(mesh, bone_names, material_name, name, collection, arm_obj):
    me = bpy.data.meshes.new(name)
    verts = [tuple(_conv(v.pos)) for v in mesh.verts]
    me.from_pydata(verts, [], [f for f in mesh.faces])
    me.update()

    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)

    if material_name:
        me.materials.append(_get_material(material_name))

    if mesh.verts and mesh.verts[0].uvs:
        uv_layer = me.uv_layers.new(name="UVMap")
        for loop in me.loops:
            uv_layer.data[loop.index].uv = mesh.verts[loop.vertex_index].uvs[0]

    # Shade smooth but leave the normals unlocked (auto, geometry based). The
    # .xob carries baked vertex normals, but importing them as custom split
    # normals locks the mesh shading, which is unwanted for an editable base
    # body. Keeping free normals is equivalent to a "Reset Vectors".
    for poly in me.polygons:
        poly.use_smooth = True

    if arm_obj is not None and mesh.skinned:
        groups = {}
        for vi, vert in enumerate(mesh.verts):
            for bone_idx, weight in vert.weights:
                gname = bone_names[bone_idx]
                group = groups.get(gname)
                if group is None:
                    group = obj.vertex_groups.new(name=gname)
                    groups[gname] = group
                group.add([vi], weight, 'REPLACE')

        modifier = obj.modifiers.new("Armature", 'ARMATURE')
        modifier.object = arm_obj
        obj.parent = arm_obj

    return obj


def import_file(operator, context):
    logger = ProcessLogger()
    logger.start_subproc("XOB import from %s" % operator.filepath)

    model = data_xob.XOB_Model.read_file(operator.filepath, scale=operator.scale)
    logger.step("Format: XOB%d" % model.version)
    logger.step("Bones: %d, Meshes: %d, Materials: %d" % (len(model.bones), len(model.meshes), len(model.materials)))

    base = os.path.splitext(os.path.basename(operator.filepath))[0]
    collection = bpy.data.collections.new(base)
    context.scene.collection.children.link(collection)

    arm_obj = None
    if operator.import_armature and model.bones:
        arm_obj, bone_names = build_armature(model.bones, base + "_skeleton", collection)
        logger.step("Built armature (%d bones)" % len(model.bones))
    else:
        bone_names = [dayz_naming.to_pascal_case(b.name) for b in model.bones]

    mesh_count = 0
    if operator.import_mesh:
        for i, mesh in enumerate(model.meshes):
            mesh_name = mesh.name or ("%s_%d" % (base, i))
            material_name = model.materials[mesh.material] if 0 <= mesh.material < len(model.materials) else ""
            build_mesh(mesh, bone_names, material_name, mesh_name, collection,
                       arm_obj if operator.import_weights else None)
            mesh_count += 1
        logger.step("Built %d mesh object(s)" % mesh_count)

    logger.end_subproc()
    logger.step("XOB import finished")

    return len(model.bones), mesh_count
