import traceback

import bpy
import bpy_extras

from ..io import import_paa
from ..utilities import generic as utils


class DZOB_OP_import_paa(bpy.types.Operator,  bpy_extras.io_utils.ImportHelper):
    """Import PAA"""

    bl_idname = "dzob.import_paa"
    bl_label = "Import Texture"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}
    filename_ext = ".paa"
    
    filter_glob: bpy.props.StringProperty(
        default = "*.paa",
        options = {'HIDDEN'}
    )
    color_space: bpy.props.EnumProperty(
        name = "Mode",
        description = "How to interpret the color data in the imported texture",
        items = (
            ('SRGB', "sRGB", "File contains a color texture (CO, CA, MC, etc.)"),
            ('DATA', "Data", "File contains non-color data (NOHQ, SMDI, AS, etc.)")
        ),
        default='SRGB'
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "color_space", expand=True)
    
    def execute(self, context):
        try:
            with utils.open_long(self.filepath, "rb") as file:
                img, tex = import_paa.import_file(self, context, file)
        except Exception as ex:
            traceback.print_exc()
            utils.op_report(self, {'ERROR'}, "Import failed: %s (check the logs in the system console)" % ex)
            return {'CANCELLED'}

        if img is not None:
            utils.op_report(self, {'INFO'}, "Texture successfully imported as %s" % img.name)
        else:
            utils.op_report(self, {'WARNING'}, "Unsupported texture format: %s" % tex.type.name)

        return {'FINISHED'}


classes = (
    DZOB_OP_import_paa,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
        
    print("\t" + "UI: PAA Import / Export")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        
    print("\t" + "UI: PAA Import / Export")
