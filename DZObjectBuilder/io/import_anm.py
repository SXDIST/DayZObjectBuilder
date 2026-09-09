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

# ANIMSET6 exporters bake a full absolute pose into every bone regardless of
# the per-bone additive flag (confirmed against multiple vanilla ANIMSET6
# clips - the flag is present but the data is already absolute). Only legacy
# ANIMSET5 clips carry genuine deltas that need reconstructing against a
# reference frame; ANIMSET6 additive bones are left exactly as decoded.
#
# Within an ANIMSET5 clip, the arm/shoulder/hand chain is a different case
# again: its rest pose (T-pose) is far from any usable "diff pose frame", so
# these bones carry a large constant absolute offset (bringing the arm down
# from T-pose) with a small amount of genuine sway layered on top. Subtracting
# a reference frame from that combination erases the constant offset and
# leaves the arm floating at rest. Bones in this chain keep their decoded
# value untouched, same as ANIMSET6; only the remaining ANIMSET5 additive
# bones (legs, spine, neck/head, hip/knee correctives) get the diff-pose-frame
# correction, since those hold a genuine delta-from-rest with no comparable
# constant offset to protect.
ADDITIVE_ABSOLUTE_CHAIN_PREFIXES = (
    'LeftArm', 'RightArm', 'LeftForeArm', 'RightForeArm', 'LeftShoulder', 'RightShoulder',
    'LeftHand', 'RightHand', 'LeftElbow', 'RightElbow', 'LeftWrist', 'RightWrist',
)


def _is_arm_chain_bone(name):
    return name.startswith(ADDITIVE_ABSOLUTE_CHAIN_PREFIXES)


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


def _overlay_gear_ik(operator, context, arm, action, anim, logger):
    # In game a held item's pose comes from two files, not one: the locomotion
    # clip carries the body, and the item's gear IK clip
    # (dz/anims/anm/player/ik/gear/<item>.anm) carries the hand that grips it.
    # Measured on 1.29: p_1hd_erc_idle_low holds 65 bones with zero RightHand
    # finger channels, while brassknuckles.anm holds 21 bones that are nothing
    # but the right hand. Import the clip alone and the grip hand is open -
    # correct for the file, wrong against what the game draws. Overlaying the
    # gear clip here makes the viewport match the engine.
    path = getattr(operator, "gear_ik_filepath", "")
    if not path:
        return
    if not os.path.isfile(path):
        logger.step("gear IK not found, skipped: %s" % path)
        return

    gear = data_anm.ANM_Anim.read_file(path, scale=operator.scale)
    blbones = {pb.name.lower(): pb for pb in arm.pose.bones}

    # Order parents first, same as the main import: each bone's placement is
    # composed against its parent's already-posed matrix.
    matched = []
    for gbone in gear.bones:
        pb = blbones.get(gbone.name.lower())
        if pb is not None:
            matched.append((gbone, pb))
    matched.sort(key=lambda pair: len(pair[1].parent_recursive))

    def _hold(prop, count, values):
        # The grip pose is constant, so one key per channel is enough.
        fcurves = _fcurves(action, arm, pb.name, prop, count)
        for axis, fc in enumerate(fcurves):
            if len(fc.keyframe_points) == 0:
                fc.keyframe_points.add(1)
            for kp in fc.keyframe_points:
                kp.co = (0.0, values[axis])
                kp.interpolation = 'LINEAR'
            fc.update()

    applied = 0
    for gbone, pb in matched:
        touched = False

        if gbone.rotations:
            first = sorted(gbone.rotations)[0]
            rot = _to_blender_quat(gbone.rotations[first]).to_matrix().to_4x4()
            if pb.parent is None:
                pb.matrix = rot @ MTX_FIX
            else:
                pb.matrix = pb.parent.matrix @ MTX_FIX.inverted() @ rot @ MTX_FIX
            _hold('rotation_quaternion', 4, pb.rotation_quaternion.copy())
            touched = True

        # The attachment bone carries a translation too, and without it the
        # bone stays at its bind position - for RightHand_Dummy that is up by
        # the chest, nowhere near the grip, so the item has nothing usable to
        # hang off. Measured: apple.anm moves it by (-0.085, 0.032, 0.066),
        # brassknuckles.anm by (-0.058, 0.009, 0.029).
        if gbone.translations:
            firstt = sorted(gbone.translations)[0]
            trans = _to_blender_vec(gbone.translations[firstt])
            if pb.parent is None:
                pb.matrix = Matrix.Translation(trans) @ MTX_FIX.inverted()
            else:
                pb.matrix = pb.parent.matrix @ MTX_FIX.inverted() @ Matrix.Translation(trans) @ MTX_FIX
            _hold('location', 3, pb.location.copy())
            touched = True

        # Reset before moving on, exactly as the main loop does. The keys are
        # already written, and the next bone composes against its parent's REST
        # matrix - leaving this one posed would fold the parent's rotation into
        # its children a second time.
        pb.matrix_basis.identity()

        if touched:
            applied += 1

    missing = len(gear.bones) - len(matched)
    note = ""
    if missing:
        note = " (%d gear bone(s) absent from the armature)" % missing
    logger.step("gear IK overlay: %d bone(s) from %s%s"
                % (applied, os.path.basename(path), note))


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
        pb.matrix_basis.identity()

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

        # First pass: resolve every rotation keyframe to its Blender-local
        # quaternion via the normal parent-chain composition, without any
        # additive correction yet.
        quats = []
        for frame in rframes:
            rot = rot_keys[frame].to_matrix().to_4x4()
            if pb.parent is None:
                pb.matrix = rot @ MTX_FIX
            else:
                pb.matrix = pb.parent.matrix @ MTX_FIX.inverted() @ rot @ MTX_FIX
            quats.append(pb.rotation_quaternion.copy())

        # Additive bones store their rotation as a delta against a "diff pose
        # frame" (Enfusion's Animation Export Profile term) rather than an
        # absolute pose. The .anm format carries no reference pose of its own,
        # so the bone's own first keyframe stands in for that diff-pose frame.
        # See the constants above for which bones/formats this applies to.
        if abone.additive and quats and not anim.is_v6 and not _is_arm_chain_bone(abone.name):
            ref = quats[0]
            quats = [ref.inverted() @ q for q in quats]

        for k, quat in enumerate(quats):
            for axis, fc in enumerate(q_fcurves):
                fc.keyframe_points[k].co = (rframes[k], quat[axis])
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

    _overlay_gear_ik(operator, context, arm, action, anim, logger)

    for frame, ename, user_string, user_int in anim.events:
        marker = action.pose_markers.new("%s|%s|%d" % (ename, user_string, user_int))
        marker.frame = frame

    context.evaluated_depsgraph_get().update()

    logger.end_subproc()
    logger.step("ANM import finished")

    return len(matched), anim.frame_count
