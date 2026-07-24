import bpy

from ..utilities import data
from ..utilities.lodgen.constants import PROP_LOD_NO_SHADOW, PROP_AUTOCENTER


def get_property_names(self, context, edit_text):
    props = sorted(data.known_namedprops.keys())
    return [p for p in props if edit_text.lower() in p.lower()]


def get_property_values(self, context, edit_text):
    if self.name in data.known_namedprops:
        values = sorted(data.known_namedprops[self.name])
        return [v for v in values if edit_text.lower() in v.lower()]

    return []


class DZOB_PG_lodgen_namedprop(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(
        name = "Name",
        description = "Name of the custom property",
        default = "",
        search = get_property_names
    )
    value: bpy.props.StringProperty(
        name = "Value",
        description = "Value of the custom property",
        default = "",
        search = get_property_values
    )


class DZOB_PG_lodgen_resolution(bpy.types.PropertyGroup):
    active: bpy.props.BoolProperty(
        name = "Generate Resolution LODs",
        description = "Enable generation of resolution LODs",
        default = True
    )
    lod_prefix: bpy.props.StringProperty(
        name = "Prefix",
        description = "Prefix for resolution LOD object names",
        default = "Resolution "
    )
    first_lod: bpy.props.EnumProperty(
        name = "First LOD",
        description = "Select the starting LOD level",
        items = (
            ('LOD0', "LOD 0", "Start with LOD 0", 'OUTLINER_OB_MESH', 0),
            ('LOD1', "LOD 1", "Start with LOD 1", 'OUTLINER_OB_MESH', 1)
        ),
        default = 'LOD1'
    )
    preset: bpy.props.EnumProperty(
        name = "Preset",
        description = "Choose a preset for decimation ratios",
        items = (
            ('CUSTOM', "Custom", "Use custom decimate values", 'MODIFIER', 0),
            ('TRIS', "Tris", "Use tris-based decimate values", 'MODIFIER', 1),
            ('QUADS', "Quads", "Use quads-based decimate values", 'MODIFIER', 2)
        ),
        default = 'QUADS'
    )
    custom_decimate_values: bpy.props.FloatVectorProperty(
        name = "Custom Ratios",
        description = "Custom decimate ratios for LODs 0-3",
        size = 4, min = 0.0, max = 1.0,
        default = (0.75, 0.50, 0.25, 0.10)
    )
    tris_decimate_values: bpy.props.FloatVectorProperty(
        name = "Tris Ratios",
        description = "Tris-based decimate ratios for LODs 0-3",
        size = 4, min = 0.0, max = 1.0,
        default = (0.80, 0.60, 0.40, 0.20)
    )
    quads_decimate_values: bpy.props.FloatVectorProperty(
        name = "Quads Ratios",
        description = "Quads-based decimate ratios for LODs 0-3",
        size = 4, min = 0.0, max = 1.0,
        default = (0.50, 0.30, 0.20, 0.10)
    )
    named_properties: bpy.props.CollectionProperty(
        type = DZOB_PG_lodgen_namedprop,
        description = "List of custom properties for resolution LODs"
    )


class DZOB_PG_lodgen_geometry(bpy.types.PropertyGroup):
    active: bpy.props.BoolProperty(
        name = "Generate Geometry LOD",
        description = "Enable generation of geometry LOD",
        default = True
    )
    lod_name: bpy.props.StringProperty(
        name = "Name",
        description = "Name of the geometry LOD object",
        default = "Geometry"
    )
    geometry_type: bpy.props.EnumProperty(
        name = "Type",
        description = "Choose the type of geometry LOD to generate",
        items = (
            ('BOX', "Box", "Generate a single bounding box", 'MESH_CUBE', 0),
            ('NONE', "None", "Create empty object with properties", 'EMPTY_DATA', 1)
        ),
        default = 'BOX'
    )
    named_properties: bpy.props.CollectionProperty(
        type = DZOB_PG_lodgen_namedprop,
        description = "List of custom properties for geometry LOD"
    )


class DZOB_PG_lodgen_memory(bpy.types.PropertyGroup):
    active: bpy.props.BoolProperty(
        name = "Generate Memory LOD",
        description = "Enable generation of memory LOD",
        default = False
    )
    invview_point: bpy.props.BoolProperty(
        name = "Inview Point",
        description = "Add invview point to memory",
        default = True
    )
    bounding_box_points: bpy.props.BoolProperty(
        name = "Bounding Box Points",
        description = "Add boundingbox_min and boundingbox_max points",
        default = True
    )
    radius_point: bpy.props.BoolProperty(
        name = "Radius Point",
        description = "Add ce_radius point to memory",
        default = True
    )
    center_point: bpy.props.BoolProperty(
        name = "Center Point",
        description = "Add ce_center point to memory",
        default = True
    )
    named_properties: bpy.props.CollectionProperty(
        type = DZOB_PG_lodgen_namedprop,
        description = "List of custom properties for memory LOD"
    )


class DZOB_PG_lodgen_fire_geometry(bpy.types.PropertyGroup):
    active: bpy.props.BoolProperty(
        name = "Generate Fire Geometry LOD",
        description = "Enable generation of fire geometry LOD",
        default = False
    )
    quality: bpy.props.IntProperty(
        name = "Fire Geometry Quality",
        description = "1 = low polygon count, 10 = high polygon count",
        min = 1, max = 10,
        default = 2
    )
    named_properties: bpy.props.CollectionProperty(
        type = DZOB_PG_lodgen_namedprop,
        description = "List of custom properties for fire geometry LOD"
    )


class DZOB_PG_lodgen_view_geometry(bpy.types.PropertyGroup):
    active: bpy.props.BoolProperty(
        name = "Generate View Geometry LOD",
        description = "Enable generation of view geometry LOD",
        default = False
    )
    lod_name: bpy.props.StringProperty(
        name = "Name",
        description = "Name of the view geometry LOD object",
        default = "View Geometry"
    )
    named_properties: bpy.props.CollectionProperty(
        type = DZOB_PG_lodgen_namedprop,
        description = "List of custom properties for view geometry LOD"
    )


class DZOB_PG_lodgen_view_pilot(bpy.types.PropertyGroup):
    active: bpy.props.BoolProperty(
        name = "Generate View Pilot LOD",
        description = "Enable generation of view pilot LOD",
        default = False
    )
    lod_name: bpy.props.StringProperty(
        name = "Name",
        description = "Name of the view pilot LOD object",
        default = "View Pilot"
    )
    mesh_type: bpy.props.EnumProperty(
        name = "Mesh",
        description = "Mesh content for the View Pilot LOD",
        items = (
            ('BY_MESH', "By Mesh", "Copy the source mesh", 'MESH_DATA', 0),
            ('NONE', "None", "Create an empty mesh object", 'MESH_CUBE', 1)
        ),
        default = 'NONE'
    )
    named_properties: bpy.props.CollectionProperty(
        type = DZOB_PG_lodgen_namedprop,
        description = "List of custom properties for view pilot LOD"
    )


def ensure_default_properties(scene):
    # Seed the named properties the engine expects by default.
    res_props = scene.dzob_resolution_lods.named_properties
    if not any(p.name == PROP_LOD_NO_SHADOW for p in res_props):
        prop = res_props.add()
        prop.name = PROP_LOD_NO_SHADOW
        prop.value = '1'

    geo_props = scene.dzob_geometry_lod.named_properties
    if not any(p.name == PROP_AUTOCENTER for p in geo_props):
        prop = geo_props.add()
        prop.name = PROP_AUTOCENTER
        prop.value = '0'


@bpy.app.handlers.persistent
def on_scene_load(dummy):
    for scene in bpy.data.scenes:
        ensure_default_properties(scene)


def _deferred_init():
    for scene in bpy.data.scenes:
        ensure_default_properties(scene)

    return None


classes = (
    DZOB_PG_lodgen_namedprop,
    DZOB_PG_lodgen_resolution,
    DZOB_PG_lodgen_geometry,
    DZOB_PG_lodgen_memory,
    DZOB_PG_lodgen_fire_geometry,
    DZOB_PG_lodgen_view_geometry,
    DZOB_PG_lodgen_view_pilot
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.dzob_resolution_lods = bpy.props.PointerProperty(type=DZOB_PG_lodgen_resolution)
    bpy.types.Scene.dzob_geometry_lod = bpy.props.PointerProperty(type=DZOB_PG_lodgen_geometry)
    bpy.types.Scene.dzob_memory_lod = bpy.props.PointerProperty(type=DZOB_PG_lodgen_memory)
    bpy.types.Scene.dzob_fire_geometry_lod = bpy.props.PointerProperty(type=DZOB_PG_lodgen_fire_geometry)
    bpy.types.Scene.dzob_view_geometry_lod = bpy.props.PointerProperty(type=DZOB_PG_lodgen_view_geometry)
    bpy.types.Scene.dzob_view_pilot_lod = bpy.props.PointerProperty(type=DZOB_PG_lodgen_view_pilot)

    if on_scene_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_scene_load)

    bpy.app.timers.register(_deferred_init, first_interval=0.0)

    print("\t" + "Properties: LOD generator")


def unregister():
    if on_scene_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_scene_load)

    del bpy.types.Scene.dzob_view_pilot_lod
    del bpy.types.Scene.dzob_view_geometry_lod
    del bpy.types.Scene.dzob_fire_geometry_lod
    del bpy.types.Scene.dzob_memory_lod
    del bpy.types.Scene.dzob_geometry_lod
    del bpy.types.Scene.dzob_resolution_lods

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("\t" + "Properties: LOD generator")
