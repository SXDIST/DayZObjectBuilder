# Export a Blender armature's animation to a DayZ (Enfusion) .anm file.
#
# Exact inverse of import_anm: for every frame the pose bone's (object-space)
# matrix is converted back into DayZ bone space through the same MTX_FIX
# change-of-basis, then stored as a quaternion (x, z, y, -w) and a translation
# (x, z, y). data_anm.ANM_Anim.write handles the container and quantisation.


from . import data_anm
from .import_anm import MTX_FIX
from ..utilities.logger import ProcessLogger


_MTX_FIX_INV = MTX_FIX.inverted()


def _stored_quat(mat):
    # DayZ-space rotation matrix -> stored (x, z, y, -w); inverse of the
    # import swizzle Quaternion((-w, x, z, y)).
    q = mat.to_quaternion()
    return (q.x, q.z, q.y, -q.w)


def _stored_vec(vec):
    # inverse of the import swizzle Vector((x, z, y))
    return (vec.x, vec.z, vec.y)


def _collect_events(arm):
    events = []
    ad = arm.animation_data
    if ad is None or ad.action is None:
        return events

    for marker in ad.action.pose_markers:
        name, user_string, user_int = marker.name, "", 0
        parts = marker.name.split("|")
        if len(parts) >= 3:
            name = parts[0]
            user_string = parts[1]
            try:
                user_int = int(parts[2])
            except ValueError:
                user_int = 0
        events.append((int(marker.frame), name, user_string, user_int))

    return events


def export_file(operator, context):
    arm = context.object
    scene = context.scene

    logger = ProcessLogger()
    logger.start_subproc("ANM export to %s" % operator.filepath)

    if operator.use_scene_range:
        f0, f1 = scene.frame_start, scene.frame_end
    else:
        f0, f1 = operator.frame_start, operator.frame_end
    if f1 < f0:
        f0, f1 = f1, f0

    pbones = list(arm.pose.bones)
    bones = {pb.name: data_anm.ANM_Bone(pb.name) for pb in pbones}

    saved = scene.frame_current
    for frame in range(f0, f1 + 1):
        scene.frame_set(frame)
        idx = frame - f0
        for pb in pbones:
            bone = bones[pb.name]
            if pb.parent is None:
                rot_mat = pb.matrix @ _MTX_FIX_INV
                trans_mat = pb.matrix @ MTX_FIX
            else:
                # non-root rotation and translation share the same matrix
                rot_mat = MTX_FIX @ pb.parent.matrix.inverted() @ pb.matrix @ _MTX_FIX_INV
                trans_mat = rot_mat

            if operator.export_rotation:
                bone.rotations[idx] = _stored_quat(rot_mat)
            if operator.export_translation:
                bone.translations[idx] = _stored_vec(trans_mat.to_translation())

    scene.frame_set(saved)

    anim = data_anm.ANM_Anim()
    anim.fps = scene.render.fps
    anim.frame_count = f1 - f0 + 1
    anim.bones = [bones[pb.name] for pb in pbones]
    anim.events = _collect_events(arm)

    anim.write_file(operator.filepath, v6=(operator.version == 'V6'))

    logger.step("Bones: %d, Frames: %d, FPS: %d" % (len(anim.bones), anim.frame_count, anim.fps))
    logger.end_subproc()
    logger.step("ANM export finished")

    return len(anim.bones), anim.frame_count
