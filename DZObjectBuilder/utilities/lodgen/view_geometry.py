from . import utils
from .constants import LOD_VIEW_GEOMETRY, COLLECTION_GEOMETRIES


def generate_view_geometry_lod(context, obj):
    view_geometry_lod = context.scene.dzob_view_geometry_lod

    if not obj or not obj.data:
        print('WARNING: No valid object selected for View Geometry LOD generation')
        return False

    geometries_collection = utils.get_or_create_collection(context, COLLECTION_GEOMETRIES)

    view_obj = utils.create_bounding_box(context, obj)
    if not view_obj:
        print('WARNING: Failed to create bounding box for View Geometry LOD')
        return False

    view_obj.name = view_geometry_lod.lod_name

    for collection in list(view_obj.users_collection):
        collection.objects.unlink(view_obj)
    geometries_collection.objects.link(view_obj)

    view_obj.a3ob_properties_object.is_a3_lod = True
    view_obj.a3ob_properties_object.lod = LOD_VIEW_GEOMETRY

    for prop in view_geometry_lod.named_properties:
        utils.add_named_property(view_obj, prop.name, prop.value)

    utils.run_component_search(context, view_obj)
    return True
