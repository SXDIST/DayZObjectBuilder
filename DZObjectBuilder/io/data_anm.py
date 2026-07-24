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

# Fixed header signatures observed in every vanilla/plugin .anm. None of these
# are truly "unknown" - they are constant markers, and the remaining header
# fields are length prefixes computed at write time (see ANM_Anim.write).
_SIG_HEAD = 1297239878     # first word
_SIG_A = 5460038           # constant word after the magic block
_SIG_B = 4                 # constant word (big-endian)
_SIG_C = 1145128264        # constant word before the bone table
_SIG_DATA = 1096040772     # "DATA" marker before the keyframe block


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


class _Writer:
    __slots__ = ("buf",)

    def __init__(self):
        self.buf = bytearray()

    def u8(self, v):    self.buf += struct.pack("<B", int(v) & 0xFF)
    def i16(self, v):   self.buf += struct.pack("<h", int(v))
    def u16(self, v):   self.buf += struct.pack("<H", int(v) & 0xFFFF)
    def i32(self, v):   self.buf += struct.pack("<i", int(v))
    def u32(self, v):   self.buf += struct.pack("<I", int(v) & 0xFFFFFFFF)
    def u32be(self, v): self.buf += struct.pack(">I", int(v) & 0xFFFFFFFF)
    def u64(self, v):   self.buf += struct.pack("<Q", int(v))
    def f32(self, v):   self.buf += struct.pack("<f", v)
    def raw(self, b):   self.buf += b


def _quant_params(values):
    # Single (bias, multiplier) shared by all components of a channel, chosen so
    # the value range maps onto the full unsigned-short span. A flat channel maps
    # to multiplier 0 (every sample decodes back to the bias).
    if not values:
        return 0.0, 0.0
    lo = min(values)
    rng = max(values) - lo
    if rng <= 0.0:
        return lo, 0.0
    return lo, rng / 65535.0


def _q(value, bias, mult):
    if mult <= 0.0:
        return 0
    s = int(round((value - bias) / mult))
    return 0 if s < 0 else 65535 if s > 65535 else s


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

    def write_file(self, filepath, v6=False):
        with open(filepath, "wb") as f:
            f.write(self.write(v6))

    def write(self, v6=False):
        table = _Writer()
        keyframes = _Writer()

        for bone in self.bones:
            tframes = sorted(bone.translations)
            sframes = sorted(bone.scales)
            rframes = sorted(bone.rotations)

            pb, pm = _quant_params([c for f in tframes for c in bone.translations[f]])
            sb, sm = _quant_params([c for f in sframes for c in bone.scales[f]])
            rb, rm = _quant_params([c for f in rframes for c in bone.rotations[f]])

            nframes = self.frame_count
            tfc, sfc, rfc = len(tframes), len(sframes), len(rframes)
            flags = 1 if bone.additive else 0

            if not v6:
                name = bone.name.encode("ascii", "replace")[:31]
                table.raw(name + b"\x00" * (32 - len(name)))
                table.f32(pb); table.f32(pm / SCALE_KEY)
                table.f32(rb); table.f32(rm / SCALE_KEY)
                table.i16(nframes); table.i16(tfc); table.i16(rfc); table.i16(flags)
            else:
                table.f32(pb); table.f32(pm / SCALE_KEY)
                table.f32(rb); table.f32(rm / SCALE_KEY)
                table.f32(sb); table.f32(sm / SCALE_KEY)
                table.i16(nframes); table.i16(tfc); table.i16(rfc); table.i16(sfc)
                table.u8(flags)
                name = bone.name.encode("ascii", "replace")[:255]
                table.u8(len(name)); table.raw(name)

            # keyframe block order: translation, scale, rotation
            for f in tframes:
                keyframes.u16(f)
            for f in tframes:
                x, y, z = bone.translations[f]
                keyframes.u16(_q(x, pb, pm)); keyframes.u16(_q(y, pb, pm)); keyframes.u16(_q(z, pb, pm))

            for f in sframes:
                keyframes.u16(f)
            for f in sframes:
                x, y, z = bone.scales[f]
                keyframes.u16(_q(x, sb, sm)); keyframes.u16(_q(y, sb, sm)); keyframes.u16(_q(z, sb, sm))

            for f in rframes:
                keyframes.u16(f)
            for f in rframes:
                x, y, z, w = bone.rotations[f]
                keyframes.u16(_q(x, rb, rm)); keyframes.u16(_q(y, rb, rm))
                keyframes.u16(_q(z, rb, rm)); keyframes.u16(_q(w, rb, rm))

        table_bytes = bytes(table.buf)
        kf_bytes = bytes(keyframes.buf)

        note_bytes = b""
        if self.events:
            body = _Writer()
            body.u16(len(self.events))
            for frame, name, user_string, user_int in self.events:
                nb = name.encode("ascii", "replace") + b"\x00"
                sb2 = user_string.encode("ascii", "replace") + b"\x00"
                body.i32(frame)
                body.i32(len(nb)); body.raw(nb)
                body.i32(len(sb2)); body.raw(sb2)
                body.i32(user_int)
            body_bytes = bytes(body.buf)
            note = _Writer()
            note.u32(NOTE_MAGIC)
            note.u32be(len(body_bytes))
            note.raw(body_bytes)
            note_bytes = bytes(note.buf)

        # header(40) + table + DATA marker(4) + keyframe length(4) + keyframes + notes
        total = 40 + len(table_bytes) + 8 + len(kf_bytes) + len(note_bytes)

        w = _Writer()
        w.u32(_SIG_HEAD)
        w.u32be(total - 8)
        w.u64(ANIMSET6 if v6 else ANIMSET5)
        w.u32be(total - 20)
        w.u32(_SIG_A)
        w.u32be(_SIG_B)
        w.i32(self.fps)
        w.u32(_SIG_C)
        w.u32be(len(table_bytes))
        w.raw(table_bytes)
        w.u32(_SIG_DATA)
        w.u32be(len(kf_bytes))
        w.raw(kf_bytes)
        w.raw(note_bytes)

        return bytes(w.buf)
