# Rebuilds the model.cfg of a binarized model from the model itself.
#
# An editable .p3d carries no skeleton, no sections and no animations; those live in the
# model.cfg beside it and are read at binarize time. Binarizing folds them into the ODOL
# file, so a model that is debinarized without also writing that model.cfg back out is
# not the model that went in - it loses its bone hierarchy, its hidden selections and
# every moving part. This module is the other half of odol_to_mlod.py: that one recovers
# the geometry, this one recovers what the geometry was configured with.
#
# Everything here is recovered, not invented, with one exception that is called out where
# it happens: an animation's axis. CfgModels names an axis, while ODOL stores it as a
# point and a direction, so the name has to be found by matching those numbers against
# the Memory LOD's own two-point selections. Measured on the IMPWMOD corpus, all 23
# axis-carrying animations across 505 models match a named selection exactly, so the name
# is recovered rather than fabricated; models where no candidate matches are reported by
# build() instead of being given a made up axis.


from . import config
from . import data_p3d as p3d


# The animation type is stored as the engine's enum. These are the CfgModels names it
# was written from, and 8 and 9 are the two the reader singles out because they change
# the record layout (ANIM_DIRECT and ANIM_HIDE in data_p3d_odol).
ANIMATION_TYPES = {
    0: "rotation",
    1: "rotationX",
    2: "rotationY",
    3: "rotationZ",
    4: "translation",
    5: "translationX",
    6: "translationY",
    7: "translationZ",
    8: "direct",
    9: "hide",
}

SOURCE_ADDRESSES = {
    0: "clamp",
    1: "mirror",
    2: "loop",
}

# How an axis is stored depends on what it drives, measured on mp443.p3d against a Memory
# LOD whose axis selections are known by name:
#
#   Rotations     position is the selection's first point and direction is normalised, so
#                 the pair describes a line and the match is: parallel, and the point on
#                 that line. hammer_fire_begin holds (-0.022, 0.0491, -0.0033) and
#                 (0, 0, 1), against hammer_axis running from that same point to
#                 (-0.022, 0.0491, 0.0037).
#
#   Translations  position is not stored at all - it is (0, 0, 0) on every one of them -
#                 and direction is the span between the selection's two points, kept at
#                 its true length rather than normalised. So the match is an equality of
#                 vectors: bolt_fire_begin holds (0.06, 0, 0), and bolt_axis spans exactly
#                 (0.06, 0, 0). Matching these as lines is what a first attempt got wrong,
#                 and it silently dropped the axis off 10 of mp443's 18 animations.
#
# The tolerances are loose against what a true match scores (under 1e-6 on the corpus) and
# tight against the nearest wrong candidate for the same animation (worse by at least
# three orders of magnitude).
AXIS_PARALLEL_TOLERANCE = 1e-4
AXIS_DISTANCE_TOLERANCE = 1e-4
AXIS_SPAN_TOLERANCE = 1e-4


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def length(vector):
    return dot(vector, vector) ** 0.5


# The two-point named selections of the Memory LOD, which is where an axis can live. A
# selection with any other number of points cannot be one, so it is not a candidate.
def axis_candidates(odol_file):
    output = {}
    for lod in odol_file.lods:
        if p3d.P3D_LOD_Resolution.from_float(lod.resolution).lod != p3d.P3D_LOD_Resolution.MEMORY:
            continue

        for selection in lod.named_selections:
            if len(selection.vertices) != 2:
                continue

            try:
                points = [lod.vertices[index] for index in selection.vertices]
            except IndexError:
                continue

            output[selection.name] = points

    return output


def match_axis(position, direction, candidates, is_rotation):
    best = None
    for name, (start, end) in candidates.items():
        span = subtract(end, start)
        if length(span) < 1e-9 or length(direction) < 1e-9:
            continue

        if is_rotation:
            score = abs(abs(dot(span, direction)) / (length(span) * length(direction)) - 1)
            if score > AXIS_PARALLEL_TOLERANCE:
                continue

            # Distance from the animation's axis point to the candidate's line.
            offset = subtract(position, start)
            projected = tuple(start[i] + dot(offset, span) / dot(span, span) * span[i] for i in range(3))
            distance = length(subtract(position, projected))
            if distance > AXIS_DISTANCE_TOLERANCE:
                continue

            score = (score, distance)
        else:
            # The stored vector is the span itself, either way round.
            distance = min(length(subtract(span, direction)),
                           length(subtract(tuple(-value for value in span), direction)))
            if distance > AXIS_SPAN_TOLERANCE:
                continue

            score = (distance, 0.0)

        if best is None or score < best[0]:
            best = (score, name)

    return best[1] if best else None


def animation_properties(animation, bones, candidates, unmatched):
    properties = {
        "type": ANIMATION_TYPES.get(animation.type, "rotation"),
        "source": animation.source,
    }

    # The bone the animation drives is stated per LOD; every LOD that drives it names the
    # same bone, so the first one that does is the selection CfgModels declared.
    bone = next((index for index in animation.bones if index != -1), -1)
    if 0 <= bone < len(bones):
        properties["selection"] = bones[bone]

    properties["minValue"] = animation.min_value
    properties["maxValue"] = animation.max_value

    if animation.type == 9:                     # hide
        properties["hideValue"] = animation.hide_value
    elif animation.type == 8:                   # direct
        properties["axisPos"] = list(animation.axis_position)
        properties["axisDir"] = list(animation.axis_direction)
        properties["angle"] = animation.angle
        properties["axisOffset"] = animation.axis_offset
    elif animation.type < 4:                    # the rotations
        properties["angle0"] = animation.value0
        properties["angle1"] = animation.value1
    else:                                       # the translations
        properties["offset0"] = animation.value0
        properties["offset1"] = animation.value1

    # Rotations and translations turn around an axis the config names. ODOL keeps the
    # numbers instead, so the name comes back from matching them against the Memory LOD.
    if animation.type not in (8, 9):
        axis = next((item for item in animation.axes if item), None)
        if axis:
            name = match_axis(axis[0], axis[1], candidates, animation.type < 4)
            if name:
                properties["axis"] = name
            else:
                unmatched.append(animation.name)

    address = SOURCE_ADDRESSES.get(animation.source_address)
    if address:
        properties["sourceAddress"] = address

    return properties


# Selections the engine keeps as their own drawable run. This is the sections[] array of
# CfgModels, consumed into a per selection flag at binarize time; a selection is listed
# once no matter how many LODs carry it.
def sections(odol_file):
    output = []
    for lod in odol_file.lods:
        for selection in lod.named_selections:
            if selection.is_sectional and selection.name and selection.name not in output:
                output.append(selection.name)

    return output


def skeleton_properties(skeleton):
    # skeletonBones is a flat array of bone, parent, bone, parent. A root bone carries an
    # empty parent, which is exactly how it is stored.
    bones = []
    for bone, parent in zip(skeleton.bones, skeleton.parents):
        bones.extend([bone, parent])

    return {
        "isDiscrete": int(skeleton.is_discrete),
        "skeletonInherit": "",
        "skeletonBones": bones,
        "pivotsModel": skeleton.pivots,
    }


def model_properties(name, odol_file, unmatched):
    properties = {
        "sectionsInherit": "",
        "sections": sections(odol_file),
        "skeletonName": odol_file.skeleton.name,
    }

    classes = {}
    if odol_file.animations:
        candidates = axis_candidates(odol_file)
        animations = {}
        for animation in odol_file.animations.classes:
            if not animation.name:
                continue

            missing = []
            animations[animation.name] = {
                "properties": animation_properties(animation, odol_file.bones, candidates, missing)
            }
            unmatched.extend("%s/%s" % (name, item) for item in missing)

        if animations:
            classes["Animations"] = {"classes": animations}

    return {"properties": properties, "classes": classes}


# A model is worth a model.cfg entry only if binarizing took something from it. A model
# with no skeleton, no sections and no animations had nothing to fold in, and an entry
# for it would state only the defaults it already inherits.
def is_worth_writing(odol_file):
    return bool(odol_file.skeleton.name or odol_file.animations or sections(odol_file))


# `models` is a sequence of (model name without extension, ODOL_File). Returns the config
# tree and the list of animations whose axis could not be matched, so a caller can report
# them rather than silently ship a model.cfg with a moving part that does not move.
def build(models):
    unmatched = []

    skeletons = {}
    for _, odol_file in models:
        skeleton = odol_file.skeleton
        if not skeleton.name or skeleton.name in skeletons:
            continue

        skeletons[skeleton.name] = {"properties": skeleton_properties(skeleton)}

    # Default first: CfgModels entries inherit from it, and a parent has to exist in the
    # tree before a class can name it.
    entries = {
        "Default": {
            "properties": {
                "sectionsInherit": "",
                "sections": [],
                "skeletonName": "",
            }
        }
    }

    for name, odol_file in models:
        entry = model_properties(name, odol_file, unmatched)
        entry["parent"] = "Default"
        entries[name] = entry

    root = {"classes": {}}
    if skeletons:
        root["classes"]["CfgSkeletons"] = {"classes": skeletons}

    root["classes"]["CfgModels"] = {"classes": entries}

    return config.from_dict({"root": root}), unmatched


# Written to match the shape of a vanilla DayZ model.cfg (P:\DZ\weapons\firearms\AKM),
# rather than whatever a generic config writer produces: the skeleton class carries
# skeletonInherit, isDiscrete and SkeletonBones in that order and nothing else, and a
# model class carries only skeletonName and sections[]. The extra properties an earlier
# version emitted here - sectionsInherit on the model class, pivotsModel on the skeleton -
# appear in no vanilla file.
def format_file(models):
    unmatched = []

    skeletons = {}
    for _, odol_file in models:
        skeleton = odol_file.skeleton
        if skeleton.name and skeleton.name not in skeletons:
            skeletons[skeleton.name] = skeleton

    lines = []
    if skeletons:
        lines.append("class cfgSkeletons")
        lines.append("{")
        for name, skeleton in skeletons.items():
            lines.append("\tclass %s" % name)
            lines.append("\t{")
            lines.append('\t\tskeletonInherit = "";')
            lines.append("\t\tisDiscrete = %d;" % int(skeleton.is_discrete))
            lines.append("\t\tSkeletonBones[]=")
            lines.append("\t\t{")
            pairs = ['\t\t\t"%s"\t,"%s"' % (bone, parent)
                     for bone, parent in zip(skeleton.bones, skeleton.parents)]
            lines.append(",\n".join(pairs))
            lines.append("\t\t};")
            lines.append("\t};")

        lines.append("};")

    lines.append("class CfgModels")
    lines.append("{")
    lines.append("\tclass Default")
    lines.append("\t{")
    lines.append("\t\tsections[] = {};")
    lines.append('\t\tsectionsInherit="";')
    lines.append('\t\tskeletonName = "";')
    lines.append("\t};")

    for name, odol_file in models:
        lines.append("\tclass %s:Default" % name)
        lines.append("\t{")
        lines.append('\t\tskeletonName="%s";' % odol_file.skeleton.name)

        names = sections(odol_file)
        if names:
            lines.append("\t\tsections[]=")
            lines.append("\t\t{")
            lines.append(",\n".join('\t\t\t"%s"' % item for item in names))
            lines.append("\t\t};")

        if odol_file.animations:
            candidates = axis_candidates(odol_file)
            animations = []
            for animation in odol_file.animations.classes:
                if not animation.name:
                    continue

                missing = []
                properties = animation_properties(animation, odol_file.bones, candidates, missing)
                unmatched.extend("%s/%s" % (name, item) for item in missing)

                animations.append("\t\t\tclass %s" % animation.name)
                animations.append("\t\t\t{")
                for key, value in properties.items():
                    if isinstance(value, str):
                        animations.append('\t\t\t\t%s="%s";' % (key, value))
                    elif isinstance(value, list):
                        animations.append("\t\t\t\t%s[]={%s};" % (key, ",".join("%f" % item for item in value)))
                    elif isinstance(value, int):
                        animations.append("\t\t\t\t%s=%d;" % (key, value))
                    else:
                        animations.append("\t\t\t\t%s=%f;" % (key, value))

                animations.append("\t\t\t};")

            if animations:
                lines.append("\t\tclass Animations")
                lines.append("\t\t{")
                lines.extend(animations)
                lines.append("\t\t};")

        lines.append("\t};")

    lines.append("};")
    return "\n".join(lines) + "\n", unmatched


def write_file(models, path):
    text, unmatched = format_file(models)
    with open(path, "wt", encoding="utf8", newline="\r\n") as file:
        file.write(text)

    return unmatched
