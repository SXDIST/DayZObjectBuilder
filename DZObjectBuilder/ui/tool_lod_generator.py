import bpy

from ..props.lod_generator import ensure_default_properties
from ..utilities import lodgen
from ..utilities import generic as utils


# LOD section -> scene property holding its settings
PROP_PATHS = {
    'RESOLUTION': "dzob_resolution_lods",
    'GEOMETRY': "dzob_geometry_lod",
    'MEMORY': "dzob_memory_lod",
    'FIRE_GEOMETRY': "dzob_fire_geometry_lod",
    'VIEW_GEOMETRY': "dzob_view_geometry_lod",
    'VIEW_PILOT': "dzob_view_pilot_lod"
}

TARGET_ITEMS = (
    ('RESOLUTION', "Resolution", ""),
    ('GEOMETRY', "Geometry", ""),
    ('MEMORY', "Memory", ""),
    ('FIRE_GEOMETRY', "Fire Geometry", ""),
    ('VIEW_GEOMETRY', "View Geometry", ""),
    ('VIEW_PILOT', "View Pilot", "")
)


class DZOB_OT_lodgen_namedprop_add(bpy.types.Operator):
    """Add a named property to the LOD section"""

    bl_idname = "dzob.lodgen_namedprop_add"
    bl_label = "Add Property"
    bl_options = {'INTERNAL', 'UNDO'}

    target: bpy.props.EnumProperty(items=TARGET_ITEMS)

    def execute(self, context):
        getattr(context.scene, PROP_PATHS[self.target]).named_properties.add()

        return {'FINISHED'}


class DZOB_OT_lodgen_namedprop_remove(bpy.types.Operator):
    """Remove the named property from the LOD section"""

    bl_idname = "dzob.lodgen_namedprop_remove"
    bl_label = "Remove Property"
    bl_options = {'INTERNAL', 'UNDO'}

    target: bpy.props.EnumProperty(items=TARGET_ITEMS)
    index: bpy.props.IntProperty()

    def execute(self, context):
        props = getattr(context.scene, PROP_PATHS[self.target]).named_properties
        if 0 <= self.index < len(props):
            props.remove(self.index)

        return {'FINISHED'}


class DZOB_OT_lodgen_generate(bpy.types.Operator):
    """Generate the enabled LODs from the active object"""

    bl_idname = "dzob.lodgen_generate"
    bl_label = "Generate LODs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def execute(self, context):
        scene = context.scene

        if not context.active_object:
            utils.op_report(self, {'WARNING'}, "Select an object first")
            return {'CANCELLED'}

        if context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # new scenes may not have been seeded yet
        ensure_default_properties(scene)

        source = context.active_object

        if scene.dzob_geometry_lod.active:
            lodgen.generate_geometry_lod(context, source)

        if scene.dzob_memory_lod.active:
            lodgen.generate_memory_lod(context, source)

        if scene.dzob_fire_geometry_lod.active:
            lodgen.generate_fire_geometry_lod(context, source)

        if scene.dzob_view_geometry_lod.active:
            lodgen.generate_view_geometry_lod(context, source)

        if scene.dzob_view_pilot_lod.active:
            lodgen.generate_view_pilot_lod(context, source)

        if scene.dzob_resolution_lods.active:
            lodgen.generate_resolution_lods(context, source)

        lodgen.utils.organize_collections(context)

        return {'FINISHED'}


def _draw_named_properties(layout, settings, target, title="Named Properties"):
    box = layout.box()
    box.label(text=title, icon='PROPERTIES')

    for i, prop in enumerate(settings.named_properties):
        row = box.row(align=True)
        row.prop(prop, "name", text="", icon='FILE_TEXT')
        row.prop(prop, "value", text="", icon='TEXT')
        op = row.operator("dzob.lodgen_namedprop_remove", text="", icon='X')
        op.target = target
        op.index = i

    op = box.row().operator("dzob.lodgen_namedprop_add", text="Add Property", icon='PLUS')
    op.target = target


class DZOB_PT_lod_generator(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Object Builder"
    bl_label = "Auto LODs Generator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return True

    def draw_header(self, context):
        self.layout.label(icon='FORCE_VORTEX')

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        resolution_lods = scene.dzob_resolution_lods
        geometry_lod = scene.dzob_geometry_lod
        memory_lod = scene.dzob_memory_lod
        fire_geometry_lod = scene.dzob_fire_geometry_lod
        view_geometry_lod = scene.dzob_view_geometry_lod
        view_pilot_lod = scene.dzob_view_pilot_lod

        # Resolution LODs
        layout.row(align=True).prop(resolution_lods, "active", icon='MOD_DECIM', text="Resolution LODs")

        if resolution_lods.active:
            box = layout.box()
            box.label(text="Resolution LODs", icon='MESH_CUBE')
            box.row(align=True).prop(resolution_lods, "lod_prefix", icon='FONT_DATA')
            box.row(align=True).prop(resolution_lods, "first_lod", expand=True)
            box.row(align=True).prop(resolution_lods, "preset", expand=True)

            first_lod = 1 if resolution_lods.first_lod == 'LOD1' else 0
            preset = resolution_lods.preset
            values_prop = (
                "custom_decimate_values" if preset == 'CUSTOM'
                else "tris_decimate_values" if preset == 'TRIS'
                else "quads_decimate_values"
            )
            for i in range(first_lod, first_lod + 4):
                row = box.row(align=True)
                row.enabled = preset == 'CUSTOM'
                row.prop(resolution_lods, values_prop, index=i - first_lod, text="LOD%d" % i, icon='MESH_DATA')

            box.separator()
            box.row(align=True).prop(view_pilot_lod, "active", icon='VIEW_CAMERA', text="View Pilot LOD")
            if view_pilot_lod.active:
                box.box().row(align=True).prop(view_pilot_lod, "mesh_type", expand=True)

            _draw_named_properties(layout, resolution_lods, 'RESOLUTION')

            if view_pilot_lod.active:
                _draw_named_properties(layout, view_pilot_lod, 'VIEW_PILOT', "View Pilot - Named Properties")

        # Geometry LOD
        layout.row(align=True).prop(geometry_lod, "active", icon='MODIFIER', text="Geometry LOD")

        if geometry_lod.active:
            box = layout.box()
            box.label(text="Geometry LOD", icon='MESH_CUBE')
            box.row(align=True).prop(geometry_lod, "lod_name", icon='FONT_DATA')
            box.row(align=True).prop(geometry_lod, "geometry_type", expand=True)

            _draw_named_properties(layout, geometry_lod, 'GEOMETRY')

        # Memory LOD
        layout.row(align=True).prop(memory_lod, "active", icon='EMPTY_AXIS', text="Memory LOD")

        if memory_lod.active:
            box = layout.box()
            box.label(text="Memory LOD", icon='EMPTY_AXIS')

            points = box.box()
            points.label(text="Standard Points", icon='MESH_CUBE')
            points.row(align=True).prop(memory_lod, "invview_point", icon='MESH_UVSPHERE')
            points.row(align=True).prop(memory_lod, "bounding_box_points", icon='MESH_CUBE')
            points.row(align=True).prop(memory_lod, "radius_point", icon='MESH_UVSPHERE')
            points.row(align=True).prop(memory_lod, "center_point", icon='MESH_UVSPHERE')

            _draw_named_properties(layout, memory_lod, 'MEMORY')

        # Fire Geometry LOD
        layout.row(align=True).prop(fire_geometry_lod, "active", icon='MODIFIER', text="Fire Geometry LOD")

        if fire_geometry_lod.active:
            box = layout.box()
            box.label(text="Fire Geometry LOD", icon='MODIFIER')
            row = box.row(align=True)
            row.label(text="Quality:")
            row.prop(fire_geometry_lod, "quality", text="", slider=True)

            _draw_named_properties(layout, fire_geometry_lod, 'FIRE_GEOMETRY')

        # View Geometry LOD
        layout.row(align=True).prop(view_geometry_lod, "active", icon='VIEW3D', text="View Geometry LOD")

        if view_geometry_lod.active:
            box = layout.box()
            box.label(text="View Geometry LOD", icon='VIEW3D')
            box.row(align=True).prop(view_geometry_lod, "lod_name", icon='FONT_DATA')

            _draw_named_properties(layout, view_geometry_lod, 'VIEW_GEOMETRY')

        row = layout.row(align=True)
        row.scale_y = 2.0
        row.operator("dzob.lodgen_generate", icon='PLAY', text="Generate LODs")


classes = (
    DZOB_OT_lodgen_namedprop_add,
    DZOB_OT_lodgen_namedprop_remove,
    DZOB_OT_lodgen_generate,
    DZOB_PT_lod_generator
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    print("\t" + "UI: LOD Generator")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("\t" + "UI: LOD Generator")
