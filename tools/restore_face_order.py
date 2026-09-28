"""OBSOLETE - DO NOT RUN. The premise below is wrong and this script damages models.

It was written believing that DayZ pairs hiddenSelectionsTextures with a model's sections
by position, so that the face order in an MLOD is load-bearing. It is not: `binarize`
regroups faces itself, and hiddenSelections resolve by selection NAME.

Measured 15.08.2026 on ak74.p3d. The MLOD coming out of Blender has its 15 material-less
faces at the END, where the binarized original has them at the start. Binarizing that MLOD
still produces exactly the original's 7 sections, material-less faces back in front
(0..13, 13..14, 14..15), every face range matching one for one.

Running this over IMPWMOD reordered 190 models to no purpose. Kept only as a record of a
refuted hypothesis; the write-up is docs/solved/dayz-model-cfg-format-breaks-sections.md
in the AB_Models_SXDIST repo.
"""

raise SystemExit(__doc__)

import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))
from _addon import load_io

odol_reader, p3d, converter = load_io("data_p3d_odol", "data_p3d", "odol_to_mlod")

R = p3d.P3D_LOD_Resolution


def original_pair_order(model):
    """The texture/material pairs of the original's visual LOD 0, in the order they run."""
    for lod in model.lods:
        signature = R.from_float(lod.resolution)
        if signature.lod != R.VISUAL or signature.res != 0:
            continue

        textures, materials = converter.face_materials(lod)
        order = []
        for pair in zip(textures, materials):
            if pair not in order:
                order.append(pair)

        return order

    return None


def reorder(lod, order):
    """Stable sort of a LOD's faces into `order`. Pairs the original does not have keep
    their relative position at the end, rather than being dropped or interleaved."""
    rank = {pair: index for index, pair in enumerate(order)}
    before = [(face[3], face[4]) for face in lod.faces]
    lod.faces.sort(key=lambda face: rank.get((face[3], face[4]), len(rank)))
    after = [(face[3], face[4]) for face in lod.faces]
    return before != after


def main():
    parser = argparse.ArgumentParser(description="Restore original face order in rebuilt models")
    parser.add_argument("original")
    parser.add_argument("rebuilt")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changed = untouched = skipped = 0
    for folder, _, files in os.walk(args.original):
        for name in sorted(files):
            if not name.lower().endswith(".p3d"):
                continue

            relative = os.path.relpath(os.path.join(folder, name), args.original)
            target = os.path.join(args.rebuilt, relative)
            if not os.path.isfile(target):
                skipped += 1
                continue

            with open(os.path.join(folder, name), "rb") as handle:
                order = original_pair_order(odol_reader.ODOL_File.read(handle))

            if not order:
                skipped += 1
                continue

            model = p3d.P3D_MLOD.read_file(target)
            touched = False
            for lod in model.lods:
                if lod.resolution.lod == R.VISUAL and reorder(lod, order):
                    touched = True

            if not touched:
                untouched += 1
                continue

            changed += 1
            if args.apply:
                model.write_file(target)

    print("%s: переупорядочено %d, уже в порядке %d, пропущено %d"
          % ("применено" if args.apply else "dry run", changed, untouched, skipped))


if __name__ == "__main__":
    main()
