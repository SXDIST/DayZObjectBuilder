"""Debinarizes a whole mod: every ODOL .p3d in it becomes an editable MLOD .p3d, and
every folder that needs one gets the model.cfg those models were binarized against.

The model.cfg is the point. Binarizing folds the skeleton, the sections[] array and the
animation classes out of the model.cfg beside the model and into the .p3d itself. Convert
the geometry alone and none of that comes back: the bones, the hidden selections and every
moving part are gone, and the mod does not work. So each output folder is given a
model.cfg rebuilt from what its own models still carry.

Runs on the system Python, not inside Blender - nothing it uses needs bpy.

    python tools/debinarize_mod.py <source> <destination> [options]

      --link          hardlink the files that are not models instead of copying them,
                      which keeps a 1.7 GB texture set from being duplicated on disk.
                      Falls back to copying across volumes. Edits to a hardlinked file
                      are edits to the original, so this is for read-only assets.
      --models-only   convert the models and write the model.cfg files, and copy nothing
      --limit N       stop after N models, for a quick look at the output
      --dry-run       report what would be written without writing it
"""

import os
import sys
import types
import shutil
import argparse
import importlib.util


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "DZObjectBuilder")


# The add-on's io package cannot be imported normally outside Blender: it is named `io`,
# which the standard library already owns, and its __init__ pulls in modules that need
# bpy. Mirror the layout under a synthetic root and load the modules by path, the same
# way tests/_addon.py does.
def load_io(*names):
    root = "dzob_tools_root"
    if root not in sys.modules:
        package = types.ModuleType(root)
        package.__path__ = [ADDON]
        sys.modules[root] = package

        io_package = types.ModuleType(root + ".io")
        io_package.__path__ = [os.path.join(ADDON, "io")]
        sys.modules[root + ".io"] = io_package

    loaded = []
    for name in names:
        full = "%s.io.%s" % (root, name)
        if full not in sys.modules:
            spec = importlib.util.spec_from_file_location(full, os.path.join(ADDON, "io", name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[full] = module
            spec.loader.exec_module(module)

        loaded.append(sys.modules[full])

    return loaded


odol_reader, odol_to_mlod, p3d, mcfg = load_io("data_p3d_odol", "odol_to_mlod", "data_p3d", "mcfg_from_odol")

# The config package is a package rather than a module, so it loads normally once its
# parent is in sys.modules - which load_io has already arranged.


class Report():
    def __init__(self):
        self.converted = 0
        self.already_mlod = 0
        self.copied = 0
        self.linked = 0
        self.model_cfgs = 0
        self.failed_models = []
        self.failed_lods = []
        self.unmatched_axes = []


def relative(path, source):
    return os.path.relpath(path, source)


def transfer(path, destination, report, link, dry_run):
    if dry_run:
        return

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if link:
        try:
            if os.path.exists(destination):
                os.remove(destination)

            os.link(path, destination)
            report.linked += 1
            return
        except OSError:
            pass    # different volume, or the filesystem has no hardlinks

    shutil.copy2(path, destination)
    report.copied += 1


def convert_model(path, destination, source, report, dry_run):
    with open(path, "rb") as file:
        signature = file.read(4)

    if signature == b"MLOD":
        return None                 # already editable, nothing to recover

    with open(path, "rb") as file:
        model = odol_reader.ODOL_File.read(file)

    for index, message in model.failed_lods:
        report.failed_lods.append("%s LOD %d: %s" % (relative(path, source), index, message))

    mlod = odol_to_mlod.convert(model)
    for index, message in mlod.failed_lods:
        report.failed_lods.append("%s LOD %d (convert): %s" % (relative(path, source), index, message))

    if not mlod.lods:
        raise ValueError("no LOD survived conversion")

    if not dry_run:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        mlod.write_file(destination)

    report.converted += 1
    return model


def write_model_cfg(folder, models, report, dry_run):
    # Only the models that lost something to binarizing are worth an entry; a model with
    # no skeleton, no sections and no animations would contribute nothing but defaults.
    entries = [(name, model) for name, model in models if mcfg.is_worth_writing(model)]
    if not entries:
        return

    path = os.path.join(folder, "model.cfg")
    if dry_run:
        report.model_cfgs += 1
        return

    unmatched = mcfg.write_file(entries, path)
    report.unmatched_axes.extend(unmatched)
    report.model_cfgs += 1


def run(source, destination, link, models_only, limit, dry_run):
    report = Report()
    count = 0

    for folder, _, files in os.walk(source):
        models = []
        target_folder = os.path.join(destination, relative(folder, source)) if folder != source else destination

        for name in sorted(files):
            path = os.path.join(folder, name)
            target = os.path.join(target_folder, name)

            if not name.lower().endswith(".p3d"):
                if not models_only:
                    transfer(path, target, report, link, dry_run)

                continue

            if limit and count >= limit:
                continue

            try:
                model = convert_model(path, target, source, report, dry_run)
            except Exception as ex:
                report.failed_models.append("%s: %s: %s" % (relative(path, source), type(ex).__name__, ex))
                continue

            count += 1
            if model is None:
                report.already_mlod += 1
                if not models_only:
                    transfer(path, target, report, link, dry_run)

                continue

            models.append((os.path.splitext(name)[0], model))

        if models:
            if not dry_run:
                os.makedirs(target_folder, exist_ok=True)

            write_model_cfg(target_folder, models, report, dry_run)

        # A folder's models are held only until its model.cfg is written; keeping every
        # parsed model would hold the whole mod's geometry in memory at once.
        models = []

    return report


def main():
    parser = argparse.ArgumentParser(description="Debinarize a mod's models and rebuild their model.cfg files")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--link", action="store_true", help="hardlink non-model files instead of copying")
    parser.add_argument("--models-only", action="store_true", help="convert models only, copy nothing else")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many models")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = os.path.abspath(args.source)
    destination = os.path.abspath(args.destination)
    if not os.path.isdir(source):
        parser.error("source is not a folder: %s" % source)

    # Writing inside the source would have the walk find its own output. Different
    # drives cannot be compared with commonpath at all, and cannot nest either.
    try:
        nested = os.path.commonpath([source, destination]) == source
    except ValueError:
        nested = False

    if nested:
        parser.error("destination is inside the source folder")

    report = run(source, destination, args.link, args.models_only, args.limit, args.dry_run)

    print("models converted : %d" % report.converted)
    print("already editable : %d" % report.already_mlod)
    print("model.cfg written: %d" % report.model_cfgs)
    print("files copied     : %d" % report.copied)
    print("files hardlinked : %d" % report.linked)

    if report.failed_models:
        print("\nmodels that failed (%d):" % len(report.failed_models))
        for item in report.failed_models:
            print("   %s" % item)

    if report.failed_lods:
        print("\nLODs that failed (%d):" % len(report.failed_lods))
        for item in report.failed_lods:
            print("   %s" % item)

    if report.unmatched_axes:
        print("\nanimations whose axis could not be matched to a Memory LOD selection (%d)."
              % len(report.unmatched_axes))
        print("they are written without an axis, which is what the binarized model itself does:")
        for item in report.unmatched_axes:
            print("   %s" % item)

    return 1 if report.failed_models else 0


if __name__ == "__main__":
    sys.exit(main())
