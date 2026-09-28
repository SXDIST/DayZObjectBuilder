import os
import re

import bpy

from .. import addon_dir


RIG_BLEND = os.path.join(addon_dir, "data", "dayz_master_rig.blend")

COLLECTION_ROOT = "DayZ_Character_Rig"
COLLECTION_HELPERS = "DayZ_Character_Rig_Helpers"
COLLECTION_FPS_CAMERA = "DayZ_Character_Rig_FPS_Camera"

# The bone shape gizmos of the master rig all carry this prefix.
HELPER_PREFIX = "zJD_"

# Objects of the root collection that are only there to be exported or referenced, and
# would just be in the way in the viewport. Everything else the rig brings along (the
# character armature and the body mesh) is left visible.
HIDDEN_OBJECTS = ("zEntityPosition", "zzzCamera")


# Split the objects of the master rig into the three groups they are laid out in:
# the character armature and its companions stay in the root collection, the bone
# shape gizmos and the FPS camera armature go into their own subcollections.
# The character armature is picked as the armature with the most bones, so the far
# smaller FPS camera armature can never be mistaken for it.
def sort_rig_objects(objects):
    armatures = [obj for obj in objects if obj.type == 'ARMATURE']
    character = max(armatures, key=lambda obj: len(obj.data.bones), default=None)

    root, helpers, fps_camera = [], [], []
    for obj in objects:
        if obj.name.startswith(HELPER_PREFIX):
            helpers.append(obj)
        elif obj.type == 'ARMATURE' and obj is not character:
            fps_camera.append(obj)
        else:
            root.append(obj)

    return character, root, helpers, fps_camera


# Appending the rig a second time makes Blender suffix the colliding object names with
# ".001", which the name based lookups have to see through.
def base_name(name):
    return re.sub(r"\.\d{3}$", "", name)


def find_layer_collection(layer_collection, collection):
    if layer_collection.collection is collection:
        return layer_collection

    for child in layer_collection.children:
        found = find_layer_collection(child, collection)
        if found is not None:
            return found

    return None


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

        objects = [obj for obj in dst.objects if obj is not None]
        if not objects:
            self.report({'ERROR'}, "Bundled rig contains no objects: %s" % RIG_BLEND)
            return {'CANCELLED'}

        parent = context.collection or context.scene.collection

        collection_root = bpy.data.collections.new(COLLECTION_ROOT)
        parent.children.link(collection_root)

        collection_helpers = bpy.data.collections.new(COLLECTION_HELPERS)
        collection_root.children.link(collection_helpers)

        collection_fps_camera = bpy.data.collections.new(COLLECTION_FPS_CAMERA)
        collection_root.children.link(collection_fps_camera)

        character, objects_root, objects_helpers, objects_fps_camera = sort_rig_objects(objects)

        for obj in objects_root:
            collection_root.objects.link(obj)

        for obj in objects_helpers:
            collection_helpers.objects.link(obj)

        for obj in objects_fps_camera:
            collection_fps_camera.objects.link(obj)

        # The entity position marker and the scene camera are kept around but hidden. The
        # gizmos and the FPS camera are taken out of the view layer entirely further below.
        for obj in objects_root:
            if base_name(obj.name) in HIDDEN_OBJECTS:
                obj.hide_set(True)

        for obj in context.selected_objects:
            obj.select_set(False)

        if character is not None:
            character.select_set(True)
            context.view_layer.objects.active = character

        # Has to happen after the objects were linked, hidden and selected: an excluded
        # collection is not part of the view layer, so its objects can no longer be
        # addressed through it.
        for collection in (collection_helpers, collection_fps_camera):
            layer_collection = find_layer_collection(context.view_layer.layer_collection, collection)
            if layer_collection is not None:
                layer_collection.exclude = True

        self.report({'INFO'}, "Added DayZ character rig (%d objects)" % len(objects))

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
