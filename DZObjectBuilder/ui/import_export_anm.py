import bpy
import bpy_extras

from ..io import import_anm
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


classes = (
    DZOB_OP_import_anm,
    DZOB_PT_import_anm_main
)


def menu_func_import(self, context):
    self.layout.operator(DZOB_OP_import_anm.bl_idname, text="DayZ animation (.anm)")


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

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    print("\t" + "UI: ANM Import / Export")


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("\t" + "UI: ANM Import / Export")
