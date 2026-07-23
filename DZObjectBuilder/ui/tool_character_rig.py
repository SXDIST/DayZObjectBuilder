import os

import bpy

from .. import addon_dir


RIG_BLEND = os.path.join(addon_dir, "data", "dayz_master_rig.blend")


class DZOB_OT_add_character_rig(bpy.types.Operator):
    """Add the bundled DayZ character master rig (armature, camera and gizmos) to the scene"""

    bl_idname = "dzob.add_character_rig"
    bl_label = "DayZ Character Rig"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return os.path.isfile(RIG_BLEND)

    def execute(self, context):
        if not os.path.isfile(RIG_BLEND):
            self.report({'ERROR'}, "Bundled rig not found: %s" % RIG_BLEND)
            return {'CANCELLED'}

        with bpy.data.libraries.load(RIG_BLEND, link=False) as (src, dst):
            dst.objects = list(src.objects)

        collection = context.collection or context.scene.collection
        armature = None
        linked = 0
        for obj in dst.objects:
            if obj is None:
                continue
            collection.objects.link(obj)
            linked += 1
            if obj.type == 'ARMATURE' and len(obj.data.bones) > 100:
                armature = obj

        if armature is not None:
            for obj in context.selected_objects:
                obj.select_set(False)
            armature.select_set(True)
            context.view_layer.objects.active = armature

        self.report({'INFO'}, "Added DayZ character rig (%d objects)" % linked)

        return {'FINISHED'}


def menu_func_add(self, context):
    self.layout.operator(DZOB_OT_add_character_rig.bl_idname, icon='ARMATURE_DATA')


def register():
    bpy.utils.register_class(DZOB_OT_add_character_rig)

    bpy.types.VIEW3D_MT_add.append(menu_func_add)

    print("\t" + "UI: Character Rig")


def unregister():
    bpy.types.VIEW3D_MT_add.remove(menu_func_add)

    bpy.utils.unregister_class(DZOB_OT_add_character_rig)

    print("\t" + "UI: Character Rig")
