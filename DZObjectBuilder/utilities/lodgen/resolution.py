from . import utils
from .constants import LOD_RESOLUTION, COLLECTION_VISUALS


def generate_resolution_lods(context, obj):
    resolution_lods = context.scene.dzob_resolution_lods

    if not obj or not obj.data:
        print('WARNING: No valid object selected for Resolution LODs generation')
        return False

    start_lod = 0 if resolution_lods.first_lod == 'LOD0' else 1

    visuals_collection = utils.get_or_create_collection(context, COLLECTION_VISUALS)

    if obj.users_collection:
        for collection in obj.users_collection:
            collection.objects.unlink(obj)
    visuals_collection.objects.link(obj)

    obj.name = f'{resolution_lods.lod_prefix}{start_lod}'
    obj.data.name = obj.name
    obj.a3ob_properties_object.is_a3_lod = True
    obj.a3ob_properties_object.lod = LOD_RESOLUTION
    obj.a3ob_properties_object.resolution = start_lod
    for prop in resolution_lods.named_properties:
        utils.add_named_property(obj, prop.name, prop.value)

    decimate_values = (
        resolution_lods.custom_decimate_values if resolution_lods.preset == 'CUSTOM'
        else resolution_lods.tris_decimate_values if resolution_lods.preset == 'TRIS'
        else resolution_lods.quads_decimate_values
    )

    for i, ratio in enumerate(decimate_values):
        lod_number = start_lod + i + 1
        dup_obj = utils.duplicate_object(context, obj, visuals_collection)
        dup_obj.name = f'{resolution_lods.lod_prefix}{lod_number}'
        dup_obj.data.name = dup_obj.name

        decimate = dup_obj.modifiers.new(name='Decimate', type='DECIMATE')
        decimate.ratio = ratio
        decimate.use_collapse_triangulate = True
        weighted_normal = dup_obj.modifiers.new(name='WeightedNormal', type='WEIGHTED_NORMAL')
        weighted_normal.use_face_influence = True
        weighted_normal.keep_sharp = True
        dup_obj.a3ob_properties_object.is_a3_lod = True
        dup_obj.a3ob_properties_object.resolution = lod_number
        for prop in resolution_lods.named_properties:
            utils.add_named_property(dup_obj, prop.name, prop.value)

    return True
