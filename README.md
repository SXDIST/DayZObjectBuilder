# DayZ Object Builder

**DayZ Object Builder** (**DZOB**) is a free add-on for **Blender** that imports and exports the model, animation and terrain formats used by **DayZ** and **Arma 3**, and provides the editing tools that go with them.

It is a fork of [**Arma 3 Object Builder**](https://github.com/MrClock8163/Arma3ObjectBuilder) by MrClock, focused on the **DayZ** workflow. Because both games share the P3D, RVMAT and RTM formats, the add-on stays fully usable for **Arma 3** content as well.

## Features

- P3D import-export
- RTM animation import-export
- ASC terrain import-export
- PAA texture import
- skeleton import-export (model.cfg)
- object list import-export (for Terrain Builder)
- armature reconstruction
- texture set auto-search
- proxy, mass, hit point, rigging and validation tools
- utility functions and scripts

## Changes in this fork

- **Windows long path support.** Paths over the 260 character `MAX_PATH` limit are opened through the extended-length API. Unpacked game asset trees routinely exceed it, especially once the temporary suffix is appended during export.
- **Import and export errors are reported, not raised.** Failures surface as an operator error with the traceback in the system console, instead of an unhandled Blender popup.
- **Texture and RVMAT auto-search.** Point the add-on at a mod root and it resolves the face texture and bound RVMAT for a material from its Base Color image. RVMAT candidates are ranked by whether they actually reference the resolved `.paa`, so sets whose normal map is named differently from the color map still match.

## Requirements and Compatibility

- [**Blender** v2.90.0](https://www.blender.org/download/releases/2-90/) or higher
- [**DayZ Tools**](https://store.steampowered.com/app/830640/DayZ_Tools/) or [**Arma 3 Tools**](https://store.steampowered.com/app/233800/Arma_3_Tools/) (optional, required for some features)

The add-on is developed on **Blender** v2.90.0, which has the side effect that it supports older releases and not just the latest ones. It is tested on newer releases regardless. If a future **Blender** release makes it impossible to stay compatible with both, support for legacy versions will be dropped in favour of the new API.

## Installation

Download a packaged release, or clone this repository and pack the `DZObjectBuilder/` folder manually. See the official [**Blender** documentation](https://docs.blender.org/manual/en/latest/editors/preferences/addons.html) on installing add-ons.

> **DZOB cannot be enabled alongside Arma 3 Object Builder.** The fork deliberately keeps the upstream operator, property and panel identifiers, so both add-ons register the same names. Disable one before enabling the other.

That same decision is what keeps existing `.blend` files working: the Arma metadata on your objects is stored under the upstream property names, and renaming those would silently drop it.

## Documentation

Since the identifiers and panels match upstream, MrClock's documentation on [GitBook](https://mrcmodding.gitbook.io/arma-3-object-builder/home) describes this add-on accurately. Features specific to this fork are documented above and in `DZObjectBuilder/CHANGELOG.md`.

## Credits

The lineage of this add-on:

- [**ArmAToolbox**](https://github.com/AlwarrenSidh/ArmAToolbox) by Hans-Joerg "Alwarren" Frieden — the original Blender add-on for the Arma engine formats.
- [**Arma 3 Object Builder**](https://github.com/MrClock8163/Arma3ObjectBuilder) by MrClock — a reimplementation of a similar workflow with extended features and an interface closer to Blender's design. This fork's direct parent, and the source of nearly all of its code.
- **DayZ Object Builder** — this fork.

The name goes back to the **Object Builder** application shipped by Bohemia Interactive, whose modelling functionality the Blender add-ons set out to replace.

## License

As inherited from **ArmAToolbox** and **Arma 3 Object Builder**, **DayZ Object Builder** is released under the GNU General Public License version 3.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see the [GNU licenses](http://www.gnu.org/licenses/).

Files created using this software are not covered by this license.
