# Canonical DayZ bone / vertex-group naming.
#
# DayZ character rigs use PascalCase names (Pelvis, LeftForeArm, PropWeaponBody,
# Face_Forehead, ...). The DayzTemporarySkeleton preset in `data` is already
# stored in that canonical casing, so it doubles as the source of truth: any
# known bone name (in any casing) is mapped to the preset's form, and names that
# are not part of the skeleton (Scene_Root, EntityPosition, *_End, ...) are left
# untouched.


import re

from . import data


_RENAME = None


def _normalize(name):
    return re.sub(r"[^a-z0-9_]", "", name.lower())


def _build():
    global _RENAME
    _RENAME = {_normalize(name): name for name in data.dayz_temporary_skeleton}


def to_pascal_case(name):
    if _RENAME is None:
        _build()

    return _RENAME.get(_normalize(name), name)
