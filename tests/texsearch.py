"""
Unit tests for the texture set auto-search engine.

Pure logic, so it runs without Blender:
    python tests/texsearch.py

(also works under: blender -b -noaudio --python tests/texsearch.py)
"""


import os
import sys
import types
import tempfile
import unittest
import importlib.util


# Load the engine and its data dependency standalone, without triggering the
# add-on's __init__.py (which imports bpy). We mirror the package layout with a
# synthetic root (carrying `addon_dir`, which data.py reads via "from .. import")
# and a "utilities" subpackage so the relative imports resolve.
_ROOT = "a3ob_texsearch_test_root"
_ADDON_DIR = os.path.join(os.getcwd(), "Arma3ObjectBuilder")
_UTIL_DIR = os.path.join(_ADDON_DIR, "utilities")


def _load_engine():
    root = types.ModuleType(_ROOT)
    root.__path__ = [_ADDON_DIR]
    root.addon_dir = _ADDON_DIR
    sys.modules[_ROOT] = root

    util = types.ModuleType(_ROOT + ".utilities")
    util.__path__ = [_UTIL_DIR]
    sys.modules[_ROOT + ".utilities"] = util

    def load(name):
        spec = importlib.util.spec_from_file_location("%s.utilities.%s" % (_ROOT, name), os.path.join(_UTIL_DIR, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    load("data")
    return load("texsearch")


texsearch = _load_engine()


def _write(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as file:
        file.write(content)


def _rvmat(*texture_paths):
    stages = "\n".join('class Stage%d { texture="%s"; };' % (i, p) for i, p in enumerate(texture_paths))
    return "ambient[]={1,1,1,1};\n" + stages + "\n"


class SplitSuffixTest(unittest.TestCase):
    def test_known_suffixes(self):
        self.assertEqual(texsearch.split_suffix("myhouse_co"), ("myhouse", "co"))
        self.assertEqual(texsearch.split_suffix("shared_nohq"), ("shared", "nohq"))
        self.assertEqual(texsearch.split_suffix("wall_smdi"), ("wall", "smdi"))

    def test_longest_suffix_wins(self):
        # "_nohq" must win over "_no", "_smdi" over "_sm".
        self.assertEqual(texsearch.split_suffix("a_nohq"), ("a", "nohq"))
        self.assertEqual(texsearch.split_suffix("a_smdi"), ("a", "smdi"))

    def test_no_suffix(self):
        self.assertEqual(texsearch.split_suffix("plain"), ("plain", None))


class ParseRvmatTest(unittest.TestCase):
    def test_extracts_texture_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.rvmat")
            _write(path, _rvmat("z\\mod\\data\\wall_co.paa", "z\\mod\\data\\generic_nohq.paa"))
            refs = texsearch.parse_rvmat_textures(path)
            self.assertIn("wall_co", refs)
            self.assertIn("generic_nohq", refs)


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name

        # Case A: everything shares the basename.
        _write(os.path.join(root, "data", "myhouse_co.paa"))
        _write(os.path.join(root, "data", "myhouse_nohq.paa"))
        _write(os.path.join(root, "data", "myhouse.rvmat"),
               _rvmat("data\\myhouse_co.paa", "data\\myhouse_nohq.paa"))

        # Case B: normal named differently AND rvmat named differently -> only the
        # rvmat content links them, so basename fallback would miss it.
        _write(os.path.join(root, "tex", "wall_co.paa"))
        _write(os.path.join(root, "tex", "shared_generic_nohq.paa"))
        _write(os.path.join(root, "mat", "building.rvmat"),
               _rvmat("tex\\wall_co.paa", "tex\\shared_generic_nohq.paa"))

        # Case C: texture only, no rvmat.
        _write(os.path.join(root, "lonely_co.paa"))

        # Case D: a tiled color shared by several RVMATs, disambiguated only by the
        # actual normal map (named "_n", a non-standard suffix). The basename/length
        # tie-break would pick the wrong "generic" one without the normal.
        _write(os.path.join(root, "tile", "floor_co.paa"))
        _write(os.path.join(root, "tile", "floor_n.paa"))
        _write(os.path.join(root, "tile", "floor_other_n.paa"))
        _write(os.path.join(root, "tile", "generic.rvmat"),
               _rvmat("tile\\floor_co.paa", "tile\\floor_other_n.paa"))
        _write(os.path.join(root, "tile", "floor_proper.rvmat"),
               _rvmat("tile\\floor_co.paa", "tile\\floor_n.paa"))

        # Case E: shader normal is the source "_n" but the RVMAT references the
        # compiled "_nohq" — exact-name matching fails, so the set-basename score
        # must carry it (oak_mat references two "oak_*" textures, generic only one).
        _write(os.path.join(root, "oak", "oak_co.paa"))
        _write(os.path.join(root, "oak", "oak_nohq.paa"))
        _write(os.path.join(root, "oak", "unrelated_nohq.paa"))
        _write(os.path.join(root, "oak", "generic2.rvmat"),
               _rvmat("oak\\oak_co.paa", "oak\\unrelated_nohq.paa"))
        _write(os.path.join(root, "oak", "oak_mat.rvmat"),
               _rvmat("oak\\oak_co.paa", "oak\\oak_nohq.paa"))

        # Case F: two RVMATs reference the SAME texture set; one is named after the
        # set ("mahogany.rvmat"), the other is a shorter-named duplicate ("mix.rvmat")
        # that would win the content tie-break. The name match must take priority.
        _write(os.path.join(root, "deck", "mahogany_co.paa"))
        _write(os.path.join(root, "deck", "mahogany_nohq.paa"))
        _write(os.path.join(root, "deck", "mahogany_smdi.paa"))
        same_set = ("deck\\mahogany_co.paa", "deck\\mahogany_nohq.paa", "deck\\mahogany_smdi.paa")
        _write(os.path.join(root, "deck", "mix.rvmat"), _rvmat(*same_set))
        _write(os.path.join(root, "deck", "mahogany.rvmat"), _rvmat(*same_set))

        # Case G: shader uses a foreign diffuse suffix "_d" (Witcher) while the
        # exported Arma set is "_co". The base must bridge "barrel_d" -> "barrel".
        _write(os.path.join(root, "props", "barrel_co.paa"))
        _write(os.path.join(root, "props", "barrel_nohq.paa"))
        _write(os.path.join(root, "props", "barrel.rvmat"),
               _rvmat("props\\barrel_co.paa", "props\\barrel_nohq.paa"))

        self.root = root
        self.index = texsearch.TextureIndex(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_basename_case(self):
        res = texsearch.resolve(self.index, "myhouse_co.png")
        self.assertEqual(res.status, 'FOUND')
        self.assertTrue(res.texture_path.lower().endswith("myhouse_co.paa"))
        self.assertTrue(res.material_path.lower().endswith("myhouse.rvmat"))

    def test_normal_named_differently_uses_rvmat_content(self):
        # Source node is the color; rvmat stem ("building") != texture base ("wall"),
        # so it can only be found by parsing rvmat references.
        res = texsearch.resolve(self.index, "wall_co.tga")
        self.assertEqual(res.status, 'FOUND')
        self.assertTrue(res.texture_path.lower().endswith("wall_co.paa"))
        self.assertTrue(res.material_path.lower().endswith("building.rvmat"))

    def test_normal_disambiguates_shared_color(self):
        # Without the normal, the shared color is ambiguous and the length tie-break
        # would wrongly pick "generic.rvmat".
        without = texsearch.resolve(self.index, "floor_co.png")
        self.assertTrue(without.material_path.lower().endswith("generic.rvmat"))
        self.assertTrue(without.ambiguous)

        # With the actual normal map, the RVMAT referencing BOTH wins unambiguously.
        with_normal = texsearch.resolve(self.index, "floor_co.png", "floor_n.png")
        self.assertEqual(with_normal.status, 'FOUND')
        self.assertTrue(with_normal.material_path.lower().endswith("floor_proper.rvmat"))
        self.assertFalse(with_normal.ambiguous)

    def test_source_normal_matches_compiled_via_basename(self):
        # Normal node points to "oak_n" (no such paa); RVMATs use "oak_nohq".
        res = texsearch.resolve(self.index, "oak_co.png", "oak_n.png")
        self.assertEqual(res.status, 'FOUND')
        self.assertTrue(res.material_path.lower().endswith("oak_mat.rvmat"))

    def test_name_match_beats_duplicate_rvmat(self):
        # Mirrors the real pack: "mix.rvmat" duplicates "mahogany.rvmat"'s texture set
        # and would win on length, but the set-named RVMAT must be chosen.
        res = texsearch.resolve(self.index, "mahogany.001", "mahogany_n.png")
        self.assertEqual(res.status, 'FOUND')
        self.assertTrue(res.material_path.lower().endswith("mahogany.rvmat"))
        self.assertFalse(res.ambiguous)

    def test_foreign_diffuse_suffix_bridges_to_arma_set(self):
        # Witcher "_d"/"_n" shader names -> Arma "_co"/"_nohq" files on disk.
        res = texsearch.resolve(self.index, "barrel_d.dds", "barrel_n.dds")
        self.assertEqual(res.status, 'FOUND')
        self.assertTrue(res.texture_path.lower().endswith("barrel_co.paa"))
        self.assertTrue(res.material_path.lower().endswith("barrel.rvmat"))

    def test_texture_only_is_partial(self):
        res = texsearch.resolve(self.index, "lonely_co.png")
        self.assertEqual(res.status, 'PARTIAL')
        self.assertTrue(res.texture_path.lower().endswith("lonely_co.paa"))
        self.assertIsNone(res.material_path)

    def test_nothing_found_is_missing(self):
        res = texsearch.resolve(self.index, "doesnotexist_co.png")
        self.assertEqual(res.status, 'MISSING')
        self.assertIsNone(res.texture_path)
        self.assertIsNone(res.material_path)

    def test_cache_returns_same_index(self):
        texsearch.clear_cache()
        a = texsearch.get_index(self.root)
        b = texsearch.get_index(self.root)
        self.assertIs(a, b)
        c = texsearch.get_index(self.root, rebuild=True)
        self.assertIsNot(a, c)


if __name__ == "__main__":
    unittest.main(argv=["texsearch"])
