import bpy
import bpy_extras

from ..io import import_xob
from ..io.data_xob import XOB_Error
from ..utilities import generic as utils


class DZOB_OP_import_xob(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    """Import DayZ Enfusion model (.xob)"""

    bl_idname = "dzob.import_xob"
    bl_label = "Import XOB"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}
    filename_ext = ".xob"

    filter_glob: bpy.props.StringProperty(
        default = "*.xob",
        options = {'HIDDEN'}
    )
    scale: bpy.props.FloatProperty(
        name = "Scale",
        description = "Scale factor applied to imported positions",
        default = 1.0,
        min = 0.0001,
        soft_max = 100.0
    )
    import_mesh: bpy.props.BoolProperty(
        name = "Mesh",
        description = "Import the model geometry",
        default = True
    )
    import_armature: bpy.props.BoolProperty(
        name = "Armature",
        description = "Build an armature from the model's skeleton",
        default = True
    )
    import_weights: bpy.props.BoolProperty(
        name = "Skin Weights",
        description = "Import vertex weights and bind the mesh to the armature",
        default = True
    )

    def draw(self, context):
        pass

    def execute(self, context):
        try:
            bones, meshes = import_xob.import_file(self, context)
        except XOB_Error as ex:
            utils.op_report(self, {'ERROR'}, str(ex))
            return {'FINISHED'}
        except Exception as ex:
            utils.op_report(self, {'ERROR'}, "Failed to import XOB: %s" % ex)
            return {'FINISHED'}

        utils.op_report(self, {'INFO'}, "Imported %d bones and %d mesh(es)" % (bones, meshes))

        return {'FINISHED'}


class DZOB_PT_import_xob_main(bpy.types.Panel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_label = "Main"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "DZOB_OT_import_xob"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        sfile = context.space_data
        operator = sfile.active_operator

        layout.prop(operator, "scale")
        layout.prop(operator, "import_mesh")
        col = layout.column()
        col.prop(operator, "import_armature")
        row = col.row()
        row.enabled = operator.import_mesh and operator.import_armature
        row.prop(operator, "import_weights")


classes = (
    DZOB_OP_import_xob,
    DZOB_PT_import_xob_main
)


def menu_func_import(self, context):
    self.layout.operator(DZOB_OP_import_xob.bl_idname, text="DayZ model (.xob)")


if bpy.app.version >= (4, 1, 0):
    class DZOB_FH_import_xob(bpy.types.FileHandler):
        bl_idname = "DZOB_FH_import_xob"
        bl_label = "DayZ model (.xob)"
        bl_import_operator = "dzob.import_xob"
        bl_file_extensions = ".xob"

        @classmethod
        def poll_drop(cls, context):
            return context.area and context.area.type == 'VIEW_3D'

    classes = (*classes, DZOB_FH_import_xob)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    print("\t" + "UI: XOB Import / Export")


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("\t" + "UI: XOB Import / Export")
