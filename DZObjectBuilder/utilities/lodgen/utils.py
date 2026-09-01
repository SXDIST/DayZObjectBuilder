import re

import bpy
import bmesh
from mathutils import Matrix, Vector

from .constants import COLLECTION_ORDER

# Blender uniquifies datablock names with a .001 suffix. A "Visuals" collection that
# already exists in another scene forces this scene's own one to be created as
# "Visuals.001", so every lookup here has to match on the base name.
NAME_SUFFIX_PATTERN = re.compile(r"\.\d{3}$")


def run_component_search(context, obj):
    # Collision component detection. This used to bridge out to the Arma 3 Object
    # Builder addon; it is now an in-addon operator, so it is called directly.
    try:
        with context.temp_override(active_object=obj, selected_objects=[obj]):
            bpy.ops.dzob.find_components()
    except Exception as ex:
        print("WARNING: find_components failed: %s" % ex)


def get_world_bounds(context, obj):
    # Bounds are measured over the evaluated vertices in world space, which is the frame
    # the model is actually seen and exported in - the export applies the object
    # transforms, so the axes the engine ends up with are these.
    #
    # Neither shortcut works here. Transforming the 8 corners of `bound_box` gives the
    # AABB of an AABB, inflated on every axis the object is rotated around. Measuring in
    # the object's own space instead trades that for the same fault one level down: a
    # mesh that sits diagonally inside its own local space (which is the normal state of
    # an imported .p3d, where the object transform is what stands the model upright)
    # gets a local AABB spanning the diagonal. A dagger 0.05 x 0.05 x 0.28 in the world
    # measured 7.0 x 28.8 x 24.6 locally, and the box built from it was five times too
    # wide.
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)

    try:
        mesh = eval_obj.to_mesh()
    except RuntimeError:
        return None

    if mesh is None or not mesh.vertices:
        eval_obj.to_mesh_clear()
        return None

    matrix = eval_obj.matrix_world
    coords = [matrix @ vert.co for vert in mesh.vertices]
    eval_obj.to_mesh_clear()

    min_corner = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    max_corner = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))

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

    bounds = get_world_bounds(context, source_obj)
    if bounds is None:
        return None

    min_corner, max_corner = bounds
    size = max_corner - min_corner
    center = (max_corner + min_corner) / 2

    if target_obj is None:
        # Create a new standalone object; caller is responsible for collection placement
        target_obj = bpy.data.objects.new("BoundingBox", bpy.data.meshes.new("BoundingBox"))
        context.scene.collection.objects.link(target_obj)

    copy_object_transform(source_obj, target_obj)

    # The box is world aligned and tight around the model, but it is written into the
    # LOD's own space so the LOD still sits in the frame of its source. Copying the
    # transform makes the target's world matrix the source's, so that is what the world
    # space corners are brought back through. The extents go into the mesh rather than
    # into the object scale, so the LOD holds its real dimensions whether or not the
    # transforms get applied on export.
    to_local = source_obj.matrix_world.inverted_safe()

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0,
                          matrix=to_local @ Matrix.Translation(center) @ Matrix.Diagonal(size).to_4x4())
    bm.to_mesh(target_obj.data)
    bm.free()
    target_obj.data.update()

    return target_obj


def base_collection_name(name):
    return NAME_SUFFIX_PATTERN.sub("", name)


def iter_scene_collections(scene):
    # Every collection reachable from the scene root, the root itself excluded.
    stack = list(scene.collection.children)
    while stack:
        collection = stack.pop()
        yield collection
        stack.extend(collection.children)


def find_scene_collection(scene, collection_name):
    # Exact name wins over a suffixed one, so a scene that owns the plain "Visuals" keeps
    # using it even if a "Visuals.001" also ended up somewhere under its root.
    fallback = None
    for collection in iter_scene_collections(scene):
        if collection.name == collection_name:
            return collection
        if fallback is None and base_collection_name(collection.name) == collection_name:
            fallback = collection

    return fallback


def get_or_create_collection(context, collection_name):
    # Scoped to the current scene on purpose. Collections are file wide datablocks, so a
    # lookup in bpy.data hands back the "Visuals" of whichever scene happens to own that
    # name, and the generated LODs then land in another scene's collection - which the
    # collection sorting afterwards links into this scene, dragging that scene's whole
    # model in with it. Working on several models in one .blend by switching scenes is
    # the normal way to use this, so the collections have to be resolved per scene.
    scene = context.scene
    existing = find_scene_collection(scene, collection_name)
    if existing is not None:
        return existing

    new_collection = bpy.data.collections.new(collection_name)
    scene.collection.children.link(new_collection)
    return new_collection


def get_or_create_subcollection(parent_collection, collection_name):
    for child in parent_collection.children:
        if child.name == collection_name:
            return child
    new_collection = bpy.data.collections.new(collection_name)
    parent_collection.children.link(new_collection)
    return new_collection


def organize_collections(context):
    # Only the scene's own top level collections are reordered. Reaching into bpy.data
    # here would link other scenes' collections into this one; reaching into nested ones
    # would yank a collection the user deliberately parented somewhere up to the root.
    scene = context.scene

    matched = {}
    for collection in scene.collection.children:
        base = base_collection_name(collection.name)
        if base in COLLECTION_ORDER and base not in matched:
            matched[base] = collection

    ordered = [matched[name] for name in COLLECTION_ORDER if name in matched]
    for collection in ordered:
        scene.collection.children.unlink(collection)
    for collection in ordered:
        scene.collection.children.link(collection)


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
