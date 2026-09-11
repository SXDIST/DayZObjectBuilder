# Channel access for slotted actions.
#
# From Blender 4.4 an action no longer owns its fcurves directly: they sit in
# per-slot channelbags inside the strips of its layers, and `action.fcurves` is
# gone. Every read here goes through both shapes so the helpers keep working on
# a legacy action too.


def iter_channels(action):
    # Yields (container, fcurve) pairs; the container is what a removal has to
    # go through, since fcurves cannot be removed from the action itself.
    if action is None:
        return

    layers = getattr(action, "layers", None)
    if layers:
        for layer in layers:
            for strip in layer.strips:
                for slot in action.slots:
                    bag = strip.channelbag(slot)
                    if bag is None:
                        continue

                    for fcurve in bag.fcurves:
                        yield bag, fcurve
    else:
        for fcurve in action.fcurves:
            yield action, fcurve


def iter_fcurves(action):
    for _container, fcurve in iter_channels(action):
        yield fcurve


def bone_path(bone_name, prop):
    return 'pose.bones["%s"].%s' % (bone_name, prop)


def bone_name_of(data_path):
    if not data_path.startswith('pose.bones['):
        return None

    parts = data_path.split('"')

    return parts[1] if len(parts) > 1 else None


# The fcurves an action already holds for one bone property, ordered by array
# index. Missing indices simply do not appear.
def find_bone_fcurves(action, bone_name, prop):
    path = bone_path(bone_name, prop)
    found = [fcurve for fcurve in iter_fcurves(action) if fcurve.data_path == path]
    found.sort(key=lambda fcurve: fcurve.array_index)

    return found


def ensure_bone_fcurves(action, obj, bone_name, prop, count):
    return [
        action.fcurve_ensure_for_datablock(obj, bone_path(bone_name, prop), index=index, group_name=bone_name)
        for index in range(count)
    ]


def remove_bone_fcurves(action, bone_name, prop):
    path = bone_path(bone_name, prop)
    doomed = [(container, fcurve) for container, fcurve in iter_channels(action) if fcurve.data_path == path]

    for container, fcurve in doomed:
        container.fcurves.remove(fcurve)

    return len(doomed)


def keyed_frames(fcurves):
    frames = set()
    for fcurve in fcurves:
        for point in fcurve.keyframe_points:
            frames.add(round(point.co[0]))

    return sorted(frames)


# Overwrite one keyframe's value, adding the key when the channel does not have
# one at that frame yet.
def set_key(fcurve, frame, value):
    for point in fcurve.keyframe_points:
        if round(point.co[0]) == round(frame):
            point.co = (point.co[0], value)
            point.interpolation = 'LINEAR'
            return

    fcurve.keyframe_points.insert(frame, value, options={'FAST'})
    fcurve.keyframe_points[-1].interpolation = 'LINEAR'
