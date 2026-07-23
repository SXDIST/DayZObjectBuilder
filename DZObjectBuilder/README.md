# DayZ Object Builder

DayZ Object Builder (DZOB) is a free add-on for Blender to help content development for DayZ and Arma. It is a fork of [Arma 3 Object Builder](https://github.com/MrClock8163/Arma3ObjectBuilder) by MrClock, which in turn is based on the ideas of the [ArmAToolbox](https://github.com/AlwarrenSidh/ArmAToolbox) add-on developed by Alwarren.

## Main features

- P3D import-export
- Binarized (ODOL) P3D import
- ASC import-export
- PAA import
- skeleton import-export (model.cfg)
- object list import-export (for Terrain Builder)
- armature reconstruction
- texture set auto-search
- various editing tools
- utility functions and scripts

## Differences from upstream

- Windows long path (`MAX_PATH`) support throughout file I/O, for deeply nested unpacked asset trees
- import/export operators report failures as errors instead of raising unhandled tracebacks
- texture and RVMAT auto-search over a mod root, matching sets even when the normal map is named differently from the color map
- binarized (ODOL) P3D import, read directly through the normal P3D import with no external debinarizer; conversion is lossy and one way, the add-on never writes ODOL, and a re-exported model is degraded relative to the original source

## Documentation

The add-on keeps the operator, property and panel identifiers of the upstream project, so the upstream documentation on [GitBook](https://mrcmodding.gitbook.io/arma-3-object-builder/home) applies to DZOB as well. Features added in this fork are documented in this repository.

## Installation

The add-on can be installed after either downloading a packaged release, or cloning the repository and manually packing it.
For information about add-on installation, visit the official [Blender documentation](https://docs.blender.org/manual/en/latest/editors/preferences/addons.html) page about add-ons.

DZOB is not published on the Blender Extensions repository. It registers the same operator and property identifiers as Arma 3 Object Builder, so the two add-ons cannot be enabled at the same time.

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR  PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see the [GNU licenses](http://www.gnu.org/licenses/).
