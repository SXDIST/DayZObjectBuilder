# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single Blender add-on living in `DZObjectBuilder/` — **DayZ Object Builder** (DZOB), a DayZ-focused
fork of [Arma 3 Object Builder](https://github.com/MrClock8163/Arma3ObjectBuilder) by MrClock. It reads
and writes the Bohemia Interactive / Enfusion content formats (`.p3d` MLOD and binarized ODOL, `.xob`,
`.anm`, `.paa`, `.asc`, `model.cfg`, Terrain Builder object lists) and adds the editing tools around them.

The repository root holds only the add-on folder, tests, docs and CI. There is no build system, no
package manager, no linter config — the add-on is shipped as a zip of `DZObjectBuilder/`.

## Commands

### Tests

Two kinds, split by whether they need Blender:

```sh
# Pure-logic suites — plain Python, no Blender. Run from the repo root (they resolve
# ./DZObjectBuilder relative to cwd).
python tests/odol.py         # ODOL binary layout
python tests/compression.py  # LZO / LZSS decompression
python tests/texsearch.py    # texture + RVMAT auto-search

# Suites that drive the operators — need Blender with the add-on installed and enabled.
blender -b -noaudio --python tests/p3d.py
blender -b -noaudio --python tests/mcfg.py
```

Run a single test case with the usual unittest argument, e.g. `python tests/odol.py TestClass.test_name`.

`tests/_addon.py` exists because the add-on's IO package is literally named `io`, which the standard
library already owns in `sys.modules`, and `io/__init__.py` imports `bpy`. It mirrors the package layout
under a synthetic root and loads single modules by path. Any new Blender-free test of an `io` module must
go through `load_io(...)`; `tests/texsearch.py` does the same trick for `utilities`.

`tests/odol.py` verifies layout guarantees against real DayZ models whose paths are constants at the top
of the file (`P:\DZ\...`). **Those are Bohemia's game files and must never be committed to this GPL-3
repository.** Without a local corpus the affected tests skip and the run prints a loud banner listing
exactly which guarantees went unverified — a green run with that banner is *not* a verified run.

`requirements.txt` pins `fake-bpy-module` only, for editor completion and static checking. It is not
needed to run anything.

### Releasing

`.github/workflows/release.yml` fires on push to `master` touching `DZObjectBuilder/**`. It reads
`version` from `DZObjectBuilder/blender_manifest.toml`, and if the tag `v<version>` does not exist yet it
zips the add-on folder, publishes a GitHub Release (notes written by Claude Code from the commit range,
falling back to GitHub's auto-notes), then uploads the same zip to extensions.blender.org.

**Bumping a version means editing two files in sync:** `version` in `blender_manifest.toml` (which drives
the tag) and `bl_info["version"]` in `DZObjectBuilder/__init__.py`.

## Architecture

Four layers, imported in dependency order by `DZObjectBuilder/__init__.py`:

- **`io/`** — file formats. `data_*.py` are pure readers/writers of the on-disk structures, built on
  `binary_handler.py` (BI scalar types) and `compression.py` (LZO1X / LZSS). `import_*.py` / `export_*.py`
  translate between those structures and Blender data. No UI, no operators.
- **`utilities/`** — Blender-side helpers with no operator classes: mass, proxies, flags, LOD naming,
  validation, rigging, texture search, and `lodgen/` (the merged LOD generator, one module per LOD type).
- **`props/`** — `PropertyGroup` definitions registered onto `bpy.types.Object` / `Scene` / `Material`.
- **`ui/`** — every `Operator`, `Panel`, `Menu` and `UIList`. One module per feature; each exposes a
  `classes` tuple plus `register()` / `unregister()`.

`P3D_MLOD` (in `io/data_p3d.py`) is the single in-memory model. Everything upstream of the importer
converts into it, so there is exactly one import path for geometry. Binarized input is detected by the
4-byte signature in `import_p3d.read_file`: `MLOD` parses directly, anything else goes through
`data_p3d_odol.py` → `odol_to_mlod.convert()` and lands as the same `P3D_MLOD`. That conversion is lossy
and one-way — **the add-on never writes ODOL.** The four geometry transforms in `odol_to_mlod.py` (vertex
frame, normal sign, winding, UV flip) were each settled by measurement against the DayZ v54 corpus and
are documented in the module header with the evidence; do not "fix" them from first principles.

### Registration

Adding a module means touching **three** places:

1. The package's `__init__.py` — both the `if "x" in locals(): reload(x)` block at the top *and* the
   `from . import x` below it. The reload block is what makes editing the add-on live in Blender work;
   omitting an entry there produces stale-module bugs that look like nothing changed.
2. `modules` in `DZObjectBuilder/__init__.py`, if the module has `register()` / `unregister()`. Order
   matters: `props` before `ui`, and unregistration walks the list in reverse.
3. Its own `classes` tuple, for `ui/` and `props/` modules.

### Naming — the one hard constraint

**`.blend` custom-property identifiers stay on the upstream `a3ob_*` names** (`a3ob_properties_object`,
`a3ob_outliner`, `a3ob_rigging`, …). Renaming them silently drops model metadata from existing files.
This is also why DZOB and Arma 3 Object Builder cannot be enabled at the same time — same identifiers.

Everything else is in the DZOB namespace:

- operator / panel `bl_idname`: `dzob.*` (all 100 of them; no `a3ob.` remains)
- classes: `DZOB_OT_`, `DZOB_OP_` (import/export operators), `DZOB_PT_`, `DZOB_MT_`, `DZOB_PG_`,
  `DZOB_UL_`, `DZOB_FH_`
- format-level classes in `io/` are named after the format, not the add-on: `P3D_LOD`, `ODOL_*`, `XOB_*`,
  `PAA_*`, `TBCSV_*`

The merged LOD generator is new in this fork and has no upstream compatibility burden, so its scene
properties do use the fork prefix: `bpy.types.Scene.dzob_resolution_lods`, `dzob_geometry_lod`, etc.

### Conventions to follow

**Windows long paths.** Never call bare `open()` or pass a raw path to an `os` call that touches the
filesystem. Use `utilities.generic.open_long()` / `long_path()`, which opt into the `\\?\` extended-length
syntax. Unpacked game asset trees routinely exceed `MAX_PATH`, and export makes it worse by appending a
`.temp` suffix.

**Operators report, never raise.** Import/export `execute()` wraps the work in `try/except`, calls
`traceback.print_exc()` and returns `{'CANCELLED'}` after `utils.op_report(self, {'ERROR'}, ...)`. The
traceback goes to the system console; the user gets an operator error, not a Blender crash popup.

**Blender version floor is 4.4.0**, because `.anm` import/export is built on the slotted action API
(`fcurve_ensure_for_datablock`). `utilities/compat.py` and scattered `bpy.app.version >= (x, y, z)` guards
still carry upstream's compatibility shims for much older releases; leave them, but do not treat them as
a reason to support anything below 4.4.

**Attribution stays.** GPL-3, the credits chain (ArmAToolbox → Arma 3 Object Builder → DZOB) in
`README.md` and `DZObjectBuilder/data/CREDITS.md`, and the upstream GitBook `doc_url` in `bl_info` are all
deliberate. `DZObjectBuilder/data/dayz_master_rig.blend` is force-tracked past the `*.blend*` ignore rule.

**DayZ Tools integration** is optional and Windows-only: the install path comes from the add-on
preferences (auto-detected via `HKCU\software\bohemia interactive\dayz tools`), and binarized `model.cfg`
is handled by shelling out to `Bin/CfgConvert/CfgConvert.exe`. Code must degrade to a reported error when
it is absent, not assume it.

Longer design notes for two non-obvious algorithms live in `docs/`: `hitpoint_generation.md` and
`vmass_distribution.md`.
