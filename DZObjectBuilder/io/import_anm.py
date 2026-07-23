# Apply a parsed DayZ .anm animation onto a selected Blender armature.
#
# The keyframe application mirrors the approach used by the DayzAnimationTools
# add-on (its ImportTxa), which is calibrated against the vanilla DayZ master
# rig: every bone transform is expressed relative to its parent through the
# fixed change-of-basis matrix below. The .anm stores no hierarchy, so the
# armature's own bone hierarchy drives the parent/child order.


import os

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import data_anm
from ..utilities.logger import ProcessLogger


# DayZ bone space <-> Blender bone space (90 degrees about Z).
MTX_FIX = Matrix(((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))


def _to_blender_quat(q):
    # .anm stores DayZ (x, y, z, w); DayZ Tools writes it from Blender as
    # (x, z, y, -w), so the inverse swizzle brings it back.
    return Quaternion((-q[3], q[0], q[2], q[1]))


def _to_blender_vec(t):
    # translation is stored with Y and Z swapped
    return Vector((t[0], t[2], t[1]))


def _fcurves(action, arm_obj, bone_name, prop, count):
    return [
        action.fcurve_ensure_for_datablock(
            arm_obj, 'pose.bones["%s"].%s' % (bone_name, prop),
            index=i, group_name=bone_name)
        for i in range(count)
    ]


def import_file(operator, context):
    arm = context.object

    logger = ProcessLogger()
    logger.start_subproc("ANM import from %s" % operator.filepath)

    anim = data_anm.ANM_Anim.read_file(operator.filepath, scale=operator.scale)
    logger.step("Bones: %d, Frames: %d, FPS: %d" % (len(anim.bones), anim.frame_count, anim.fps))

    if arm.animation_data is None:
        arm.animation_data_create()

    bpy.ops.object.mode_set(mode='POSE')
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    # keep any existing action as an NLA strip
    if arm.animation_data.action is not None:
        old = arm.animation_data.action
        track = arm.animation_data.nla_tracks.new()
        track.strips.new(old.name, int(old.frame_range[0]), old)

    name = os.path.splitext(os.path.basename(operator.filepath))[0]
    action = bpy.data.actions.new(name)
    arm.animation_data.action = action
    action.use_fake_user = True

    scene = context.scene
    scene.render.fps = anim.fps
    scene.frame_start = 0
    scene.frame_end = max(0, anim.frame_count - 1)

    blbones = {pb.name.lower(): pb for pb in arm.pose.bones}

    # match .anm bones to pose bones and order them parents first
    matched = []
    for abone in anim.bones:
        pb = blbones.get(abone.name.lower())
        if pb is not None:
            matched.append((abone, pb))
    matched.sort(key=lambda pair: len(pair[1].parent_recursive))

    missing = len(anim.bones) - len(matched)
    if missing:
        logger.step("%d animated bone(s) not found in the armature (skipped)" % missing)

    for abone, pb in matched:
        rot_keys = {f: _to_blender_quat(q) for f, q in abone.rotations.items()} if operator.import_rotation else {}
        trans_keys = {f: _to_blender_vec(t) for f, t in abone.translations.items()} if operator.import_translation else {}

        q_fcurves = _fcurves(action, arm, pb.name, 'rotation_quaternion', 4) if rot_keys else None
        t_fcurves = _fcurves(action, arm, pb.name, 'location', 3) if trans_keys else None
        if q_fcurves:
            for fc in q_fcurves:
                fc.keyframe_points.add(len(rot_keys))
        if t_fcurves:
            for fc in t_fcurves:
                fc.keyframe_points.add(len(trans_keys))

        rframes = sorted(rot_keys)
        tframes = sorted(trans_keys)

        for k, frame in enumerate(rframes):
            rot = rot_keys[frame].to_matrix().to_4x4()
            if pb.parent is None:
                pb.matrix = rot @ MTX_FIX
            else:
                pb.matrix = pb.parent.matrix @ MTX_FIX.inverted() @ rot @ MTX_FIX
            quat = pb.rotation_quaternion
            for axis, fc in enumerate(q_fcurves):
                fc.keyframe_points[k].co = (frame, quat[axis])
                fc.keyframe_points[k].interpolation = 'LINEAR'

        for k, frame in enumerate(tframes):
            trans = trans_keys[frame]
            if pb.parent is None:
                pb.matrix = Matrix.Translation(trans) @ MTX_FIX.inverted()
            else:
                pb.matrix = pb.parent.matrix @ MTX_FIX.inverted() @ Matrix.Translation(trans) @ MTX_FIX
            for axis, fc in enumerate(t_fcurves):
                fc.keyframe_points[k].co = (frame, pb.location[axis])
                fc.keyframe_points[k].interpolation = 'LINEAR'

        if q_fcurves:
            for fc in q_fcurves:
                fc.update()
        if t_fcurves:
            for fc in t_fcurves:
                fc.update()

        pb.matrix_basis.identity()

    for frame, ename, user_string, user_int in anim.events:
        marker = action.pose_markers.new("%s|%s|%d" % (ename, user_string, user_int))
        marker.frame = frame

    context.evaluated_depsgraph_get().update()

    logger.end_subproc()
    logger.step("ANM import finished")

    return len(matched), anim.frame_count
