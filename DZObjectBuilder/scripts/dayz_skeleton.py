#   ---------------------------------------- HEADER ----------------------------------------
#
#   Author: MrClock
#   Add-on: DayZ Object Builder
#
#   Description:
#       The script adds the DayzTemporarySkeleton to the skeleton list of the Rigging tool panel.
#
#   Usage:
#       1. run script
#
#   ----------------------------------------------------------------------------------------


#   ---------------------------------------- LOGIC -----------------------------------------

import importlib

import bpy

name = None
for addon in bpy.context.preferences.addons:
    if addon.module.endswith("DZObjectBuilder"):
        name = addon.module
        break
else:
    raise Exception("DayZ Object Builder could not be found")

a3ob = importlib.import_module(name)
data = a3ob.utilities.data


def main():
    scene_props = bpy.context.scene.a3ob_rigging
    skeleton = scene_props.skeletons.add()
    skeleton.name = "DayzTemporarySkeleton"
    skeleton.protected = True

    for bone, parent in data.dayz_temporary_skeleton.items():
        item = skeleton.bones.add()
        item.name = bone
        item.parent = parent


main()
