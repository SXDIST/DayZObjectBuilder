"""
python tests/anm_shape.py

Pins the export time warnings about how a written clip compares to vanilla.

Two properties matter here and neither is about the maths. A warning must not
fire on a clip that matches vanilla's shape - a gear clip keys translation on
every bone and is built entirely out of right hand bones, and both of those are
correct there, so warning about them would train people to ignore the warnings.
And the wording must stay descriptive: every one of these differences was
suspected of breaking a held item and ruled out in game, so a message that calls
one of them a fault would send the next person down a dead end that has already
been walked.
"""


import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

shape = load_io("anm_shape")


# 65 bones, translation on 5 of them: the shape of p_1hd_erc_idle_low.
def vanilla_movement_clip():
    bones = ["Bone%02d" % index for index in range(60)]
    bones += ["Pelvis", "LeftHand_Dummy", "EntityPosition", "Collision", "Scene_Root"]

    return bones, ["Pelvis", "LeftHand_Dummy", "EntityPosition", "Collision", "Scene_Root"]


# 22 bones, all of them right hand, translation on all of them: a gear clip.
def vanilla_gear_clip():
    bones = ["RightHand_Dummy"] + ["RightHandIndex%d" % index for index in range(21)]

    return bones, list(bones)


class TestGearLayerBones(unittest.TestCase):
    def test_fingers_and_dummy_belong_to_the_gear_layer(self):
        for name in ("RightHand_Dummy", "RightHandIndex1", "righthandthumb3", "RightHandPinky2"):
            self.assertTrue(shape.is_gear_layer_bone(name), "%s should count as a gear layer bone" % name)

    def test_the_wrist_itself_does_not(self):
        # RightHand is part of the arm and belongs in a movement clip.
        self.assertFalse(shape.is_gear_layer_bone("RightHand"))

    def test_the_left_hand_does_not(self):
        for name in ("LeftHand", "LeftHand_Dummy", "LeftHandIndex1"):
            self.assertFalse(shape.is_gear_layer_bone(name))


class TestClipWarnings(unittest.TestCase):
    def test_vanilla_movement_clip_is_silent(self):
        bones, translated = vanilla_movement_clip()

        self.assertEqual(shape.clip_warnings(bones, translated), [])

    def test_gear_clip_is_silent(self):
        # Every bone keyed for translation and nothing but right hand bones is
        # exactly right for a gear clip, and must not warn.
        bones, translated = vanilla_gear_clip()

        self.assertEqual(shape.clip_warnings(bones, translated), [])

    def test_translation_on_every_bone_warns(self):
        bones, _translated = vanilla_movement_clip()
        warnings = shape.clip_warnings(bones, bones)

        self.assertEqual(len(warnings), 1)
        self.assertIn("differs from the vanilla shape", warnings[0])

    def test_no_translation_at_all_is_silent(self):
        bones, _translated = vanilla_movement_clip()

        self.assertEqual(shape.clip_warnings(bones, []), [])

    def test_right_hand_bones_in_a_movement_clip_warn(self):
        bones, translated = vanilla_movement_clip()
        bones = bones + ["RightHand_Dummy", "RightHandIndex1"]
        warnings = shape.clip_warnings(bones, translated)

        self.assertEqual(len(warnings), 1)
        self.assertIn("gear IK layer", warnings[0])

    def test_both_differences_are_reported_separately(self):
        bones, _translated = vanilla_movement_clip()
        bones = bones + ["RightHand_Dummy"]

        self.assertEqual(len(shape.clip_warnings(bones, bones)), 2)

    def test_no_warning_claims_the_clip_is_broken(self):
        # The wording is the point: these differences were all tested in game
        # and none of them was the fault, so a message may describe the
        # difference but never diagnose it.
        bones, _translated = vanilla_movement_clip()
        warnings = shape.clip_warnings(bones + ["RightHand_Dummy"], bones)

        self.assertTrue(warnings)
        for warning in warnings:
            lowered = warning.lower()
            for word in ("broken", "invalid", "wrong", "bug", "must be", "error"):
                self.assertNotIn(word, lowered, "%r reads as a diagnosis, not a difference" % warning)

            self.assertIn("differs from the vanilla shape", warning)


if __name__ == "__main__":
    unittest.main()
