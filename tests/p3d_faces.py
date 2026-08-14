"""
python tests/p3d_faces.py

Pins the removal of faces Blender cannot hold.

A face whose corners do not all name distinct vertices has no area. Blender's
from_pydata will build one, and mesh.update() will report a sensible loop count for
it, but the mesh it produces is malformed: on Blender 5.1.2 the following
mesh.normals_split_custom_set() reads out of bounds and takes the whole process down
with an access violation, with no Python exception to catch.

Hand authored MLOD models really do contain them - 2406 faces across 9 of the 505
models in the IMPWMOD source tree, every one a triangle with a repeated corner - so
the importer drops them before the mesh is built. Binarized input has never produced
one (none over 2339 ODOL models), which is why this only ever showed up on .p3d
sources.

The importer derives its loop normals, UVs, materials and face flags from the face
list after this runs, so the only thing that can fall out of step is a tagg that
addresses faces by index. Those are remapped here, and that is what these tests are
mostly about.
"""


import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

p3d = load_io("data_p3d")


def make_face(vertices, texture = "tex.paa"):
    # [vertices, normals, uvs, texture, material, flag]. Normals are parallel to the
    # vertex indices the same way the readers produce them.
    return [list(vertices), list(vertices), [(0.0, 0.0)] * len(vertices), texture, "mat.rvmat", 0]


def make_lod(faces):
    lod = p3d.P3D_LOD()
    lod.verts = [(float(i), 0.0, 0.0, 0) for i in range(64)]
    lod.normals = [(0.0, 0.0, 1.0)] * 64
    lod.faces = [make_face(face) for face in faces]

    return lod


def make_selection(lod, name, weight_faces):
    tagg = p3d.P3D_TAGG()
    tagg.name = name

    data = p3d.P3D_TAGG_DataSelection()
    data.count_verts = len(lod.verts)
    data.count_faces = len(lod.faces)
    data.weight_verts = [(0, 1.0)]
    data.weight_faces = list(weight_faces)

    tagg.data = data
    lod.taggs.append(tagg)

    return data


class TestDegenerateFaceRemoval(unittest.TestCase):
    def test_a_clean_lod_is_left_alone(self):
        lod = make_lod([(0, 1, 2), (3, 4, 5, 6)])
        faces = list(lod.faces)

        self.assertEqual(lod.remove_degenerate_faces(), 0)
        self.assertEqual(lod.faces, faces)

    def test_a_triangle_with_a_repeated_corner_is_dropped(self):
        # The exact shape found in the corpus: three corners, two distinct vertices.
        lod = make_lod([(0, 1, 2), (10, 11, 11), (3, 4, 5)])

        self.assertEqual(lod.remove_degenerate_faces(), 1)
        self.assertEqual([face[0] for face in lod.faces], [[0, 1, 2], [3, 4, 5]])

    def test_a_face_collapsing_to_one_vertex_is_dropped(self):
        lod = make_lod([(7, 7, 7), (0, 1, 2)])

        self.assertEqual(lod.remove_degenerate_faces(), 1)
        self.assertEqual([face[0] for face in lod.faces], [[0, 1, 2]])

    def test_a_quad_with_a_repeated_corner_is_dropped(self):
        # None have been seen, but a quad with a repeat is malformed for the same
        # reason a triangle is, so it must not be handed to Blender either.
        lod = make_lod([(0, 1, 2, 1), (3, 4, 5)])

        self.assertEqual(lod.remove_degenerate_faces(), 1)
        self.assertEqual([face[0] for face in lod.faces], [[3, 4, 5]])

    def test_surviving_faces_keep_all_their_data(self):
        lod = make_lod([(10, 11, 11), (0, 1, 2)])
        lod.faces[1][3] = "kept.paa"
        kept = lod.faces[1]

        lod.remove_degenerate_faces()

        self.assertEqual(lod.faces, [kept])

    def test_loop_normals_stay_in_step_with_the_faces(self):
        # This is the invariant the importer's own guard rests on: it only applies
        # custom normals when the loop count matches, so the two must agree after
        # removal or the model silently loses its shading.
        lod = make_lod([(0, 1, 2), (10, 11, 11), (3, 4, 5, 6)])
        lod.remove_degenerate_faces()

        corners = sum(len(face[0]) for face in lod.faces)
        self.assertEqual(len(lod.loop_normals()), corners)
        self.assertEqual(corners, 7)

    def test_selection_face_indices_are_remapped(self):
        # A selection addresses faces by index, so dropping face 1 has to pull face 2
        # down to 1 rather than leave the selection pointing at the wrong face.
        lod = make_lod([(0, 1, 2), (10, 11, 11), (3, 4, 5)])
        data = make_selection(lod, "camo", [(0, 1.0), (2, 0.5)])

        lod.remove_degenerate_faces()

        self.assertEqual(data.weight_faces, [(0, 1.0), (1, 0.5)])

    def test_a_selection_on_a_removed_face_loses_it(self):
        lod = make_lod([(0, 1, 2), (10, 11, 11)])
        data = make_selection(lod, "camo", [(0, 1.0), (1, 1.0)])

        lod.remove_degenerate_faces()

        self.assertEqual(data.weight_faces, [(0, 1.0)])

    def test_selection_face_count_follows_the_faces(self):
        lod = make_lod([(0, 1, 2), (10, 11, 11)])
        data = make_selection(lod, "camo", [])

        lod.remove_degenerate_faces()

        self.assertEqual(data.count_faces, 1)
        self.assertEqual(data.count_verts, len(lod.verts))

    def test_vertex_weights_are_untouched(self):
        # Only face indices shift; vertices are not renumbered.
        lod = make_lod([(0, 1, 2), (10, 11, 11)])
        data = make_selection(lod, "camo", [])

        lod.remove_degenerate_faces()

        self.assertEqual(data.weight_verts, [(0, 1.0)])

    def test_non_selection_taggs_survive(self):
        lod = make_lod([(0, 1, 2), (10, 11, 11)])
        tagg = p3d.P3D_TAGG()
        tagg.name = "#Property#"
        tagg.data = p3d.P3D_TAGG_DataProperty()
        lod.taggs.append(tagg)

        lod.remove_degenerate_faces()

        self.assertEqual([item.name for item in lod.taggs], ["#Property#"])


if __name__ == "__main__":
    unittest.main()
