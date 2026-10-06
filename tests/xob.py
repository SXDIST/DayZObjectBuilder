import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _addon import load_io

xob = load_io("data_xob")


VANILLA_BODIES = (
    r"P:\DZ\anims\workspaces\player\Models\player_m_editorpreview.xob",
    r"P:\DZ\characters\bodies\player_testing.xob",
)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _signed_volume(points, faces):
    return sum(_dot(points[f[0]], _cross(points[f[1]], points[f[2]])) for f in faces) / 6.0


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _qrot(q, v):
    x, y, z, _ = _qmul(_qmul(q, (v[0], v[1], v[2], 0.0)), (-q[0], -q[1], -q[2], q[3]))
    return (x, y, z)


def _world_positions(bones):
    world = [None] * len(bones)

    def resolve(i):
        if world[i] is None:
            bone = bones[i]
            if bone.parent < 0:
                world[i] = (tuple(bone.pos), tuple(bone.rot))
            else:
                parent_pos, parent_rot = resolve(bone.parent)
                offset = _qrot(parent_rot, bone.pos)
                world[i] = (
                    tuple(p + o for p, o in zip(parent_pos, offset)),
                    _qmul(parent_rot, bone.rot),
                )
        return world[i]

    return {bones[i].name.lower(): resolve(i)[0] for i in range(len(bones))}


class TestConversion(unittest.TestCase):
    def test_axes_are_a_reflection(self):
        x, y, z = (xob.to_blender_axes(v) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))

        self.assertEqual(_dot(_cross(x, y), z), -1)

    def test_y_up_becomes_z_up(self):
        self.assertEqual(xob.to_blender_axes((0.0, 1.0, 0.0)), (0.0, 0.0, 1.0))

    def test_winding_keeps_a_closed_mesh_outward(self):
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
        converted = [xob.to_blender_axes(p) for p in points]

        before = _signed_volume(points, faces)
        after = _signed_volume(converted, [xob.to_blender_face(f) for f in faces])

        self.assertGreater(before, 0)
        self.assertAlmostEqual(after, before)


class TestVanillaBody(unittest.TestCase):
    def _models(self):
        found = [path for path in VANILLA_BODIES if os.path.isfile(path)]
        if not found:
            self.skipTest("no vanilla body .xob under P:\\")
        return [(os.path.basename(path), xob.XOB_Model.read_file(path)) for path in found]

    def test_left_side_is_positive_x(self):
        for name, model in self._models():
            world = _world_positions(model.bones)
            for bone in ("lefthand", "leftfoot", "lefttoebase"):
                with self.subTest(model=name, bone=bone):
                    self.assertGreater(xob.to_blender_axes(world[bone])[0], 0.1)
            for bone in ("righthand", "rightfoot", "righttoebase"):
                with self.subTest(model=name, bone=bone):
                    self.assertLess(xob.to_blender_axes(world[bone])[0], -0.1)

    def test_faces_minus_y(self):
        for name, model in self._models():
            world = {k: xob.to_blender_axes(v) for k, v in _world_positions(model.bones).items()}
            with self.subTest(model=name):
                self.assertLess(world["lefttoebase"][1], world["leftfoot"][1])
                self.assertLess(world["face_jowl"][1], world["head"][1])

    def test_body_normals_point_outward(self):
        for name, model in self._models():
            for mesh in model.meshes:
                if len(mesh.faces) < 1000:
                    continue
                with self.subTest(model=name, mesh=mesh.name):
                    points = [xob.to_blender_axes(v.pos) for v in mesh.verts]
                    faces = [xob.to_blender_face(f) for f in mesh.faces]
                    self.assertGreater(_signed_volume(points, faces), 0)


if __name__ == "__main__":
    unittest.main()
