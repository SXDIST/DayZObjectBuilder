import bpy
from mathutils import Matrix

from .. import get_prefs
from ..utilities import grip


# Every Child Of this operator writes carries this name, so a second run replaces
# its own constraint instead of stacking another one on top.
CONSTRAINT_NAME = "DZOB Item Grip"


def matrix_basis_from_prefs():
    return grip.matrix_basis_from_rows(grip.rows_from_flat(get_prefs().grip_matrix))


def find_bone(arm, name):
    bone = arm.data.bones.get(name)
    if bone is not None:
        return bone

    lowered = name.lower()
    for candidate in arm.data.bones:
        if candidate.name.lower() == lowered:
            return candidate

    return None


# The armature is worked out rather than asked for: the active object has to stay
# the item, so there is no second slot to select one in. Preference goes to an
# armature the user actually selected, then to the only one in the scene that has
# the grip bone at all - which rules out the master rig's FPS camera armature
# without having to know its name.
def find_armature(context, bone_name):
    selected = [obj for obj in context.selected_objects if obj.type == 'ARMATURE']
    if context.object is not None and context.object.type == 'ARMATURE':
        selected.insert(0, context.object)

    for obj in selected:
        if find_bone(obj, bone_name) is not None:
            return obj, None

    candidates = [obj for obj in context.scene.objects if obj.type == 'ARMATURE' and find_bone(obj, bone_name) is not None]
    if len(candidates) == 1:
        return candidates[0], None

    if len(candidates) == 0:
        return None, "No armature in the scene has a %s bone" % bone_name

    return None, "%d armatures have a %s bone, select the one to attach to" % (len(candidates), bone_name)


class DZOB_OT_item_grip_attach(bpy.types.Operator):
    """Place the active object into the character's hand the way the engine does
    
Hangs the object off the grip bone with the measured engine grip matrix, so the viewport shows the same placement the game draws"""

    bl_idname = "dzob.item_grip_attach"
    bl_label = "Attach To Hand"
    bl_options = {'REGISTER', 'UNDO'}

    bone: bpy.props.StringProperty(
        name = "Grip Bone",
        description = "Bone the engine hangs the held item off",
        default = grip.GRIP_BONE
    )
    keep_scale: bpy.props.BoolProperty(
        name = "Keep Scale",
        description = "Preserve the object's current scale instead of resetting it to 1",
        default = True
    )

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type != 'ARMATURE'

    def execute(self, context):
        obj = context.object

        arm, error = find_armature(context, self.bone)
        if arm is None:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        bone = find_bone(arm, self.bone)
        notes = []

        # The dummy is a child of RightHand in the DayZ rig, and the engine's
        # matrix is expressed against the dummy alone. A dummy sitting somewhere
        # else in the hierarchy still produces a preview, just not the game's one.
        if bone.parent is None or bone.parent.name.lower() != grip.GRIP_PARENT_BONE.lower():
            notes.append("%s is not a child of %s" % (bone.name, grip.GRIP_PARENT_BONE))

        # Child Of runs on the object's matrix after parenting, so a leftover
        # parent would quietly compose itself into the result.
        if obj.parent is not None:
            obj.parent = None
            notes.append("cleared the object's parent")

        for constraint in [item for item in obj.constraints if item.name == CONSTRAINT_NAME]:
            obj.constraints.remove(constraint)

        leftover = len([item for item in obj.constraints if item.type == 'CHILD_OF'])
        if leftover:
            notes.append("%d other Child Of constraint(s) left in place" % leftover)

        constraint = obj.constraints.new('CHILD_OF')
        constraint.name = CONSTRAINT_NAME
        constraint.target = arm
        constraint.subtarget = bone.name
        # The whole offset lives in matrix_basis below. An inverse matrix baked by
        # Blender's own Set Inverse would fold the bone's current pose into the
        # result and pin the item to whatever frame happened to be current.
        constraint.inverse_matrix = Matrix.Identity(4)

        basis = matrix_basis_from_prefs()
        if self.keep_scale:
            basis = basis @ Matrix.Diagonal(obj.scale.to_4d())

        obj.matrix_basis = basis

        context.view_layer.update()

        message = "Attached %s to %s of %s" % (obj.name, bone.name, arm.name)
        if notes:
            self.report({'WARNING'}, "%s (%s)" % (message, "; ".join(notes)))
        else:
            self.report({'INFO'}, message)

        return {'FINISHED'}


class DZOB_PT_item_grip(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Object Builder"
    bl_label = "Item Grip"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout

        layout.operator("dzob.item_grip_attach", icon='CONSTRAINT_BONE')

        col = layout.column(align=True)
        col.label(text="Uses the measured grip matrix")
        col.label(text="from the add-on preferences.")


classes = (
    DZOB_OT_item_grip_attach,
    DZOB_PT_item_grip
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    print("\t" + "UI: Item Grip")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("\t" + "UI: Item Grip")
