import bpy
from mathutils import Vector

from . import utils
from .constants import LOD_MEMORY, COLLECTION_POINT_CLOUDS


def generate_memory_lod(context, obj):
    memory_lod = context.scene.dzob_memory_lod

    if not obj or not obj.data:
        print('WARNING: No valid object selected for Memory LOD generation')
        return False

    point_clouds_collection = utils.get_or_create_collection(context, COLLECTION_POINT_CLOUDS)

    memory_obj = _create_memory_points(obj, memory_lod)
    if not memory_obj:
        print('WARNING: No memory points were enabled - Memory LOD not created')
        return False

    point_clouds_collection.objects.link(memory_obj)
    memory_obj.a3ob_properties_object.is_a3_lod = True
    memory_obj.a3ob_properties_object.lod = LOD_MEMORY

    for prop in memory_lod.named_properties:
        utils.add_named_property(memory_obj, prop.name, prop.value)

    return True


def _create_memory_points(source_obj, memory_lod):
    mesh = bpy.data.meshes.new("Memory")
    memory_obj = bpy.data.objects.new("Memory", mesh)

    local_bbox_center = sum((Vector(v) for v in source_obj.bound_box), Vector((0, 0, 0))) / 8

    vertices = []
    vertex_groups = []

    if memory_lod.invview_point:
        # invView = the inventory-preview camera position. It must sit along the item's
        # THINNEST world axis (the flattening axis for ground clothing) so the camera looks
        # squarely at the broad face, not off to +Y where a flat item is seen edge-on.
        # Distance from centre = the larger of the two in-plane extents, so the whole item
        # frames.
        world_corners = [source_obj.matrix_world @ Vector(corner) for corner in source_obj.bound_box]
        bmin = Vector((min(c.x for c in world_corners), min(c.y for c in world_corners), min(c.z for c in world_corners)))
        bmax = Vector((max(c.x for c in world_corners), max(c.y for c in world_corners), max(c.z for c in world_corners)))
        center = (bmin + bmax) * 0.5
        ext = bmax - bmin
        axis = min((0, 1, 2), key=lambda i: ext[i])              # thinnest axis = camera direction
        frame = max(ext[(axis + 1) % 3], ext[(axis + 2) % 3])    # in-plane size to frame
        invview_point = center.copy()
        invview_point[axis] = center[axis] + frame * 1.15   # ~in-plane size + 15% framing margin
        vertices.append(invview_point)
        vertex_groups.append("invview")

    # Compute true world-space bounding box from all 8 corners (correct for rotated objects)
    bbox_max_world = None
    bbox_min_world = None
    if memory_lod.bounding_box_points or memory_lod.radius_point:
        world_corners = [source_obj.matrix_world @ Vector(v) for v in source_obj.bound_box]
        bbox_max_world = Vector((
            max(v.x for v in world_corners),
            max(v.y for v in world_corners),
            max(v.z for v in world_corners),
        ))
        if memory_lod.bounding_box_points:
            bbox_min_world = Vector((
                min(v.x for v in world_corners),
                min(v.y for v in world_corners),
                min(v.z for v in world_corners),
            ))

    if memory_lod.bounding_box_points:
        vertices.extend([bbox_min_world, bbox_max_world])
        vertex_groups.extend(["boundingbox_min", "boundingbox_max"])

    if memory_lod.radius_point:
        vertices.append(bbox_max_world)
        vertex_groups.append("ce_radius")

    if memory_lod.center_point:
        vertices.append(source_obj.matrix_world @ local_bbox_center)
        vertex_groups.append("ce_center")

    if not vertices:
        bpy.data.objects.remove(memory_obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        return None

    mesh.from_pydata(vertices, [], [])
    mesh.update()

    for group_name in set(vertex_groups):
        vg = memory_obj.vertex_groups.new(name=group_name)
        for i, vg_name in enumerate(vertex_groups):
            if vg_name == group_name:
                vg.add([i], 1.0, 'ADD')

    return memory_obj
