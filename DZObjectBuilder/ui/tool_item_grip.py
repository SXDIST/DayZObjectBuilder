import math
import os

import bpy
import bpy_extras
from mathutils import Matrix, Vector

from .. import get_prefs
from ..utilities import actions as action_utils
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


AXIS_VECTORS = {
    'X': Vector((1.0, 0.0, 0.0)),
    'Y': Vector((0.0, 1.0, 0.0)),
    'Z': Vector((0.0, 0.0, 1.0)),
    '-X': Vector((-1.0, 0.0, 0.0)),
    '-Y': Vector((0.0, -1.0, 0.0)),
    '-Z': Vector((0.0, 0.0, -1.0)),
}

AXIS_ITEMS = (
    ('Z', "+Z", "Up in Blender, which is what a DayZ model's own up axis becomes on import"),
    ('Y', "+Y", ""),
    ('X', "+X", ""),
    ('-Z', "-Z", ""),
    ('-Y', "-Y", ""),
    ('-X', "-X", ""),
)


def find_grip_constraint(obj):
    for constraint in obj.constraints:
        if constraint.name == CONSTRAINT_NAME and constraint.type == 'CHILD_OF':
            return constraint

    for constraint in obj.constraints:
        if constraint.type == 'CHILD_OF' and constraint.target is not None and constraint.subtarget:
            return constraint

    return None


class DZOB_OT_item_grip_align_upright(bpy.types.Operator):
    """Rotate the grip bone until the held item stands upright

Works the correction out from the item in the scene and applies it to every keyframe of the bone as one constant offset, so the clip keeps its animation and only the item's seating in the hand changes"""

    bl_idname = "dzob.item_grip_align_upright"
    bl_label = "Align Item Upright"
    bl_options = {'REGISTER', 'UNDO'}

    axis: bpy.props.EnumProperty(
        name = "Item Axis",
        description = "Axis of the item that should end up pointing at world up",
        items = AXIS_ITEMS,
        default = 'Z'
    )

    @classmethod
    def poll(cls, context):
        obj = context.object

        return obj is not None and obj.type != 'ARMATURE' and find_grip_constraint(obj) is not None

    def execute(self, context):
        obj = context.object

        constraint = find_grip_constraint(obj)
        arm = constraint.target
        pose_bone = arm.pose.bones.get(constraint.subtarget)
        if pose_bone is None:
            self.report({'ERROR'}, "%s has no bone called %s" % (arm.name, constraint.subtarget))
            return {'CANCELLED'}

        if arm.animation_data is None or arm.animation_data.action is None:
            self.report({'ERROR'}, "%s has no action to write the correction into" % arm.name)
            return {'CANCELLED'}

        action = arm.animation_data.action
        scene = context.scene
        saved_frame = scene.frame_current

        if pose_bone.rotation_mode != 'QUATERNION':
            pose_bone.rotation_mode = 'QUATERNION'

        # The correction is read off the item as it stands right now, in world
        # space, and then expressed once in the bone's own parent relative frame.
        # Kept as a constant local offset it means the same thing on every frame:
        # the grip bone states where the item sits relative to the hand, and that
        # relation is what is being corrected, not the animation on top of it.
        context.view_layer.update()
        up_now = (obj.matrix_world.to_3x3() @ AXIS_VECTORS[self.axis]).normalized()
        applied = up_now.rotation_difference(Vector((0.0, 0.0, 1.0)))

        armature_basis = arm.matrix_world.to_3x3()
        correction = armature_basis.inverted() @ applied.to_matrix() @ armature_basis

        parent_basis = pose_bone.parent.matrix.to_3x3() if pose_bone.parent else Matrix.Identity(3)
        delta = parent_basis.inverted() @ correction @ parent_basis

        existing = action_utils.find_bone_fcurves(action, pose_bone.name, "rotation_quaternion")
        frames = action_utils.keyed_frames(existing)
        if not frames:
            frames = [saved_frame]

        fcurves = action_utils.ensure_bone_fcurves(action, arm, pose_bone.name, "rotation_quaternion", 4)

        for frame in frames:
            scene.frame_set(frame)

            parent = pose_bone.parent.matrix if pose_bone.parent else Matrix.Identity(4)
            local = parent.inverted() @ pose_bone.matrix
            rotated = Matrix.Translation(local.to_translation()) @ (delta @ local.to_3x3()).to_4x4()
            pose_bone.matrix = parent @ rotated

            quat = pose_bone.rotation_quaternion.copy()
            for index, fcurve in enumerate(fcurves):
                action_utils.set_key(fcurve, frame, quat[index])

        for fcurve in fcurves:
            fcurve.update()

        scene.frame_set(saved_frame)
        context.view_layer.update()

        residual = (obj.matrix_world.to_3x3() @ AXIS_VECTORS[self.axis]).normalized().angle(Vector((0.0, 0.0, 1.0)))

        self.report(
            {'INFO'},
            "Rotated %s by %.2f deg on %d keyframe(s), item now %.2f deg off vertical"
            % (pose_bone.name, math.degrees(applied.angle), len(frames), math.degrees(residual))
        )

        return {'FINISHED'}


class DZOB_OT_item_grip_solve_report(bpy.types.Operator):
    """Solve the grip bone from an in-game probe log and check it on every sample

A bone that stands the item upright in one hand pose can be 60 to 90 degrees out in another, and that is true of vanilla items too, so the answer is only meaningful as a table across several measured frames and never as a single number from the pose that happened to be on screen"""

    bl_idname = "dzob.item_grip_solve_report"
    bl_label = "Solve From Probe Log"
    bl_options = {'REGISTER'}

    TEXT_NAME = "DZOB Grip Solution"

    log: bpy.props.StringProperty(
        name = "Probe Log",
        description = ("Paste the probe output. Label each line with 'item' or 'hand' and give "
                       "either one row (3 numbers) or a whole transform (9, or 12 with the "
                       "position); a line labelled 'grip' overrides the stored grip matrix"),
        default = ""
    )

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=600)

    def execute(self, context):
        try:
            samples, override = grip.parse_probe_samples(self.log)
        except ValueError as ex:
            self.report({'ERROR'}, "Could not read the probe log: %s" % ex)
            return {'CANCELLED'}

        grip_matrix = override if override is not None else grip.dayz_col_from_rows(
            grip.rows_from_flat(get_prefs().grip_matrix))

        measured = [grip.bone_from_sample(sample["item"], sample["hand"], grip_matrix) for sample in samples]
        solved = [grip.upright_bone_from_sample(sample["item"], sample["hand"], grip_matrix) for sample in samples]

        lines = []
        lines.append("Grip bone solved from %d sample(s)%s."
                     % (len(samples), " (grip matrix taken from the log)" if override is not None else ""))
        lines.append("")
        lines.append("Everything below is in DayZ engine space, the convention the probe printed.")
        lines.append("It is deliberately not converted into an .anm bone channel: a clip stores")
        lines.append("bones in DayZ Tools' convention rather than the engine's, and crossing")
        lines.append("between the two is the one step no measurement here can check. To put a")
        lines.append("solution into a clip, pose the scene and export with this add-on, which")
        lines.append("round trips that convention exactly.")
        lines.append("")

        # The bone is one constant value, so the same bone read out of different
        # frames has to agree. It not agreeing means a sample is off, and the
        # usual cause is a frame where the item's transform lagged the bone.
        spread = 0.0
        for first in measured:
            for second in measured:
                spread = max(spread, (first.to_3x3().inverted() @ second.to_3x3()).to_quaternion().angle)

        lines.append("Measured bone agreement across samples: %.4f deg" % math.degrees(spread))
        if math.degrees(spread) > 1.0:
            lines.append("  The samples disagree about the bone, so item = E * D * hand does not")
            lines.append("  hold on all of them. Drop the odd frame before trusting the solution.")
        lines.append("")

        lines.append("Item tilt from vertical, in degrees. Rows are candidate bone values,")
        lines.append("columns are the measured samples.")
        lines.append("")

        header = "%-22s" % "candidate" + "".join("%10s" % ("n=%d" % (index + 1)) for index in range(len(samples)))
        lines.append(header)
        lines.append("-" * len(header))

        def row(label, candidate):
            tilts = [grip.tilt_degrees(grip.compose_item(sample["hand"], candidate, grip_matrix)) for sample in samples]
            lines.append("%-22s" % label + "".join("%10.2f" % tilt for tilt in tilts))

            return tilts

        row("measured (as built)", measured[0])

        best_label, best_mean = None, None
        for index, candidate in enumerate(solved):
            tilts = row("solved from n=%d" % (index + 1), candidate)
            mean = sum(tilts) / len(tilts)
            if best_mean is None or mean < best_mean:
                best_label, best_mean = "n=%d" % (index + 1), mean

        lines.append("")
        lines.append("Solved bone values, DayZ rows (right, up, forward, position):")
        for index, candidate in enumerate(solved):
            lines.append("  n=%d" % (index + 1))
            for name, values in zip(("right", "up", "forward", "position"), grip.rows_from_dayz_col(candidate)):
                lines.append("    %-9s %12.6f %12.6f %12.6f" % (name, values[0], values[1], values[2]))

        report = "\n".join(lines)

        text = bpy.data.texts.get(self.TEXT_NAME)
        if text is None:
            text = bpy.data.texts.new(self.TEXT_NAME)

        text.clear()
        text.write(report)

        print(report)

        self.report(
            {'INFO'},
            "Solved on %d sample(s), best average tilt from %s (%.2f deg), see the text block %s"
            % (len(samples), best_label, best_mean, self.TEXT_NAME)
        )

        return {'FINISHED'}


class DZOB_OT_item_grip_copy_bone_channel(bpy.types.Operator, bpy_extras.io_utils.ImportHelper):
    """Copy one bone's channel out of an .anm into the current action

Raw numbers from an .anm cannot be written into a pose bone: a pose is measured against the rest pose, and a direct substitution throws the item most of a metre out of place. This imports the clip through the add-on's own reader and lifts the channel out of the result"""

    bl_idname = "dzob.item_grip_copy_bone_channel"
    bl_label = "Copy Bone Channel"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".anm"

    filter_glob: bpy.props.StringProperty(
        default = "*.anm",
        options = {'HIDDEN'}
    )
    bones: bpy.props.StringProperty(
        name = "Bones",
        description = "Comma separated bone names to lift out of the clip",
        default = grip.GRIP_BONE
    )
    scale: bpy.props.FloatProperty(
        name = "Scale",
        description = "Scale factor applied to keyframe translations",
        default = 1.0,
        min = 0.0001,
        soft_max = 100.0
    )

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'ARMATURE'

    def execute(self, context):
        arm = context.object

        if arm.animation_data is None or arm.animation_data.action is None:
            self.report({'ERROR'}, "%s has no action to copy the channel into" % arm.name)
            return {'CANCELLED'}

        wanted = [name.strip() for name in self.bones.split(",") if name.strip()]
        if not wanted:
            self.report({'ERROR'}, "No bone names given")
            return {'CANCELLED'}

        target = arm.animation_data.action
        tracks_before = len(arm.animation_data.nla_tracks)

        # The import operator replaces the action and pushes the old one onto an
        # NLA track. Both are undone further down, once the channels are out.
        try:
            bpy.ops.dzob.import_anm(filepath=self.filepath, scale=self.scale, gear_ik_filepath="")
        except RuntimeError as ex:
            self.report({'ERROR'}, "Could not import %s: %s" % (os.path.basename(self.filepath), ex))
            return {'CANCELLED'}

        source = arm.animation_data.action
        if source is target:
            self.report({'ERROR'}, "The import did not produce a separate action to copy from")
            return {'CANCELLED'}

        harvested = {}
        for name in wanted:
            resolved = next((bone.name for bone in arm.pose.bones if bone.name.lower() == name.lower()), name)
            for prop in ("rotation_quaternion", "location"):
                curves = action_utils.find_bone_fcurves(source, resolved, prop)
                if not curves:
                    continue

                harvested[(resolved, prop)] = [
                    (fcurve.array_index, [(point.co[0], point.co[1]) for point in fcurve.keyframe_points])
                    for fcurve in curves
                ]

        arm.animation_data.action = target
        bpy.data.actions.remove(source)

        for track in list(arm.animation_data.nla_tracks)[tracks_before:]:
            arm.animation_data.nla_tracks.remove(track)

        if not harvested:
            self.report({'WARNING'}, "%s holds no channel for %s" % (os.path.basename(self.filepath), self.bones))
            return {'FINISHED'}

        copied = set()
        for (bone_name, prop), curves in harvested.items():
            action_utils.remove_bone_fcurves(target, bone_name, prop)
            count = 4 if prop == "rotation_quaternion" else 3
            destination = action_utils.ensure_bone_fcurves(target, arm, bone_name, prop, count)

            for array_index, points in curves:
                fcurve = destination[array_index]
                for frame, value in points:
                    action_utils.set_key(fcurve, frame, value)

                fcurve.update()

            copied.add(bone_name)

        context.view_layer.update()

        self.report(
            {'INFO'},
            "Copied %d channel(s) for %s from %s into %s"
            % (len(harvested), ", ".join(sorted(copied)), os.path.basename(self.filepath), target.name)
        )

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

        col_scene = layout.column(align=True)
        col_scene.operator("dzob.item_grip_attach", icon='CONSTRAINT_BONE')
        col_scene.operator("dzob.item_grip_align_upright", icon='ORIENTATION_NORMAL')

        col_clip = layout.column(align=True)
        col_clip.operator("dzob.item_grip_copy_bone_channel", icon='ANIM_DATA')
        col_clip.operator("dzob.item_grip_solve_report", icon='CON_TRACKTO')

        col_note = layout.column(align=True)
        col_note.label(text="Uses the measured grip matrix")
        col_note.label(text="from the add-on preferences.")


classes = (
    DZOB_OT_item_grip_attach,
    DZOB_OT_item_grip_align_upright,
    DZOB_OT_item_grip_solve_report,
    DZOB_OT_item_grip_copy_bone_channel,
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
