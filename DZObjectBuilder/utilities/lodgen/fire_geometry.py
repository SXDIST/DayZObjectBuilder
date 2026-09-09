import bpy
import bmesh

from . import utils
from .constants import LOD_FIRE_GEOMETRY, COLLECTION_GEOMETRIES


def generate_fire_geometry_lod(context, obj):
    fire_geometry_lod = context.scene.dzob_fire_geometry_lod

    if not obj or not obj.data:
        print('WARNING: No valid object selected for Fire Geometry LOD generation')
        return False

    geometries_collection = utils.get_or_create_collection(context, COLLECTION_GEOMETRIES)

    fire_obj = utils.duplicate_object(context, obj, geometries_collection)
    fire_obj.name = "Fire Geometry"
    fire_obj.data.name = "Fire Geometry"

    for child in list(fire_obj.children):
        bpy.data.objects.remove(child, do_unlink=True)
    fire_obj.modifiers.clear()

    # Build convex hull via bmesh API - no context/mode dependency
    _build_convex_hull(fire_obj)

    decimate_ratio = max(0.1, fire_geometry_lod.quality / 10.0)

    if decimate_ratio < 1.0:
        decimate = fire_obj.modifiers.new(name='Decimate_Quality', type='DECIMATE')
        decimate.ratio = decimate_ratio
        _apply_modifiers(context, fire_obj)
        # Collapse decimation moves vertices off the hull, so the mesh is not convex any
        # more. Hulling the decimated points again restores convexity at the same vertex
        # budget the quality setting asked for.
        _build_convex_hull(fire_obj)

    triangulate = fire_obj.modifiers.new(name='Triangulate', type='TRIANGULATE')
    triangulate.min_vertices = 4
    triangulate.keep_custom_normals = False
    triangulate.quad_method = 'BEAUTY'
    triangulate.ngon_method = 'BEAUTY'

    _apply_modifiers(context, fire_obj)

    fire_obj.a3ob_properties_object.is_a3_lod = True
    fire_obj.a3ob_properties_object.lod = LOD_FIRE_GEOMETRY

    for prop in fire_geometry_lod.named_properties:
        utils.add_named_property(fire_obj, prop.name, prop.value)

    utils.run_component_search(context, fire_obj)
    return True


def _apply_modifiers(context, obj):
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(eval_obj, depsgraph=depsgraph)
    old_mesh = obj.data
    obj.data = new_mesh
    obj.modifiers.clear()
    bpy.data.meshes.remove(old_mesh)


def _build_convex_hull(obj):
    # bmesh.ops.convex_hull only *adds* the hull faces, it does not remove the topology it
    # was handed. Hulling the mesh in place leaves every original face whose vertices all
    # happen to sit on the hull, so the result keeps the model's concavities and is not a
    # convex volume at all. Feed it a bare point cloud instead: nothing survives that the
    # hull did not produce.
    bm = bmesh.new()
    for vert in obj.data.vertices:
        bm.verts.new(vert.co)

    bm.verts.ensure_lookup_table()
    result = bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)

    # geom_interior and geom_unused can reference the same element more than once;
    # bmesh.ops.delete rejects geom lists with duplicates, so dedupe before deleting.
    del_geom = result.get("geom_interior", []) + result.get("geom_unused", [])
    seen = set()
    del_geom = [g for g in del_geom if id(g) not in seen and not seen.add(id(g))]
    if del_geom:
        bmesh.ops.delete(bm, geom=del_geom, context='VERTS')

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
