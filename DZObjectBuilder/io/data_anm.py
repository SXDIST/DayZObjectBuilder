# Reader for DayZ (Enfusion) .anm binary animation files, versions ANIMSET5
# and ANIMSET6. The layout follows the one implemented by DayZATool
# (ProgramDayZAnimReader). Pure parsing, no bpy dependency.
#
# Per-bone keyframes are quantised as unsigned shorts and reconstructed with a
# per-bone bias + multiplier. A handful of header counts are stored big-endian.


import struct


class ANM_Error(Exception):
    def __str__(self):
        return "ANM - %s" % super().__str__()


ANIMSET5 = 3842772606135127617
ANIMSET6 = 3914830200173055553
NOTE_MAGIC = 1414420037

# Quantisation scale for the 16-bit keyframe samples (1 / 65535).
SCALE_KEY = 1.52590219e-05


class _Reader:
    __slots__ = ("b", "p")

    def __init__(self, buf):
        self.b = buf
        self.p = 0

    def at_end(self):
        return self.p >= len(self.b)

    def read(self, n):
        v = self.b[self.p:self.p + n]; self.p += n; return v
    def u8(self):    v = self.b[self.p]; self.p += 1; return v
    def i16(self):   v = struct.unpack_from("<h", self.b, self.p)[0]; self.p += 2; return v
    def u16(self):   v = struct.unpack_from("<H", self.b, self.p)[0]; self.p += 2; return v
    def i32(self):   v = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; return v
    def u32(self):   v = struct.unpack_from("<I", self.b, self.p)[0]; self.p += 4; return v
    def u32be(self): v = struct.unpack_from(">I", self.b, self.p)[0]; self.p += 4; return v
    def u64(self):   v = struct.unpack_from("<Q", self.b, self.p)[0]; self.p += 8; return v
    def f32(self):   v = struct.unpack_from("<f", self.b, self.p)[0]; self.p += 4; return v


def _null_string(raw):
    end = raw.find(b"\x00")
    if end >= 0:
        raw = raw[:end]
    return raw.decode("ascii", "replace")


class ANM_Bone:
    __slots__ = ("name", "translations", "rotations", "scales", "additive")

    def __init__(self, name):
        self.name = name
        self.translations = {}   # frame -> (x, y, z)
        self.rotations = {}      # frame -> (x, y, z, w)
        self.scales = {}         # frame -> (x, y, z)
        self.additive = False


class ANM_Anim:
    def __init__(self):
        self.fps = 30
        self.frame_count = 0
        self.bones = []
        self.events = []         # (frame, name, user_string, user_int)

    @classmethod
    def read_file(cls, filepath, scale=1.0):
        with open(filepath, "rb") as f:
            return cls.read(f.read(), scale)

    @classmethod
    def read(cls, data, scale=1.0):
        r = _Reader(data)
        r.u32()                          # unknown
        r.u32be()                        # unknown
        magic = r.u64()
        if magic == ANIMSET5:
            v6 = False
        elif magic == ANIMSET6:
            v6 = True
        else:
            raise ANM_Error("not an ANIMSET5/ANIMSET6 animation")

        r.u32be()                        # unknown
        r.u32()                          # unknown
        r.u32be()                        # unknown
        fps = r.i32()
        r.u32()                          # unknown
        table_len = r.u32be()

        # bone table (transform bias/multiplier + per-channel frame counts)
        meta = []
        if not v6:
            for _ in range(table_len // 56):
                meta.append({
                    "name": _null_string(r.read(32)),
                    "pb": r.f32(), "pm": r.f32() * SCALE_KEY,
                    "rb": r.f32(), "rm": r.f32() * SCALE_KEY,
                    "sb": 0.0, "sm": 0.0,
                    "nframes": r.i16(), "tfc": r.i16(), "rfc": r.i16(), "sfc": 0,
                    "flags": r.i16(),
                })
        else:
            t = _Reader(r.read(table_len))
            while not t.at_end():
                pb, pm = t.f32(), t.f32() * SCALE_KEY
                rb, rm = t.f32(), t.f32() * SCALE_KEY
                sb, sm = t.f32(), t.f32() * SCALE_KEY
                nframes, tfc, rfc, sfc = t.i16(), t.i16(), t.i16(), t.i16()
                flags = t.u8()
                name = t.read(t.u8()).decode("ascii", "replace")
                meta.append({"name": name, "pb": pb, "pm": pm, "rb": rb, "rm": rm,
                             "sb": sb, "sm": sm, "nframes": nframes,
                             "tfc": tfc, "rfc": rfc, "sfc": sfc, "flags": flags})

        r.u32()                          # unknown
        r.u32be()                        # unknown

        anim = cls()
        anim.fps = fps
        max_frame = 0
        for m in meta:
            bone = ANM_Bone(m["name"])
            bone.additive = m["flags"] > 0

            frames = [r.u16() for _ in range(m["tfc"])]
            for i in range(m["tfc"]):
                x, y, z = r.u16(), r.u16(), r.u16()
                f = frames[i]
                bone.translations[f] = ((x * m["pm"] + m["pb"]) * scale,
                                        (y * m["pm"] + m["pb"]) * scale,
                                        (z * m["pm"] + m["pb"]) * scale)
                max_frame = max(max_frame, f)

            frames = [r.u16() for _ in range(m["sfc"])]
            for i in range(m["sfc"]):
                x, y, z = r.u16(), r.u16(), r.u16()
                f = frames[i]
                bone.scales[f] = (x * m["sm"] + m["sb"], y * m["sm"] + m["sb"], z * m["sm"] + m["sb"])
                max_frame = max(max_frame, f)

            if m["rfc"] == 0:
                bone.rotations[0] = (0.0, 0.0, 0.0, 1.0)
            frames = [r.u16() for _ in range(m["rfc"])]
            for i in range(m["rfc"]):
                x, y, z, w = r.u16(), r.u16(), r.u16(), r.u16()
                f = frames[i]
                bone.rotations[f] = (x * m["rm"] + m["rb"], y * m["rm"] + m["rb"],
                                     z * m["rm"] + m["rb"], w * m["rm"] + m["rb"])
                max_frame = max(max_frame, f)

            anim.bones.append(bone)

        anim.frame_count = max((m["nframes"] for m in meta), default=max_frame + 1)

        # optional note tracks / events
        if not r.at_end() and r.u32() == NOTE_MAGIC:
            r.u32be()                    # unknown
            for _ in range(r.u16()):
                frame = r.i32()
                name = _null_string(r.read(r.i32()))
                user_string = _null_string(r.read(r.i32()))
                user_int = r.i32()
                anim.events.append((frame, name, user_string, user_int))

        return anim
