"""
python tests/grip.py

Pins the axis convention of the item grip matrix against the game itself.

DayZ draws a held item at `RightHand_Dummy * E`, and E is measured in a running
game rather than derived - deriving it means guessing an axis convention and a
transposition at the same time, and neither guess announces itself: a wrong grip
matrix produces a preview that looks entirely plausible, and any check built on
top of it agrees with it. That is what this test exists to break.

It also covers the tools built on that matrix: the engine space solver, aligning
a held item upright, and lifting a bone channel back out of a vanilla clip.

It is an end to end regression, so it needs Blender and the mounted project drive.
The reference number comes from the game, not from this add-on: with the vanilla
water bottle held in the vanilla `p_1hd_erc_idle_low` stance, an in-game probe put
the bottle 14.2 degrees off vertical. Every wrong conversion that was tried lands
far outside the tolerance below - the mirrored y/z swap the .anm reader uses
internally gives 165 degrees, and folding in the bone space fix gives 76 to 104.

Skipped, not failed, when Blender or the project drive is missing.
"""


import glob
import json
import math
import os
import shutil
import string
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MOVE_CLIP = os.path.join("dz", "anims", "anm", "player", "moves", "1handed", "p_1hd_erc_idle_low.anm")
GEAR_CLIP = os.path.join("dz", "anims", "anm", "player", "ik", "gear", "water_bottle.anm")
ITEM_MODEL = os.path.join("dz", "gear", "drinks", "WaterBottle.p3d")

# Measured in game on the same stance, see the module docstring.
EXPECTED_TILT = 14.2
TILT_TOLERANCE = 5.0

# The engine's grip matrix has no translation of its own, so the item's origin has
# to land exactly on the grip bone. A non-identity inverse matrix on the Child Of
# constraint is the usual way to lose this.
ORIGIN_TOLERANCE = 1e-5


def project_root():
    return os.environ.get("DZOB_PROJECT_ROOT", "P:\\")


def find_blender():
    override = os.environ.get("DZOB_BLENDER", "")
    if override:
        return override if os.path.isfile(override) else None

    found = shutil.which("blender")
    if found:
        return found

    patterns = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = "%s:\\" % letter
            if not os.path.isdir(drive):
                continue

            patterns.append(os.path.join(drive, "Program Files", "Blender Foundation", "*", "blender.exe"))
            patterns.append(os.path.join(drive, "Program Files (x86)", "Steam", "steamapps", "common", "Blender", "blender.exe"))
            patterns.append(os.path.join(drive, "Steam*", "steamapps", "common", "Blender", "blender.exe"))
            patterns.append(os.path.join(drive, "*", "steamapps", "common", "Blender", "blender.exe"))
    else:
        patterns.append("/Applications/Blender.app/Contents/MacOS/Blender")
        patterns.append("/usr/share/blender/*/blender")

    for pattern in patterns:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]

    return None


def missing_inputs():
    root = project_root()

    return [path for path in (MOVE_CLIP, GEAR_CLIP, ITEM_MODEL) if not os.path.isfile(os.path.join(root, path))]


# ----------------------------------------------------------------------------
# Inside Blender
# ----------------------------------------------------------------------------

def measure(root):
    import bpy
    import addon_utils
    from mathutils import Vector

    # Has to come before the add-on is enabled: reading the factory settings back
    # in wipes the enabled add-on list, taking the operators with it.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    sys.path.insert(0, REPO_ROOT)
    addon_utils.enable("DZObjectBuilder", default_set=True, persistent=False)

    rig_blend = os.path.join(REPO_ROOT, "DZObjectBuilder", "data", "dayz_master_rig.blend")
    with bpy.data.libraries.load(rig_blend, link=False) as (src, dst):
        dst.objects = list(src.objects)

    rig_objects = [obj for obj in dst.objects if obj is not None]
    for obj in rig_objects:
        bpy.context.scene.collection.objects.link(obj)

    armatures = sorted([obj for obj in rig_objects if obj.type == 'ARMATURE'], key=lambda obj: -len(obj.data.bones))
    arm = armatures[0]

    for obj in bpy.context.selected_objects:
        obj.select_set(False)

    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm

    # The locomotion clip carries the body, the gear clip carries the grip hand
    # and the RightHand_Dummy channel the item hangs off. Without the gear clip
    # the dummy stays at its bind position up by the chest.
    bpy.ops.dzob.import_anm(
        filepath = os.path.join(root, MOVE_CLIP),
        gear_ik_filepath = os.path.join(root, GEAR_CLIP)
    )

    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()

    bpy.ops.object.mode_set(mode='OBJECT')

    known = set(bpy.data.objects)
    bpy.ops.dzob.import_p3d(filepath=os.path.join(root, ITEM_MODEL), first_lod_only=True, proxy_action='NOTHING')
    imported = [obj for obj in bpy.data.objects if obj not in known and obj.type == 'MESH']

    item = imported[0]
    for obj in bpy.context.selected_objects:
        obj.select_set(False)

    item.select_set(True)
    bpy.context.view_layer.objects.active = item

    bpy.ops.dzob.item_grip_attach()

    bpy.context.view_layer.update()

    arm_eval = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    grip_head = (arm_eval.matrix_world @ arm_eval.pose.bones["RightHand_Dummy"].matrix).to_translation()

    world = item.matrix_world
    # P3D import maps DayZ's Y up onto Blender's Z, so the bottle's own up axis is
    # its local +Z.
    up = (world.to_3x3() @ Vector((0, 0, 1))).normalized()

    constraint = item.constraints[0]

    result = {
        "tilt": math.degrees(up.angle(Vector((0, 0, 1)))),
        "up": list(up),
        "origin_offset": (world.to_translation() - grip_head).length,
        "constraint_type": constraint.type,
        "constraint_subtarget": constraint.subtarget,
        "inverse_is_identity": constraint.inverse_matrix == constraint.inverse_matrix.Identity(4),
        "item": item.name,
    }

    result.update(measure_solver())
    result.update(measure_scene_tools(arm, item, root))

    return result


def item_tilt(item):
    import bpy
    from mathutils import Vector

    bpy.context.view_layer.update()
    up = (item.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()

    return math.degrees(up.angle(Vector((0, 0, 1))))


# Engine space arithmetic, checked against data it produced itself: compose an
# item out of a known bone and three different hand poses, then see whether the
# solver reads that bone back out. It also pins the property the whole table
# exists for - a bone that is perfect in one hand pose is far out in another.
def measure_solver():
    from mathutils import Euler, Vector

    from DZObjectBuilder.utilities import grip

    engine_grip = grip.dayz_col_from_rows(grip.GRIP_MATRIX_MEASURED)

    bone = grip.dayz_col_from_rows(Euler((0.3, -0.8, 1.1)).to_matrix())
    bone.translation = Vector((0.01, -0.02, 0.03))

    hands = []
    for index, angles in enumerate(((0.1, 0.2, 0.3), (-1.2, 0.4, 2.0), (0.8, -1.5, 0.2))):
        hand = Euler(angles).to_matrix().to_4x4()
        hand.translation = Vector((0.2 * index, 1.3, -0.1 * index))
        hands.append(hand)

    lines = []
    for hand in hands:
        for index, row in enumerate(grip.rows_from_dayz_col(grip.compose_item(hand, bone, engine_grip))):
            lines.append("item%d %.6f %.6f %.6f" % (index, row[0], row[1], row[2]))

        for index, row in enumerate(grip.rows_from_dayz_col(hand)):
            lines.append("hand%d %.6f %.6f %.6f" % (index, row[0], row[1], row[2]))

    samples, override = grip.parse_probe_samples("\n".join(lines))

    recovered = [grip.bone_from_sample(sample["item"], sample["hand"], engine_grip) for sample in samples]
    solved = [grip.upright_bone_from_sample(sample["item"], sample["hand"], engine_grip) for sample in samples]

    own, cross = [], []
    for index, candidate in enumerate(solved):
        for other, sample in enumerate(samples):
            tilt = grip.tilt_degrees(grip.compose_item(sample["hand"], candidate, engine_grip))
            (own if other == index else cross).append(tilt)

    return {
        "solver_samples": len(samples),
        "solver_override": override is not None,
        "solver_recovery_error": max(math.degrees((bone.inverted() @ found).to_quaternion().angle) for found in recovered),
        "solver_own_tilt": max(own),
        "solver_cross_tilt": max(cross),
    }


# The two operators that reach into a clip, checked end to end on the scene the
# grip matrix was validated on.
def measure_scene_tools(arm, item, root):
    import bpy

    bpy.ops.dzob.item_grip_align_upright()
    aligned = item_tilt(item)

    for obj in bpy.context.selected_objects:
        obj.select_set(False)

    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm

    action = arm.animation_data.action
    tracks_before = len(arm.animation_data.nla_tracks)
    actions_before = len(bpy.data.actions)

    bpy.ops.dzob.item_grip_copy_bone_channel(filepath=os.path.join(root, GEAR_CLIP), bones="RightHand_Dummy")

    return {
        "tilt_aligned": aligned,
        "tilt_restored": item_tilt(item),
        "copy_kept_action": arm.animation_data.action is action,
        "copy_leaked_tracks": len(arm.animation_data.nla_tracks) - tracks_before,
        "copy_leaked_actions": len(bpy.data.actions) - actions_before,
    }


def run_in_blender():
    args = sys.argv[sys.argv.index("--") + 1:]
    out_path, root = args[0], args[1]

    try:
        result = measure(root)
    except Exception as ex:
        import traceback

        traceback.print_exc()
        result = {"error": "%s: %s" % (type(ex).__name__, ex)}

    with open(out_path, "w", encoding="utf-8") as file:
        json.dump(result, file)


# ----------------------------------------------------------------------------
# Outside Blender
# ----------------------------------------------------------------------------

class TestItemGrip(unittest.TestCase):
    _result = None

    @classmethod
    def measurement(cls):
        if cls._result is not None:
            return cls._result

        blender = find_blender()
        if blender is None:
            raise unittest.SkipTest("Blender not found, set DZOB_BLENDER to its executable")

        missing = missing_inputs()
        if missing:
            raise unittest.SkipTest("Vanilla inputs not available under %s: %s" % (project_root(), ", ".join(missing)))

        handle, out_path = tempfile.mkstemp(suffix=".json")
        os.close(handle)

        try:
            process = subprocess.run(
                [blender, "--background", "--factory-startup", "--python", os.path.abspath(__file__),
                 "--", out_path, project_root()],
                capture_output = True,
                text = True
            )

            with open(out_path, encoding="utf-8") as file:
                content = file.read()
        except OSError as ex:
            raise unittest.SkipTest("Could not run Blender at %s: %s" % (blender, ex))
        finally:
            if os.path.isfile(out_path):
                os.remove(out_path)

        if not content:
            raise AssertionError("Blender produced no measurement\n%s" % process.stdout[-4000:])

        result = json.loads(content)
        if "error" in result:
            raise AssertionError("Measurement failed inside Blender: %s\n%s" % (result["error"], process.stdout[-4000:]))

        cls._result = result

        return result

    def test_constraint_is_wired_to_the_grip_bone(self):
        result = self.measurement()

        self.assertEqual(result["constraint_type"], 'CHILD_OF')
        self.assertEqual(result["constraint_subtarget"], "RightHand_Dummy")

    def test_inverse_matrix_stays_identity(self):
        # An inverse matrix baked from the current pose would pin the item to
        # whatever frame happened to be current when it was attached.
        self.assertTrue(self.measurement()["inverse_is_identity"])

    def test_item_origin_sits_on_the_grip_bone(self):
        offset = self.measurement()["origin_offset"]

        self.assertLess(offset, ORIGIN_TOLERANCE, "item origin is %.6f m off the grip bone" % offset)

    def test_solver_reads_back_the_bone_it_was_given(self):
        # Pure engine space arithmetic, so this one is exact.
        result = self.measurement()

        self.assertEqual(result["solver_samples"], 3)
        self.assertFalse(result["solver_override"])
        self.assertLess(result["solver_recovery_error"], 1e-4)

    def test_solved_bone_is_upright_on_its_own_sample(self):
        self.assertLess(self.measurement()["solver_own_tilt"], 1e-4)

    def test_solved_bone_is_not_upright_on_the_others(self):
        # The reason the operator prints a table instead of a number: the hand
        # sits in visibly different places, so a bone that is perfect in one
        # sample is tens of degrees out in another. True of vanilla items too.
        self.assertGreater(self.measurement()["solver_cross_tilt"], 30.0)

    def test_align_upright_stands_the_item_up(self):
        tilt = self.measurement()["tilt_aligned"]

        self.assertLess(tilt, 0.01, "item still sits %.4f degrees off vertical after aligning" % tilt)

    def test_copying_the_vanilla_channel_back_restores_the_vanilla_pose(self):
        # Proves the channel really came out of the file rather than being left
        # over from the aligned pose, and that the raw numbers went through the
        # importer instead of straight into the pose bone.
        result = self.measurement()

        self.assertLess(abs(result["tilt_restored"] - result["tilt"]), 0.01)

    def test_copying_a_channel_leaves_no_debris(self):
        result = self.measurement()

        self.assertTrue(result["copy_kept_action"], "the action was not restored after the copy")
        self.assertEqual(result["copy_leaked_tracks"], 0, "an NLA track from the temporary import was left behind")
        self.assertEqual(result["copy_leaked_actions"], 0, "the temporary action was left behind")

    def test_bottle_stands_up_in_the_hand(self):
        result = self.measurement()
        tilt = result["tilt"]

        self.assertLess(
            abs(tilt - EXPECTED_TILT), TILT_TOLERANCE,
            "bottle sits %.2f degrees off vertical, the game measured %.1f - the axis "
            "conversion of the grip matrix has drifted (up axis %s)" % (tilt, EXPECTED_TILT, result["up"])
        )


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401

        in_blender = True
    except ImportError:
        in_blender = False

    if in_blender:
        run_in_blender()
    else:
        unittest.main()
