"""Drives tools/generate_lods.py over a whole mod, surviving Blender crashing.

Blender 5.1 can die outright - not raise, die - inside mesh_normals_corner_custom_set
while the importer applies a model's custom normals. One such model would otherwise end
the run wherever it happened to be, which on this corpus was model 70 of 505.

So the work is driven from outside the process: run Blender, watch how far it got, and on
a crash restart past the model that killed it. Anything skipped that way is retried at the
end with custom normals turned off, which is what actually crashes; a model recovered on
that second pass keeps its geometry and selections but gets recomputed shading.

Runs on the system Python:

    python tools/generate_lods_batch.py <blender.exe> <source> <destination> [--ratios ...]
"""

import os
import re
import sys
import time
import argparse
import subprocess


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "generate_lods.py")


def run_blender(blender, source, destination, extra):
    command = [blender, "--background", "--factory-startup", "--python", SCRIPT, "--",
               source, destination] + extra
    process = subprocess.run(command, capture_output=True, text=True, errors="replace")
    return process.stdout or ""


def list_models(blender, source, destination):
    output = run_blender(blender, source, destination, ["--list"])
    return re.findall(r"^LODGEN LIST (.+)$", output, re.MULTILINE)


def processed_in(output):
    done = re.findall(r"^LODGEN (?:OK \d+/\d+|SKIP) (.+?)(?::.*)?$", output, re.MULTILINE)
    return [item.strip() for item in done]


def main():
    parser = argparse.ArgumentParser(description="Generate resolution LODs across a mod, crash-tolerant")
    parser.add_argument("blender")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--ratios", default=None)
    args = parser.parse_args()

    extra_common = ["--ratios", args.ratios] if args.ratios else []

    models = list_models(args.blender, args.source, args.destination)
    if not models:
        raise SystemExit("no models found under %s" % args.source)

    print("%d models to process" % len(models), flush=True)

    index = 0
    crashed = []
    completed = 0
    started = time.time()

    while index < len(models):
        output = run_blender(args.blender, args.source, args.destination,
                             ["--skip", str(index)] + extra_common)
        done = processed_in(output)
        completed += len(done)

        if "LODGEN done" in output:
            index = len(models)
            break

        # Blender died. Everything it reported is finished; the next one is what killed it.
        index += len(done)
        if index < len(models):
            print("CRASH on %s (after %d done) - skipping it" % (models[index], completed), flush=True)
            crashed.append(models[index])
            index += 1

    print("first pass: %d done, %d crashed, %.1f min"
          % (completed, len(crashed), (time.time() - started) / 60), flush=True)

    recovered = []
    for relative in crashed:
        target = os.path.join(args.destination, relative)
        run_blender(args.blender,
                    os.path.join(args.source, relative),
                    target,
                    ["--no-normals"] + extra_common)
        if os.path.isfile(target):
            recovered.append(relative)
            print("RECOVERED without custom normals: %s" % relative, flush=True)
        else:
            print("STILL FAILING: %s" % relative, flush=True)

    print("\ntotal: %d generated, %d recovered without custom normals, %d unrecoverable, %.1f min"
          % (completed, len(recovered), len(crashed) - len(recovered), (time.time() - started) / 60))
    for relative in crashed:
        if relative not in recovered:
            print("   unrecoverable: %s" % relative)


if __name__ == "__main__":
    main()
