import bpy


# All DayZ Object Builder import/export entries are grouped under a single
# "DayZ" submenu in File > Import and File > Export instead of being scattered
# as flat entries. Each tuple is (operator bl_idname, menu text, icon).

IMPORT_ENTRIES = (
    ("dzob.import_p3d",      "DayZ model (.p3d)",              'MESH_DATA'),
    ("dzob.import_xob",      "DayZ model (.xob)",              'MESH_DATA'),
    ("dzob.import_anm",      "DayZ animation (.anm)",          'ACTION'),
    ("dzob.import_mcfg",     "DayZ skeletons (model.cfg)",     'ARMATURE_DATA'),
    ("dzob.import_armature", "DayZ armature (.p3d)",           'OUTLINER_OB_ARMATURE'),
    ("dzob.import_tbcsv",    "Terrain Builder objects (.txt)", 'FILE_TEXT'),
    ("dzob.import_asc",      "Esri Grid ASCII (.asc)",         'MESH_GRID'),
    ("dzob.import_paa",      "DayZ texture (.paa)",            'TEXTURE'),
)

EXPORT_ENTRIES = (
    ("dzob.export_p3d",   "DayZ model (.p3d)",              'MESH_DATA'),
    ("dzob.export_mcfg",  "DayZ skeleton (model.cfg)",      'ARMATURE_DATA'),
    ("dzob.export_tbcsv", "Terrain Builder objects (.txt)", 'FILE_TEXT'),
    ("dzob.export_asc",   "Esri Grid ASCII (.asc)",         'MESH_GRID'),
)


class DZOB_MT_file_import(bpy.types.Menu):
    bl_idname = "DZOB_MT_file_import"
    bl_label = "DayZ"

    def draw(self, context):
        layout = self.layout
        for idname, text, icon in IMPORT_ENTRIES:
            layout.operator(idname, text=text, icon=icon)


class DZOB_MT_file_export(bpy.types.Menu):
    bl_idname = "DZOB_MT_file_export"
    bl_label = "DayZ"

    def draw(self, context):
        layout = self.layout
        for idname, text, icon in EXPORT_ENTRIES:
            layout.operator(idname, text=text, icon=icon)


classes = (
    DZOB_MT_file_import,
    DZOB_MT_file_export,
)


def menu_func_import(self, context):
    self.layout.menu(DZOB_MT_file_import.bl_idname, text="DayZ", icon='IMPORT')


def menu_func_export(self, context):
    self.layout.menu(DZOB_MT_file_export.bl_idname, text="DayZ", icon='EXPORT')


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

    print("\t" + "UI: DayZ Import / Export menu")


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("\t" + "UI: DayZ Import / Export menu")
