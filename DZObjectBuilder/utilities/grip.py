# The matrix that puts a held item into the character's hand.
#
# DayZ does not animate a held item, and does not give it a bone of its own. The
# engine redraws it every frame from the grip bone:
#
#     item = RightHand_Dummy * E      (row convention: v_world = v_local * M)
#
# E is one fixed matrix, identical for every item, and it is the one piece of the
# chain that no .p3d, .anm or model.cfg carries. A scene that wants to show the
# item in the hand has to supply it from somewhere, so everyone who needed it so
# far derived it by hand from an axis convention plus a transposition - and got
# it wrong, silently, because a wrong grip matrix still produces a preview that
# looks entirely plausible. One such hand written matrix was measured 161 degrees
# off, while every offline check in that project (distance to the lips, phase
# seams, wrist error) reported a perfect result, because all of them ran through
# that same matrix.
#
# So E is MEASURED, never derived. See GRIP_MATRIX_MEASURED for the probe.


import re

from mathutils import Matrix, Vector


# The bone the engine hangs the item off, and its parent in the DayZ rig. The
# dummy is a child of RightHand, so a Child Of constraint on the dummy already
# carries the hand - composing the hand a second time is a common way to get a
# preview that is wrong by exactly the hand's own rotation.
GRIP_BONE = "RightHand_Dummy"
GRIP_PARENT_BONE = "RightHand"

# E, as read out of a running game. Rows are the axes of the item relative to the
# grip bone, in DayZ's own order: right, up, forward.
#
# Taken with an Enforce Script probe in `modded class PlayerBase`, under
# `#ifdef DIAG_DEVELOPER`:
#
#     GetBoneTransformWS(GetBoneIndexByName("RightHand_Dummy"), gripBone);
#     held.GetTransform(heldWorld);
#     Math3D.MatrixInvMultiply4(gripBone, heldWorld, gripMat);
#     Math3D.MatrixOrthogonalize4(gripMat);
#
# Cross checked against the composition model `item = E * D * hand` (D being the
# local transform of RightHand_Dummy against RightHand) on live frames: agreement
# to 0.0000 on three samples out of four, the fourth being a frame where the
# item's transform lagged the bone by one tick.
GRIP_MATRIX_MEASURED = (
    (-0.999951, -0.00972025, -0.00163486),      # right
    (-0.00161898, -0.00164119, 0.999997),       # up
    (-0.00972291, 0.999951, 0.00162537),        # forward
)

# Blender to DayZ axis conversion: (x, y, z)_blender -> (x, z, -y)_dayz.
#
# Note this is the proper rotation (determinant +1), not the mirrored y/z swap
# the .anm reader uses internally for keyframe data. The two differ by a
# reflection, which for a rotation matrix is not a no-op: conjugating E through
# the mirrored swap instead lands the item 165 degrees off. Pinned by tests/grip.py.
MTX_AXES = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))


# Conjugate the engine matrix into Blender's column convention:
#
#     M_blender = S^-1 * (M_dayz_rows)^T * S
#
# The transposition is DayZ's row-major storage (rows are axes), the conjugation
# is the axis change. Getting either one wrong is invisible in the viewport,
# which is the whole reason this lives in one place.
def matrix_basis_from_rows(rows):
    engine = Matrix([tuple(row) for row in rows])

    return (MTX_AXES.inverted() @ engine.transposed() @ MTX_AXES).to_4x4()


def rows_from_flat(values):
    values = tuple(values)

    return tuple(values[start:start + 3] for start in (0, 3, 6))


def flat_from_rows(rows):
    return tuple(value for row in rows for value in row)


# Measurements come out of the game with a little drift, and a basis that is not
# quite orthonormal skews the item instead of just rotating it. The engine's own
# probe calls MatrixOrthogonalize4 for the same reason.
def orthonormalize(rows):
    basis = []
    for index, row in enumerate(rows):
        vector = Vector(row)
        for previous in basis:
            vector = vector - previous * vector.dot(previous)

        if vector.length < 1e-6:
            raise ValueError("Axis %d of the grip matrix is degenerate (parallel to another axis, or zero length)" % (index + 1))

        basis.append(vector.normalized())

    if Matrix(basis).determinant() < 0:
        raise ValueError("The grip matrix is left handed - the three axes are most likely in the wrong order, expected right, up, forward")

    return tuple(tuple(vector) for vector in basis)


NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


# Read a grip matrix out of whatever the in game probe printed. Every number in
# the text is taken in order, so the surrounding wording, the axis labels and the
# brackets are all free form - only the count has to be right: 9 for a plain
# basis, or 12 for a full DayZ 4x3 transform, whose fourth row is the position
# and is dropped (the item sits on the bone's own origin).
def parse_grip_log(text):
    numbers = [float(match.group()) for match in NUMBER.finditer(text)]

    if len(numbers) == 12:
        numbers = numbers[0:9]

    if len(numbers) != 9:
        raise ValueError("Expected 9 numbers (right, up, forward) or 12 (4x3 transform), found %d" % len(numbers))

    return orthonormalize(rows_from_flat(numbers))
