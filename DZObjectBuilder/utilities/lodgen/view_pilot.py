import bpy

from . import utils
from .constants import LOD_VIEW_PILOT, COLLECTION_VISUALS


def generate_view_pilot_lod(context, obj):
    view_pilot_lod = context.scene.dzob_view_pilot_lod

    if not obj or not obj.data:
        print('WARNING: No valid object selected for View Pilot LOD generation')
        return False

    visuals_collection = utils.get_or_create_collection(context, COLLECTION_VISUALS)
    name = view_pilot_lod.lod_name

    if view_pilot_lod.mesh_type == 'BY_MESH':
        view_obj = utils.duplicate_object(context, obj, visuals_collection)
        view_obj.name = name
        view_obj.data.name = name
    else:
        view_obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        visuals_collection.objects.link(view_obj)

    view_obj.a3ob_properties_object.is_a3_lod = True
    view_obj.a3ob_properties_object.lod = LOD_VIEW_PILOT

    for prop in view_pilot_lod.named_properties:
        utils.add_named_property(view_obj, prop.name, prop.value)

    return True
