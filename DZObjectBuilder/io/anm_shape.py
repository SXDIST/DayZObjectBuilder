# How a written .anm clip compares to the shape vanilla clips have.
#
# These are observations about vanilla, turned into export time warnings. None
# of them is a bug report: every one of them was suspected of causing a held
# item to sit wrong in the hand, and every one of them was ruled out in game -
# the clips were rebuilt without the difference and the item was still wrong.
# They are worth surfacing because a clip that differs from the vanilla shape is
# worth a second look, not because the difference is known to break anything.
#
# Wording matters here. Each message says the clip "differs from the vanilla
# shape", never that it is wrong, so a warning cannot send the next person down
# the same four dead ends. Pure data, no bpy.


# Bones vanilla movement clips carry a translation channel on: 5 out of the 65
# bones in p_1hd_erc_idle_low. Gear clips are the other case entirely - all 22
# of their bones carry one - so the rule below only looks at movement shaped
# clips.
VANILLA_TRANSLATION_BONES = frozenset((
    "pelvis",
    "lefthand_dummy",
    "entityposition",
    "collision",
    "scene_root",
))

# Vanilla movement clips hold 65 bones, gear clips 22, and nothing sits in
# between - so the split only has to land somewhere in the gap.
MOVEMENT_CLIP_MIN_BONES = 40


# The right hand below the wrist: the fingers and the grip dummy. In vanilla
# these come from the gear layer, and the action clip does not mention them.
# RightHand itself is part of the arm and belongs in a movement clip, so it is
# the one name in this family that is not gear layer.
def is_gear_layer_bone(name):
    lowered = name.lower()

    return lowered.startswith("righthand") and lowered != "righthand"


def is_movement_clip(bone_names):
    return len(bone_names) >= MOVEMENT_CLIP_MIN_BONES


# bone_names: every bone written into the clip.
# translation_bones: the subset that got a translation channel.
# Returns a list of message strings, empty when the clip matches vanilla's shape.
def clip_warnings(bone_names, translation_bones):
    bone_names = list(bone_names)
    translation_bones = list(translation_bones)

    if not is_movement_clip(bone_names):
        return []

    warnings = []

    extra_translation = sorted({name for name in translation_bones if name.lower() not in VANILLA_TRANSLATION_BONES})
    if extra_translation:
        warnings.append(
            "Translation is written on %d of %d bones; vanilla movement clips key it on %d (%s). "
            "The translation option is per clip, not per bone, so every keyed bone gets a rest "
            "offset rather than animation. This differs from the vanilla shape - it was tested in "
            "game and is not what breaks a held item."
            % (len(translation_bones), len(bone_names), len(VANILLA_TRANSLATION_BONES),
               ", ".join(sorted(VANILLA_TRANSLATION_BONES)))
        )

    gear_layer = sorted({name for name in bone_names if is_gear_layer_bone(name)})
    if gear_layer:
        warnings.append(
            "The clip carries %d right hand bone(s) below the wrist (%s%s); vanilla action clips "
            "carry neither the right hand fingers nor RightHand_Dummy, because those come from the "
            "gear IK layer. This differs from the vanilla shape - dropping them was tested in game "
            "and changed nothing, while it did leave the hand unanimated in the scene."
            % (len(gear_layer), ", ".join(gear_layer[0:4]), ", ..." if len(gear_layer) > 4 else "")
        )

    return warnings
