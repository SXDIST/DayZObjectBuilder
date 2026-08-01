import bpy
import bmesh
from mathutils import Matrix, Vector

from .constants import COLLECTION_ORDER


def run_component_search(context, obj):
    # Collision component detection. This used to bridge out to the Arma 3 Object
    # Builder addon; it is now an in-addon operator, so it is called directly.
    try:
        with context.temp_override(active_object=obj, selected_objects=[obj]):
            bpy.ops.dzob.find_components()
    except Exception as ex:
        print("WARNING: find_components failed: %s" % ex)


def get_local_bounds(context, obj):
    # Bounds have to be measured in the object's own space. Transforming the corners of
    # the local bounding box to world space gives the AABB of a rotated AABB, which is
    # inflated on every axis the object is rotated around, and the box that comes out of
    # it is aligned to the world instead of to the model.
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)

    try:
        mesh = eval_obj.to_mesh()
    except RuntimeError:
        return None

    if mesh is None or not mesh.vertices:
        eval_obj.to_mesh_clear()
        return None

    coords = [0.0] * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", coords)
    eval_obj.to_mesh_clear()

    x_coords, y_coords, z_coords = coords[0::3], coords[1::3], coords[2::3]
    min_corner = Vector((min(x_coords), min(y_coords), min(z_coords)))
    max_corner = Vector((max(x_coords), max(y_coords), max(z_coords)))

    return min_corner, max_corner


def copy_object_transform(source_obj, target_obj):
    # A generated LOD only lines up with the visual LODs if it sits in the same frame as
    # its source: same local transform, same parenting, same constraints. The resolution
    # LODs are copies of the source and get this for free, generated ones do not.
    target_obj.matrix_basis = source_obj.matrix_basis.copy()
    target_obj.parent = source_obj.parent
    target_obj.matrix_parent_inverse = source_obj.matrix_parent_inverse.copy()

    for constraint in source_obj.constraints:
        target_obj.constraints.copy(constraint)


def create_bounding_box(context, source_obj, target_obj=None):
    if not source_obj or not source_obj.data:
        return None

    bounds = get_local_bounds(context, source_obj)
    if bounds is None:
        return None

    min_corner, max_corner = bounds
    size = max_corner - min_corner
    center = (max_corner + min_corner) / 2

    if target_obj is None:
        # Create a new standalone object; caller is responsible for collection placement
        target_obj = bpy.data.objects.new("BoundingBox", bpy.data.meshes.new("BoundingBox"))
        context.scene.collection.objects.link(target_obj)

    # Bake the extents into the mesh rather than into the object scale, so the LOD holds
    # its real dimensions whether or not the transforms get applied on export.
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(center) @ Matrix.Diagonal(size).to_4x4())
    bm.to_mesh(target_obj.data)
    bm.free()
    target_obj.data.update()

    copy_object_transform(source_obj, target_obj)

    return target_obj


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
