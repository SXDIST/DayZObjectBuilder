# DayZ Object Builder

DayZ Object Builder (DZOB) is a free add-on for Blender to help content development for DayZ. It is a fork of [Arma 3 Object Builder](https://github.com/MrClock8163/Arma3ObjectBuilder) by MrClock, which in turn is based on the ideas of the [ArmAToolbox](https://github.com/AlwarrenSidh/ArmAToolbox) add-on developed by Alwarren.

## Main features

- P3D import-export
- Binarized (ODOL) P3D import
- XOB import (Enfusion models: armature, mesh, skin weights, UVs and materials)
- ANM import-export (Enfusion animations), with an item's gear IK clip optionally laid over on import
- ASC import-export
- PAA import
- skeleton import-export (model.cfg)
- object list import-export (for Terrain Builder)
- Auto LODs Generator: Resolution, Geometry, Memory, Fire Geometry and View Geometry LODs in one click
- bundled DayZ character master rig, added from the `Add` menu
- item grip tools: attach a held item to the hand with the engine's measured grip matrix, align it upright, solve the grip bone from an in-game probe log, and copy a bone channel out of an `.anm`
- armature reconstruction
- texture set auto-search
- various editing tools
- utility functions and scripts

## Differences from upstream

- Windows long path (`MAX_PATH`) support throughout file I/O, for deeply nested unpacked asset trees
- import/export operators report failures as errors instead of raising unhandled tracebacks
- texture and RVMAT auto-search over a mod root, matching sets even when the normal map is named differently from the color map
- binarized (ODOL) P3D import, read directly through the normal P3D import with no external debinarizer; all three versions DayZ uses are read: 54, which the game files use, 53, which the DayZ Tools binarizer writes, and 55, which the current AddonBuilder writes. Every UV set is kept. Conversion is lossy and one way, the add-on never writes ODOL, and a re-exported model is degraded relative to the original source
- whole-mod debinarization outside Blender (`tools/debinarize_mod.py`), which also rebuilds the `model.cfg` each output folder needs: skeleton and bone hierarchy, `sections[]`, and the animation classes with their selections and axes; plus bulk LOD generation for a whole mod (`tools/generate_lods.py`, `tools/generate_lods_batch.py`)
- P3D export keeps the case of selection names and normalizes skin weights; import restores PascalCase for known DayZ skeleton selections
- `.anm` export writes only the bones the action keys by default, and reports where a clip is shaped differently from vanilla clips
- the grip matrix for a held item is a value measured in a running game, not derived, and can be updated from a fresh probe reading in the preferences

## Documentation

The add-on keeps the `.blend` custom-property identifiers of the upstream project (so existing files keep working), while operator and panel identifiers have been renamed to the DZOB namespace. The workflow and panel layout stay close to upstream, so the documentation on [GitBook](https://mrcmodding.gitbook.io/arma-3-object-builder/home) still describes most of DZOB accurately. Features added in this fork are documented in this repository.

## Installation

The add-on can be installed after either downloading a packaged release, or cloning the repository and manually packing it.
For information about add-on installation, visit the official [Blender documentation](https://docs.blender.org/manual/en/latest/editors/preferences/addons.html) page about add-ons.

DZOB is not published on the Blender Extensions repository. It registers the same `.blend` custom-property identifiers as Arma 3 Object Builder, so the two add-ons cannot be enabled at the same time.

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR  PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see the [GNU licenses](http://www.gnu.org/licenses/).
