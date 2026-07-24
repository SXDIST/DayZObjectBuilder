import bpy
import bpy_extras

from ..io import import_anm, export_anm
from ..io.data_anm import ANM_Error
from ..utilities import generic as utils


class DZOB_OP_import_anm(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    """Import DayZ animation (.anm) onto the active armature"""

    bl_idname = "dzob.import_anm"
    bl_label = "Import ANM"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}
    filename_ext = ".anm"

    filter_glob: bpy.props.StringProperty(
        default = "*.anm",
        options = {'HIDDEN'}
    )
    scale: bpy.props.FloatProperty(
        name = "Scale",
        description = "Scale factor applied to keyframe translations",
        default = 1.0,
        min = 0.0001,
        soft_max = 100.0
    )
    import_rotation: bpy.props.BoolProperty(
        name = "Rotation Keys",
        default = True
    )
    import_translation: bpy.props.BoolProperty(
        name = "Translation Keys",
        default = True
    )

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE'

    def draw(self, context):
        pass

    def execute(self, context):
        if context.object is None or context.object.type != 'ARMATURE':
            utils.op_report(self, {'ERROR'}, "Select the target armature first")
            return {'FINISHED'}

        try:
            bones, frames = import_anm.import_file(self, context)
        except ANM_Error as ex:
            utils.op_report(self, {'ERROR'}, str(ex))
            return {'FINISHED'}
        except Exception as ex:
            utils.op_report(self, {'ERROR'}, "Failed to import ANM: %s" % ex)
            return {'FINISHED'}

        utils.op_report(self, {'INFO'}, "Imported animation onto %d bones (%d frames)" % (bones, frames))

        return {'FINISHED'}


class DZOB_PT_import_anm_main(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Main"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "DZOB_OT_import_anm"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "scale")
        layout.prop(operator, "import_rotation")
        layout.prop(operator, "import_translation")


class DZOB_OP_export_anm(bpy.types.Operator, bpy_extras.io_utils.ExportHelper):
    """Export the active armature's animation to a DayZ animation (.anm)"""

    bl_idname = "dzob.export_anm"
    bl_label = "Export ANM"
    bl_options = {'REGISTER', 'PRESET'}
    filename_ext = ".anm"

    filter_glob: bpy.props.StringProperty(
        default = "*.anm",
        options = {'HIDDEN'}
    )
    version: bpy.props.EnumProperty(
        name = "Version",
        description = "ANM container version to write",
        items = (
            ('V6', "ANIMSET6", "Newer Enfusion format (used by the DayZ animation plugin)"),
            ('V5', "ANIMSET5", "Older format (vanilla player animations)"),
        ),
        default = 'V6'
    )
    use_scene_range: bpy.props.BoolProperty(
        name = "Scene Frame Range",
        description = "Use the scene start/end frames instead of the values below",
        default = True
    )
    frame_start: bpy.props.IntProperty(
        name = "Start",
        default = 0
    )
    frame_end: bpy.props.IntProperty(
        name = "End",
        default = 100
    )
    export_rotation: bpy.props.BoolProperty(
        name = "Rotation Keys",
        default = True
    )
    export_translation: bpy.props.BoolProperty(
        name = "Translation Keys",
        default = True
    )

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE'

    def draw(self, context):
        pass

    def execute(self, context):
        if context.object is None or context.object.type != 'ARMATURE':
            utils.op_report(self, {'ERROR'}, "Select the source armature first")
            return {'FINISHED'}

        try:
            bones, frames = export_anm.export_file(self, context)
        except Exception as ex:
            utils.op_report(self, {'ERROR'}, "Failed to export ANM: %s" % ex)
            return {'FINISHED'}

        utils.op_report(self, {'INFO'}, "Exported animation from %d bones (%d frames)" % (bones, frames))

        return {'FINISHED'}


class DZOB_PT_export_anm_main(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Main"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "DZOB_OT_export_anm"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        operator = context.space_data.active_operator

        layout.prop(operator, "version")
        layout.prop(operator, "use_scene_range")
        col = layout.column(align=True)
        col.enabled = not operator.use_scene_range
        col.prop(operator, "frame_start")
        col.prop(operator, "frame_end")
        layout.prop(operator, "export_rotation")
        layout.prop(operator, "export_translation")


classes = (
    DZOB_OP_import_anm,
    DZOB_PT_import_anm_main,
    DZOB_OP_export_anm,
    DZOB_PT_export_anm_main
)


if bpy.app.version >= (4, 1, 0):
    class DZOB_FH_import_anm(bpy.types.FileHandler):
        bl_idname = "DZOB_FH_import_anm"
        bl_label = "DayZ animation (.anm)"
        bl_import_operator = "dzob.import_anm"
        bl_file_extensions = ".anm"

        @classmethod
        def poll_drop(cls, context):
            return context.area and context.area.type == 'VIEW_3D'

    classes = (*classes, DZOB_FH_import_anm)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    print("\t" + "UI: ANM Import / Export")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("\t" + "UI: ANM Import / Export")
