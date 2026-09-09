"""Generates the resolution LOD stack for every model in a mod, headless.

Most mod models ship with a single visual LOD, so the engine draws full detail at every
distance. This walks a folder, and for each .p3d duplicates its visual LOD once per
decimate ratio, leaving the original as resolution 0 and the decimated copies as 1..N.

Runs inside Blender, driving the add-on's own P3D import and export:

    blender --background --factory-startup --python tools/generate_lods.py -- \
        <source> <destination> [--ratios 0.8,0.6,0.4,0.2] [--limit N] [--skip N]

Everything the model already carries - Geometry, Memory, View and Fire LODs, proxies,
named selections, sections, LOD properties - passes through untouched: the decimation
only ever touches copies of the visual LOD. Models that already have more than one
visual LOD are left alone rather than having a second stack piled on top.
"""

import os
import sys
import time
import bpy
import addon_utils


# The add-on's Tris preset, which is what this mod's models are authored against.
DEFAULT_RATIOS = (0.80, 0.60, 0.40, 0.20)

LOD_RESOLUTION = '0'


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("usage: ... -- <source> <destination> [--ratios a,b,c] [--limit N] [--skip N]")

    options = {
        "source": argv[0],
        "destination": argv[1],
        "ratios": DEFAULT_RATIOS,
        "limit": 0,
        "skip": 0,
        "normals": True,
        "list": False,
    }

    index = 2
    while index < len(argv):
        flag = argv[index]
        if flag == "--no-normals":
            options["normals"] = False
            index += 1
            continue

        if flag == "--list":
            options["list"] = True
            index += 1
            continue

        value = argv[index + 1]
        if flag == "--ratios":
            options["ratios"] = tuple(float(item) for item in value.split(","))
        elif flag == "--limit":
            options["limit"] = int(value)
        elif flag == "--skip":
            options["skip"] = int(value)
        else:
            raise SystemExit("unknown flag: %s" % flag)

        index += 2

    return options


# The add-on's live proxy preview runs off a depsgraph handler that assumes a UI is
# there; headless it raises on every scene update and buries the real output. Nothing
# in this script needs it.
def silence_ui_handlers():
    for handler in list(bpy.app.handlers.depsgraph_update_post):
        if "proxies" in getattr(handler, "__module__", ""):
            bpy.app.handlers.depsgraph_update_post.remove(handler)


# read_factory_settings would disable the add-on, so the scene is emptied by hand.
def clear_scene():
    for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.materials,
                       bpy.data.collections, bpy.data.images, bpy.data.armatures):
        for item in list(collection):
            collection.remove(item)


def visual_lods():
    output = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue

        properties = obj.a3ob_properties_object
        if properties.is_a3_lod and properties.lod == LOD_RESOLUTION:
            output.append(obj)

    return output


# One decimated copy per ratio. Children come along: an imported proxy is its own object
# parented to the LOD mesh, which is what keeps the decimation off the proxy triangles
# and what puts a full set of attachment points on every LOD.
def add_lod(context, source, ratio, resolution):
    copy = source.copy()
    copy.data = source.data.copy()
    context.collection.objects.link(copy)

    for child in source.children:
        child_copy = child.copy()
        if child_copy.data:
            child_copy.data = child_copy.data.copy()

        context.collection.objects.link(child_copy)
        child_copy.parent = copy
        child_copy.matrix_parent_inverse = copy.matrix_world.inverted()

    copy.name = "%s_lod%d" % (source.name, resolution)
    copy.data.name = copy.name

    decimate = copy.modifiers.new(name="Decimate", type='DECIMATE')
    decimate.ratio = ratio
    decimate.use_collapse_triangulate = True

    weighted = copy.modifiers.new(name="WeightedNormal", type='WEIGHTED_NORMAL')
    weighted.use_face_influence = True
    weighted.keep_sharp = True

    copy.a3ob_properties_object.is_a3_lod = True
    copy.a3ob_properties_object.lod = LOD_RESOLUTION
    copy.a3ob_properties_object.resolution = resolution

    return copy


# Everything the importer can carry over, minus the custom normals when they are the
# thing that kills the process: Blender 5.1 can crash inside mesh_normals_corner_custom_set
# on some models, taking the whole run with it, and the add-on's own UI flags that option
# as unreliable. Dropping it costs the authored shading on that one model - the exporter
# writes recomputed normals instead - and is only ever used as the retry.
# FLAGS matters as much as the geometry: a vertex flag carries the texture clamp and
# lighting modes, and importing without them exports every vertex as flag 0 - which looks
# correct in Buldozer and wrong in game.
DATA_WITH_NORMALS = {'NORMALS', 'FLAGS', 'PROPS', 'MASS', 'SELECTIONS', 'UV', 'MATERIALS'}
DATA_WITHOUT_NORMALS = {'FLAGS', 'PROPS', 'MASS', 'SELECTIONS', 'UV', 'MATERIALS'}


def process(path, destination, ratios, normals = True):
    clear_scene()

    bpy.ops.dzob.import_p3d(
        filepath=path,
        absolute_paths=False,
        proxy_action='SEPARATE',
        validate_meshes=False,
        translate_selections=False,
        pascalcase_selections=False,
        cleanup_empty_selections=False,
        sections='PRESERVE',
        additional_data_allowed=True,
        additional_data=DATA_WITH_NORMALS if normals else DATA_WITHOUT_NORMALS,
    )

    existing = visual_lods()
    if not existing:
        return "no visual LOD"

    if len(existing) > 1:
        return "already has %d visual LODs" % len(existing)

    source = existing[0]
    source.a3ob_properties_object.resolution = 0
    for index, ratio in enumerate(ratios):
        add_lod(bpy.context, source, ratio, index + 1)

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    bpy.ops.dzob.export_p3d(
        filepath=destination,
        use_selection=False,
        visible_only=False,
        apply_transforms=True,
        apply_modifiers=True,
        preserve_normals=True,
        validate_meshes=False,
        validate_lods=False,
        sort_sections=False,
        renumber_components=False,
        force_lowercase=False,
        translate_selections=False,
        generate_components=False,
        normalize_weights=False,
        relative_paths=True,
    )

    return None


# Passing an empty NORMALS flag through bpy.ops does not reliably stop the importer from
# applying custom normals - a model that crashes with them still crashed with the flag
# cleared, in the same mesh_normals_corner_custom_set frame. So the call is removed at the
# source instead, by replacing the importer's own function.
def disable_custom_normals():
    import importlib

    module = importlib.import_module("DZObjectBuilder.io.import_p3d")
    module.process_normals = lambda mesh, lod: False
    print("LODGEN custom normals disabled at the importer", flush=True)


def main():
    options = parse_args()
    addon_utils.enable("DZObjectBuilder", default_set=True, persistent=True)
    silence_ui_handlers()

    if not options["normals"]:
        disable_custom_normals()

    source_root = os.path.abspath(options["source"])
    destination_root = os.path.abspath(options["destination"])

    # A single .p3d is accepted as the source, which is how the batch driver retries one
    # model without touching the rest of its folder. The destination is then the file.
    single = os.path.isfile(source_root)
    if single:
        models = [source_root]
        source_root = os.path.dirname(source_root)
    else:
        models = []
        for folder, _, files in os.walk(source_root):
            for name in sorted(files):
                if name.lower().endswith(".p3d"):
                    models.append(os.path.join(folder, name))

    models.sort()

    # The driver needs the same ordering this script walks in, so it asks for it rather
    # than reimplementing the walk and hoping the two agree.
    if options["list"]:
        for path in models:
            print("LODGEN LIST %s" % os.path.relpath(path, source_root), flush=True)

        return

    models = models[options["skip"]:]
    if options["limit"]:
        models = models[:options["limit"]]

    print("LODGEN start: %d models, ratios %s, normals %s"
          % (len(models), options["ratios"], options["normals"]), flush=True)

    done = skipped = failed = 0
    started = time.time()
    for index, path in enumerate(models):
        relative = os.path.relpath(path, source_root)
        destination = destination_root if single else os.path.join(destination_root, relative)
        try:
            note = process(path, destination, options["ratios"], options["normals"])
        except Exception as ex:
            failed += 1
            print("LODGEN FAIL %s: %s: %s" % (relative, type(ex).__name__, ex), flush=True)
            continue

        if note:
            skipped += 1
            print("LODGEN SKIP %s: %s" % (relative, note), flush=True)
            continue

        done += 1
        print("LODGEN OK %d/%d %s" % (index + 1, len(models), relative), flush=True)

    print("LODGEN done: %d generated, %d skipped, %d failed, %.1f min"
          % (done, skipped, failed, (time.time() - started) / 60), flush=True)


if __name__ == "__main__":
    main()
