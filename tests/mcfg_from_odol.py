"""Rebuilding a model.cfg out of a binarized model.

Runs without Blender: python -m unittest tests.mcfg_from_odol
"""


import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

mcfg, odol, p3d = load_io("mcfg_from_odol", "data_p3d_odol", "data_p3d")


MEMORY = 1e15


def make_lod(resolution, selections = (), vertices = ()):
    lod = odol.ODOL_LOD()
    lod.resolution = resolution
    lod.vertices = list(vertices)
    for name, indices, sectional in selections:
        selection = odol.ODOL_NamedSelection(name)
        selection.vertices = list(indices)
        selection.weights = [1.0] * len(indices)
        selection.is_sectional = sectional
        lod.named_selections.append(selection)

    return lod


def make_animation(name, anim_type, bone, axis = None, **fields):
    animation = odol.ODOL_Animation()
    animation.name = name
    animation.type = anim_type
    animation.bones = [bone]
    animation.axes = [axis]
    for key, value in fields.items():
        setattr(animation, key, value)

    return animation


def make_model(skeleton_name = "", bones = (), parents = (), lods = (), animations = ()):
    model = odol.ODOL_File()
    model.skeleton.name = skeleton_name
    model.skeleton.bones = list(bones)
    model.skeleton.parents = list(parents)
    model.lods = list(lods)
    model.animations.classes = list(animations)
    return model


class TestAxisMatching(unittest.TestCase):
    """How an axis is stored depends on what it drives, and the two cases do not match
    the same way. Getting that wrong is silent: the animation is written without an
    axis and binarize then rejects it, rather than anything failing here."""

    def setUp(self):
        # Two candidate axes in a Memory LOD, and one point selection that cannot be one.
        self.model = make_model(lods = [make_lod(MEMORY, [
            ("bolt_axis", [0, 1], False),
            ("hammer_axis", [2, 3], False),
            ("eye", [4], False),
        ], vertices = [
            (-0.196, 0.065, 0.0), (-0.136, 0.065, 0.0),
            (-0.022, 0.049, -0.003), (-0.022, 0.049, 0.004),
            (0.3, 0.082, 0.0),
        ])])
        self.candidates = mcfg.axis_candidates(self.model)

    def test_only_two_point_selections_are_candidates(self):
        self.assertEqual(sorted(self.candidates), ["bolt_axis", "hammer_axis"])

    def test_rotation_matches_a_line(self):
        # Position is a point on the axis and direction is normalised.
        name = mcfg.match_axis((-0.022, 0.049, -0.003), (0.0, 0.0, 1.0), self.candidates, True)
        self.assertEqual(name, "hammer_axis")

    def test_translation_matches_the_span_itself(self):
        # Position is not stored at all, and direction is the span at its true length.
        name = mcfg.match_axis((0.0, 0.0, 0.0), (0.06, 0.0, 0.0), self.candidates, False)
        self.assertEqual(name, "bolt_axis")

    def test_translation_span_is_matched_either_way_round(self):
        name = mcfg.match_axis((0.0, 0.0, 0.0), (-0.06, 0.0, 0.0), self.candidates, False)
        self.assertEqual(name, "bolt_axis")

    def test_a_direction_no_candidate_carries_matches_nothing(self):
        # The degenerate axis a model gets when binarizing could not resolve one: the
        # X axis through the origin. Inventing a name for it would be worse than none.
        self.assertIsNone(mcfg.match_axis((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), self.candidates, True))

    def test_a_translation_of_the_wrong_length_matches_nothing(self):
        self.assertIsNone(mcfg.match_axis((0.0, 0.0, 0.0), (0.09, 0.0, 0.0), self.candidates, False))


class TestBuild(unittest.TestCase):
    def build(self, model, name = "weapon"):
        cfg, unmatched = mcfg.build([(name, model)])
        return cfg.format(), unmatched

    def test_skeleton_bones_are_written_as_bone_parent_pairs(self):
        model = make_model("Rifle", ["recoil", "bolt"], ["", "recoil"])
        text, _ = self.build(model)

        self.assertIn("class Rifle", text)
        self.assertIn('"recoil",', text)
        self.assertIn('"bolt",', text)
        self.assertIn('skeletonName = "Rifle"', text)

    def test_sections_come_from_the_sectional_flag(self):
        model = make_model(lods = [make_lod(0.0, [
            ("camo", [0], True),
            ("bolt", [1], False),
        ])])
        text, _ = self.build(model)

        self.assertIn('"camo"', text)
        self.assertNotIn('"bolt"', text)

    def test_a_rotation_is_written_with_its_selection_and_axis(self):
        model = make_model("Rifle", ["hammer"], [""], lods = [make_lod(MEMORY,
            [("hammer_axis", [0, 1], False)],
            vertices = [(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)])])
        model.animations.classes = [make_animation("hammer_rot", 0, 0,
                                                   axis = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
                                                   min_value = 0.0, max_value = 1.0,
                                                   value0 = 0.0, value1 = 1.5, source = "reload",
                                                   source_address = 1)]
        text, unmatched = self.build(model)

        self.assertEqual(unmatched, [])
        self.assertIn("class hammer_rot", text)
        self.assertIn('type = "rotation"', text)
        self.assertIn('selection = "hammer"', text)
        self.assertIn('axis = "hammer_axis"', text)
        self.assertIn('sourceAddress = "mirror"', text)
        self.assertIn("angle1", text)
        self.assertNotIn("offset1", text)

    def test_a_hide_is_written_without_an_axis(self):
        model = make_model("Rifle", ["magazine"], [""])
        model.animations.classes = [make_animation("mag_hide", 9, 0, hide_value = 0.5,
                                                   source = "reloadmagazine")]
        text, unmatched = self.build(model)

        self.assertEqual(unmatched, [])
        self.assertIn('type = "hide"', text)
        self.assertIn("hideValue", text)
        self.assertNotIn("axis =", text)

    def test_an_unmatched_axis_is_reported_not_invented(self):
        model = make_model("Rifle", ["shell"], [""], lods = [make_lod(MEMORY, [], [])])
        model.animations.classes = [make_animation("shell_rot", 0, 0,
                                                   axis = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))]
        text, unmatched = self.build(model)

        self.assertEqual(unmatched, ["weapon/shell_rot"])
        self.assertNotIn("axis =", text)

    def test_models_worth_writing(self):
        # A model that lost nothing to binarizing would contribute only the defaults it
        # already inherits, so it is left out of the file entirely.
        self.assertFalse(mcfg.is_worth_writing(make_model()))
        self.assertTrue(mcfg.is_worth_writing(make_model("Rifle")))
        self.assertTrue(mcfg.is_worth_writing(make_model(lods = [make_lod(0.0, [("camo", [0], True)])])))

    def test_every_model_in_a_folder_lands_in_one_file(self):
        first = make_model("Rifle", ["bolt"], [""])
        second = make_model("Pistol", ["slide"], [""])
        cfg, _ = mcfg.build([("rifle", first), ("pistol", second)])
        text = cfg.format()

        self.assertIn("class Rifle", text)
        self.assertIn("class Pistol", text)
        self.assertIn("class rifle: Default", text)
        self.assertIn("class pistol: Default", text)

    def test_one_skeleton_shared_by_two_models_is_written_once(self):
        first = make_model("Rifle", ["bolt"], [""])
        second = make_model("Rifle", ["bolt"], [""])
        cfg, _ = mcfg.build([("a", first), ("b", second)])

        self.assertEqual(cfg.format().count("skeletonBones[]"), 1)


if __name__ == "__main__":
    unittest.main()
