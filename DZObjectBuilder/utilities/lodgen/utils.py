import bpy
import bmesh
from mathutils import Vector

from .constants import COLLECTION_ORDER


def run_component_search(context, obj):
    # Collision component detection. This used to bridge out to the Arma 3 Object
    # Builder addon; it is now an in-addon operator, so it is called directly.
    try:
        with context.temp_override(active_object=obj, selected_objects=[obj]):
            bpy.ops.dzob.find_components()
    except Exception as ex:
        print("WARNING: find_components failed: %s" % ex)


def create_bounding_box(context, source_obj, target_obj=None):
    if not source_obj or not source_obj.data:
        return None

    # Use evaluated depsgraph so modifiers are included in bounds
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = source_obj.evaluated_get(depsgraph)

    coords = [eval_obj.matrix_world @ Vector(v) for v in eval_obj.bound_box]
    if not coords:
        return None

    x_coords = [v.x for v in coords]
    y_coords = [v.y for v in coords]
    z_coords = [v.z for v in coords]
    min_corner = Vector((min(x_coords), min(y_coords), min(z_coords)))
    max_corner = Vector((max(x_coords), max(y_coords), max(z_coords)))
    size = max_corner - min_corner
    center = (max_corner + min_corner) / 2

    if target_obj:
        # Write cube geometry directly into the existing object's mesh
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(target_obj.data)
        bm.free()
        target_obj.location = center
        target_obj.scale = size
    else:
        # Create a new standalone object; caller is responsible for collection placement
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        mesh = bpy.data.meshes.new("BoundingBox")
        bm.to_mesh(mesh)
        bm.free()
        box_obj = bpy.data.objects.new("BoundingBox", mesh)
        box_obj.location = center
        box_obj.scale = size
        context.scene.collection.objects.link(box_obj)
        return box_obj


def get_or_create_collection(context, collection_name):
    if collection_name in bpy.data.collections:
        return bpy.data.collections[collection_name]
    new_collection = bpy.data.collections.new(collection_name)
    context.scene.collection.children.link(new_collection)
    return new_collection


def get_or_create_subcollection(parent_collection, collection_name):
    for child in parent_collection.children:
        if child.name == collection_name:
            return child
    new_collection = bpy.data.collections.new(collection_name)
    parent_collection.children.link(new_collection)
    return new_collection


def organize_collections(context):
    scene = context.scene
    existing = [
        bpy.data.collections[name]
        for name in COLLECTION_ORDER
        if name in bpy.data.collections
    ]
    for col in existing:
        try:
            scene.collection.children.unlink(col)
        except RuntimeError:
            pass
    for col in existing:
        if col.name not in scene.collection.children:
            scene.collection.children.link(col)


def duplicate_object(context, obj, target_collection=None):
    if target_collection is None:
        target_collection = context.collection
    copy = obj.copy()
    copy.data = obj.data.copy()
    target_collection.objects.link(copy)
    for child in obj.children:
        child_copy = child.copy()
        if child_copy.data:
            child_copy.data = child_copy.data.copy()
        target_collection.objects.link(child_copy)
        child_copy.parent = copy
        child_copy.matrix_parent_inverse = copy.matrix_world.inverted()
    return copy


def add_named_property(obj, name, value):
    if not hasattr(obj, 'a3ob_properties_object'):
        return
    props = obj.a3ob_properties_object.properties
    if not any(p.name == name for p in props):
        item = props.add()
        item.name = name
        item.value = value
