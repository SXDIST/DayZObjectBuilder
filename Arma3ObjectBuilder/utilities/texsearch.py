#  Texture set auto-search engine.
#
# Pure logic (no bpy dependency) so it stays fast and unit testable. Given a base
# texture name (taken from a material's Base Color image node) and an indexed mod
# folder, it resolves the matching face texture (_co) and the bound RVMAT.
#
# The RVMAT is the only reliable link between a color texture and a normal map that
# was named differently, so RVMAT resolution prioritizes files that actually
# reference the found texture over a naive basename match.


import os
import re

from . import data


# Known Arma texture suffixes, derived from the shared enum so we never duplicate
# the list. Sorted by length descending so longer suffixes win during matching
# (e.g. "_nohq" before "_no", "_dtsmdi" before "_dt").
TEXTURE_SUFFIXES = sorted(
    (item[0].lower() for item in data.enum_texture_types),
    key=len,
    reverse=True
)

# Suffixes that mark a face/color texture (the value stored in texture_path).
COLOR_SUFFIXES = ("co", "ca")

# Non-Arma diffuse/source suffixes (Witcher, generic PBR exports, etc.). A shader
# may reference "stovebig_d" while the exported Arma set is "stovebig_co" — stripping
# these recovers the shared set basename "stovebig". Sorted longest-first.
FOREIGN_SUFFIXES = sorted(
    ("d", "diff", "diffuse", "basecolor", "basecol", "bc", "albedo", "alb", "color", "col"),
    key=len,
    reverse=True
)

PAA_EXTENSION = ".paa"
SOURCE_EXTENSIONS = (".png", ".tga", ".tif", ".tiff")

RE_RVMAT_TEXTURE = re.compile(r"\"([^\"]+\.paa)\"", re.IGNORECASE)


# Windows MAX_PATH (260) workaround. RVMATs are walked from deeply nested game asset trees, which
# routinely exceed the limit; without the "\\?\" extended-length prefix open() raises and the file
# is silently skipped, corrupting texture resolution. Kept inline (instead of utilities.generic) so
# this module stays free of the bpy import and remains unit testable. See generic.long_path.
def _long_path(path):
    if os.name != "nt":
        return path

    if path.startswith("\\\\?\\"):
        return path

    normalized = os.path.abspath(path)
    if normalized.startswith("\\\\"):
        return "\\\\?\\UNC\\" + normalized[2:]

    return "\\\\?\\" + normalized


def split_suffix(stem):
    """Split a file stem into (basename, suffix). Suffix is None if unrecognized.

    "myhouse_co" -> ("myhouse", "co"); "shared_nohq" -> ("shared", "nohq");
    "plain" -> ("plain", None).
    """
    stem = stem.lower()
    for suffix in TEXTURE_SUFFIXES:
        tail = "_" + suffix
        if stem.endswith(tail) and len(stem) > len(tail):
            return stem[:-len(tail)], suffix

    return stem, None


def strip_foreign_suffix(stem):
    """Strip a non-Arma diffuse/source suffix (_d, _diff, _albedo, ...) if present.

    Returns the basename without the suffix, or None if the stem has none. Used to
    bridge a foreign-named shader texture to an Arma-named set on disk.
    """
    stem = stem.lower()
    for suffix in FOREIGN_SUFFIXES:
        tail = "_" + suffix
        if stem.endswith(tail) and len(stem) > len(tail):
            return stem[:-len(tail)]

    return None


def file_stem(path):
    # Normalize backslashes first: RVMAT paths use the Arma "\" convention, which
    # os.path.basename does not split on non-Windows platforms.
    path = path.replace("\\", "/")
    return os.path.splitext(os.path.basename(path))[0].lower()


def parse_rvmat_textures(filepath):
    """Return the set of referenced texture stems (lowercased, no dir/ext) in an RVMAT."""
    result = set()
    try:
        with open(_long_path(filepath), encoding="utf-8", errors="ignore") as file:
            content = file.read()
    except OSError:
        return result

    for match in RE_RVMAT_TEXTURE.finditer(content):
        result.add(file_stem(match.group(1)))

    return result


class ResolveResult:
    __slots__ = ("texture_path", "material_path", "status", "ambiguous", "rvmat_candidates")

    def __init__(self, texture_path=None, material_path=None, status='MISSING', ambiguous=False, rvmat_candidates=None):
        self.texture_path = texture_path
        self.material_path = material_path
        self.status = status  # 'FOUND' | 'PARTIAL' | 'MISSING'
        self.ambiguous = ambiguous
        self.rvmat_candidates = rvmat_candidates or []


class TextureIndex:
    """An index of the texture (.paa) and material (.rvmat) files under a mod folder."""

    def __init__(self, root, include_sources=False):
        self.root = root
        self.include_sources = include_sources

        # base -> { suffix(or "") -> abspath } for color/normal/etc. lookup by set.
        self.paa_by_base = {}
        # exact stem -> abspath for direct hits.
        self.paa_by_stem = {}
        # rvmat stem -> abspath for the basename fallback.
        self.rvmat_by_stem = {}
        # referenced texture stem -> [rvmat abspath, ...] for content-based lookup.
        self.reverse_index = {}
        # rvmat abspath -> set of referenced texture stems, for ranking candidates.
        self.rvmat_refs = {}

        self._build()

    def _build(self):
        texture_exts = {PAA_EXTENSION}
        if self.include_sources:
            texture_exts.update(SOURCE_EXTENSIONS)

        for dirpath, _, filenames in os.walk(self.root):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                fullpath = os.path.join(dirpath, name)
                stem = os.path.splitext(name)[0].lower()

                if ext in texture_exts:
                    # Prefer .paa over source images when both exist for the same stem.
                    if ext == PAA_EXTENSION or stem not in self.paa_by_stem:
                        self.paa_by_stem[stem] = fullpath

                    base, suffix = split_suffix(stem)
                    bucket = self.paa_by_base.setdefault(base, {})
                    key = suffix or ""
                    if ext == PAA_EXTENSION or key not in bucket:
                        bucket[key] = fullpath

                elif ext == ".rvmat":
                    self.rvmat_by_stem.setdefault(stem, fullpath)
                    refs = parse_rvmat_textures(fullpath)
                    self.rvmat_refs[fullpath] = refs
                    for ref in refs:
                        self.reverse_index.setdefault(ref, []).append(fullpath)


def _rank_rvmats(index, candidates, color_base, normal_stem, color_path):
    """Pick the best RVMAT from candidates and report whether the choice was ambiguous.

    Scoring (most to least important):
      - references the exact normal map from the shader,
      - references more textures that share the color's basename (a dedicated
        material references co+nohq+smdi of the same set; a generic one does not),
      - lives in the same folder as the color texture,
      - shorter path.

    The same-basename score is what makes this robust when the shader's normal is
    named "_n" (source) while the RVMAT references "_nohq" (compiled): both still
    share the set basename, so the dedicated material outscores a generic one.
    """
    unique = list(dict.fromkeys(candidates))
    if not unique:
        return None, False
    if len(unique) == 1:
        return unique[0], False

    color_dir = os.path.dirname(color_path).lower() if color_path else None

    def score(path):
        refs = index.rvmat_refs.get(path, set())
        exact_normal = 1 if normal_stem and normal_stem in refs else 0
        same_base = sum(1 for ref in refs if split_suffix(ref)[0] == color_base)
        same_dir = 0 if color_dir and os.path.dirname(path).lower() == color_dir else 1
        return (-exact_normal, -same_base, same_dir, len(path), path.lower())

    ranked = sorted(unique, key=score)
    best, runner_up = ranked[0], ranked[1]

    # Ambiguous only when we could not distinguish beyond the shared color: no exact
    # normal match and at most the color itself shared with the runner-up.
    best_score = score(best)
    ambiguous = best_score[0] == 0 and best_score[1] >= -1 and score(runner_up)[:2] == best_score[:2]

    return best, ambiguous


def resolve(index, image_name, normal_name=None):
    """Resolve a texture set from a color image name (and optional normal) against an index.

    The normal map is the key disambiguator: when a color texture is tiled across
    many materials, only the RVMAT that references BOTH the color and this exact
    normal is the right one. Candidates are ranked in tiers:
      1. references both the color and the normal,
      2. references the color,
      3. references any sibling of the set (suffix-derived),
      4. an RVMAT named after the texture set (basename fallback).

    Returns a ResolveResult with absolute texture_path / material_path (or None).
    """
    stem = file_stem(image_name)
    base, suffix = split_suffix(stem)

    # Bridge a foreign-named diffuse (e.g. "stovebig_d") to the Arma set basename
    # ("stovebig"), but only when that basename actually has files in the index.
    if suffix is None:
        foreign_base = strip_foreign_suffix(stem)
        if foreign_base and foreign_base != base and (foreign_base in index.paa_by_base or foreign_base in index.rvmat_by_stem):
            base = foreign_base

    # --- Color texture ---
    bucket = index.paa_by_base.get(base, {})
    color_path = bucket.get("co") or bucket.get("ca")
    if not color_path:
        # The node itself may already be the color map, or an exact-name paa exists.
        color_path = index.paa_by_stem.get(stem)

    color_stem = file_stem(color_path) if color_path else stem
    color_base, _ = split_suffix(color_stem)
    normal_stem = file_stem(normal_name) if normal_name else None

    refs_color = index.reverse_index.get(color_stem, [])
    refs_set = set(refs_color)

    material_path = None
    ambiguous = False

    # Tier 1: an RVMAT named exactly after the texture set. This is the Arma
    # convention (foo_co/foo_nohq/foo_smdi -> foo.rvmat) and the strongest, most
    # intuitive signal — it beats content matching, which can't tell apart two
    # RVMATs that reference the same texture set (e.g. a duplicate "plain_wood").
    named = index.rvmat_by_stem.get(color_base) or index.rvmat_by_stem.get(base)
    if named and (not refs_color or named in refs_set):
        material_path = named

    # Tier 2: RVMATs that reference the color, ranked so the dedicated material
    # (matching normal / sharing the set basename) wins over a generic one.
    if not material_path and refs_color:
        material_path, ambiguous = _rank_rvmats(index, refs_color, color_base, normal_stem, color_path)

    # Tier 3: the color itself isn't referenced anywhere, but a set sibling is.
    if not material_path:
        sibling = []
        for sibling_path in bucket.values():
            sibling.extend(index.reverse_index.get(file_stem(sibling_path), []))
        if sibling:
            material_path, ambiguous = _rank_rvmats(index, sibling, color_base, normal_stem, color_path)

    # Tier 4: the named RVMAT even if it does not reference the color (last resort).
    if not material_path and named:
        material_path = named

    # --- Status ---
    if color_path and material_path:
        status = 'FOUND'
    elif color_path or material_path:
        status = 'PARTIAL'
    else:
        status = 'MISSING'

    candidates = list(dict.fromkeys(refs_color))

    return ResolveResult(
        texture_path=color_path,
        material_path=material_path,
        status=status,
        ambiguous=ambiguous,
        rvmat_candidates=candidates
    )


# --- Module-level index cache (keyed by absolute mod root) ---

_index_cache = {}


def get_index(root, include_sources=False, rebuild=False):
    """Get a cached TextureIndex for the mod root, building it on demand."""
    key = os.path.normcase(os.path.abspath(root))
    if rebuild:
        _index_cache.pop(key, None)

    index = _index_cache.get(key)
    if index is None or index.include_sources != include_sources:
        index = TextureIndex(root, include_sources)
        _index_cache[key] = index

    return index


def clear_cache(root=None):
    """Invalidate the whole cache, or just one mod root."""
    if root is None:
        _index_cache.clear()
    else:
        _index_cache.pop(os.path.normcase(os.path.abspath(root)), None)
