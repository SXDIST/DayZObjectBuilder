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


import math
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


# ---------------------------------------------------------------------------
# Engine space arithmetic
#
# Everything below stays in DayZ's own space and never crosses into Blender.
# That is deliberate. The engine's matrices (E, and the item/hand transforms a
# probe prints) live in one convention, and the bone channels inside an .anm
# live in another - the .anm quaternion convention is what DayZ Tools writes,
# and the two differ by a mirror. Both are validated against the engine on
# their own side, and mixing them in one formula is exactly the mistake this
# module exists to prevent. So the solver reports engine space values, and
# anything that has to reach a clip goes through the add-on's own import and
# export, which round trip that convention exactly.
#
# Matrices here are held in column convention (Blender's, v' = M * v) even
# though DayZ writes rows, because mathutils multiplies that way. A DayZ row
# matrix M_row becomes M_col = M_row^T, which reverses the order of products:
#
#     item = E * D * hand        (DayZ rows)
#     item_col = hand_col * D_col * E_col
# ---------------------------------------------------------------------------


# DayZ's world up. Blender's is +Z; both axis conversions in this file agree on
# that one mapping, which is why a verticality check is convention independent.
DAYZ_UP = Vector((0.0, 1.0, 0.0))


def dayz_col_from_rows(rows):
    rows = [tuple(row) for row in rows]
    if len(rows) == 3:
        rows.append((0.0, 0.0, 0.0))

    matrix = Matrix.Identity(4)
    for index, row in enumerate(rows[0:4]):
        for axis in range(3):
            matrix[axis][index] = row[axis]

    return matrix


def rows_from_dayz_col(matrix):
    return tuple(tuple(matrix[axis][index] for axis in range(3)) for index in range(4))


# The item's own up axis, in world space. In DayZ's row layout that is row 1 of
# the item's transform.
def item_up_axis(item_col):
    return (item_col.to_3x3() @ DAYZ_UP).normalized()


def tilt_degrees(item_col):
    return math.degrees(item_up_axis(item_col).angle(DAYZ_UP))


def compose_item(hand_col, bone_col, grip_col):
    return hand_col @ bone_col @ grip_col


def bone_from_sample(item_col, hand_col, grip_col):
    return hand_col.inverted() @ item_col @ grip_col.inverted()


# The bone value that would stand this sample's item upright: rotate the item
# about its own origin by the minimal rotation taking its up axis to world up,
# then read the bone back out of the composition.
def upright_bone_from_sample(item_col, hand_col, grip_col):
    correction = item_up_axis(item_col).rotation_difference(DAYZ_UP).to_matrix().to_4x4()
    upright = correction @ item_col
    upright.translation = item_col.translation

    return bone_from_sample(upright, hand_col, grip_col)


# ---------------------------------------------------------------------------
# Probe log
# ---------------------------------------------------------------------------

# A line is assigned to a matrix by the first of these words it contains, and
# carries either one row (3 numbers) or a whole transform (9 for the axes, 12
# with the position). Rows accumulate until three are in, so a probe that
# prints item0/item1/item2 on separate lines reads the same as one that prints
# the matrix on one. A second item matrix starts a second sample.
SAMPLE_KINDS = (
    ("item", ("item", "held", "object")),
    ("hand", ("hand",)),
    ("grip", ("grip", "gripmat")),
)

# Labels are dropped before the numbers are read, so "item0" does not leave a
# stray 0 behind. A label is a whole identifier - it has to start the word, so
# the "e" of 1e-05 is not one and scientific notation survives.
_LABEL = re.compile(r"(?<![0-9A-Za-z_])[A-Za-z_][0-9A-Za-z_]*")


class _Blocks:
    def __init__(self):
        self.matrices = []
        self.rows = []

    def feed(self, numbers):
        if len(numbers) in (9, 12):
            self.flush()
            self.matrices.append(dayz_col_from_rows([numbers[start:start + 3] for start in range(0, len(numbers), 3)]))
        elif len(numbers) == 3:
            self.rows.append(numbers)
            if len(self.rows) == 4:
                self.flush()
        # Any other count is a line that merely happens to contain the word -
        # a frame counter, an index - and is ignored rather than guessed at.

    def flush(self):
        if len(self.rows) >= 3:
            self.matrices.append(dayz_col_from_rows(self.rows[0:4]))

        self.rows = []


def _kind_of(line):
    lowered = line.lower()
    position = {}
    for kind, words in SAMPLE_KINDS:
        hits = [lowered.find(word) for word in words if lowered.find(word) >= 0]
        if hits:
            position[kind] = min(hits)

    if not position:
        return None

    # "RightHand_Dummy" in a label would otherwise claim the line for the hand,
    # so the earliest word in the line wins and a bone name loses to the label
    # in front of it.
    return min(position, key=position.get)


# Returns (samples, grip_override). A sample is a dict with the item and hand
# transforms of one measured frame, in column convention.
def parse_probe_samples(text):
    blocks = {kind: _Blocks() for kind, _words in SAMPLE_KINDS}

    for line in text.splitlines():
        kind = _kind_of(line)
        if kind is None:
            continue

        numbers = [float(match.group()) for match in NUMBER.finditer(_LABEL.sub(" ", line))]
        blocks[kind].feed(numbers)

    for block in blocks.values():
        block.flush()

    items = blocks["item"].matrices
    hands = blocks["hand"].matrices

    if not items or not hands:
        raise ValueError("Found %d item and %d hand transform(s); label the probe lines with 'item' and 'hand'" % (len(items), len(hands)))

    if len(items) != len(hands):
        raise ValueError("Found %d item transform(s) but %d hand transform(s), every sample needs both" % (len(items), len(hands)))

    grips = blocks["grip"].matrices
    if len(grips) > 1:
        raise ValueError("Found %d grip matrices in the log, expected at most one" % len(grips))

    samples = [{"item": item, "hand": hand} for item, hand in zip(items, hands)]

    return samples, (grips[0] if grips else None)
