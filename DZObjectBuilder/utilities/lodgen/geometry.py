import bpy

from . import utils
from .constants import LOD_GEOMETRY, COLLECTION_GEOMETRIES


def generate_geometry_lod(context, obj):
    geometry_lod = context.scene.dzob_geometry_lod

    if not obj or not obj.data:
        print('WARNING: No valid object selected for Geometry LOD generation')
        return False

    geometries_collection = utils.get_or_create_collection(context, COLLECTION_GEOMETRIES)

    if geometry_lod.geometry_type == 'BOX':
        geometry_lod_obj = bpy.data.objects.new(
            geometry_lod.lod_name,
            bpy.data.meshes.new(geometry_lod.lod_name)
        )
        geometries_collection.objects.link(geometry_lod_obj)
        utils.create_bounding_box(context, obj, geometry_lod_obj)
    else:
        geometry_lod_obj = bpy.data.objects.new(geometry_lod.lod_name, bpy.data.meshes.new(geometry_lod.lod_name))
        geometries_collection.objects.link(geometry_lod_obj)

    _set_geometry_lod_properties(geometry_lod_obj, geometry_lod)
    utils.run_component_search(context, geometry_lod_obj)
    return True


def _set_geometry_lod_properties(obj, geometry_lod):
    obj.a3ob_properties_object.is_a3_lod = True
    obj.a3ob_properties_object.lod = LOD_GEOMETRY
    for prop in geometry_lod.named_properties:
        utils.add_named_property(obj, prop.name, prop.value)
