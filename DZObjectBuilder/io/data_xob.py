# Reader for DayZ (Enfusion) .xob binary model files, versions XOB6 and XOB8.
# The binary layout follows the one implemented by the DayZATool converter
# (ProgramDayZModelReader). This module only parses the file into plain Python
# data (bones with rest transforms, mesh geometry, skin weights); it has no
# bpy dependency, so it can be unit tested and reused.
#
# XOB6 mesh streams are ZLib compressed (handled with the standard library).
# XOB8 streams may be ZLib or LZ4; the LZ4 path is implemented on a best-effort
# basis (no XOB8 sample was available to verify against).


import struct
import zlib


class XOB_Error(Exception):
    def __str__(self):
        return "XOB - %s" % super().__str__()


XOB6_MAGIC = 4918288444515569496
XOB8_MAGIC = 4918288444549123928

STREAM_LZ4 = 877615692
STREAM_ZLIB = 1112099930


class _Reader:
    __slots__ = ("b", "p")

    def __init__(self, buf):
        self.b = buf
        self.p = 0

    def seek(self, p): self.p = p
    def skip(self, n): self.p += n
    def read(self, n):
        v = self.b[self.p:self.p + n]; self.p += n; return v
    def u8(self):  v = self.b[self.p]; self.p += 1; return v
    def u16(self): v = struct.unpack_from("<H", self.b, self.p)[0]; self.p += 2; return v
    def i16(self): v = struct.unpack_from("<h", self.b, self.p)[0]; self.p += 2; return v
    def u32(self): v = struct.unpack_from("<I", self.b, self.p)[0]; self.p += 4; return v
    def i32(self): v = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; return v
    def f32(self): v = struct.unpack_from("<f", self.b, self.p)[0]; self.p += 4; return v


def _lz4_block_decode(src, out):
    # Decode a single LZ4 block, appending to the growing bytearray "out".
    # Matches may reference earlier output (chain/streaming dictionary), which
    # works naturally because "out" accumulates across blocks.
    i = 0
    n = len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8); i += 2
        mlen = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while True:
                b = src[i]; i += 1; mlen += b
                if b != 255:
                    break
        start = len(out) - offset
        for k in range(mlen):
            out.append(out[start + k])


def _decompress(reader, length, mode):
    if mode == "ZLIB":
        reader.skip(2)                       # skip 2-byte zlib header
        return zlib.decompress(reader.read(length - 4), -15)
    if mode == "LZ4":
        out = bytearray()
        end = reader.p + length
        while reader.p < end:
            flag = reader.u32()
            size = flag & 0x7FFFFFFF
            if flag & 0x80000000:            # stored (uncompressed) block
                out += reader.read(size)
            else:
                _lz4_block_decode(reader.read(size), out)
        return bytes(out)
    raise XOB_Error("uncompressed .xob streams are not supported")


class XOB_Bone:
    __slots__ = ("name", "pos", "rot", "parent")

    def __init__(self, name, pos, rot, parent):
        self.name = name
        self.pos = pos          # (x, y, z) local to parent, already scaled
        self.rot = rot          # (x, y, z, w) local quaternion
        self.parent = parent    # index into the bone list, -1 for a root


class XOB_Vertex:
    __slots__ = ("pos", "normal", "uvs", "weights")

    def __init__(self, pos):
        self.pos = pos
        self.normal = (0.0, 0.0, 1.0)
        self.uvs = []
        self.weights = []       # list of (bone_index, weight)


class XOB_Mesh:
    __slots__ = ("name", "verts", "faces", "material", "skinned")

    def __init__(self, name):
        self.name = name
        self.verts = []
        self.faces = []
        self.material = 0
        self.skinned = False


class XOB_Model:
    def __init__(self):
        self.version = 6
        self.materials = []
        self.bones = []
        self.meshes = []

    @classmethod
    def read_file(cls, filepath, scale=1.0):
        with open(filepath, "rb") as f:
            return cls.read(f.read(), scale)

    @classmethod
    def read(cls, data, scale=1.0):
        model = cls()
        r = _Reader(data)
        r.seek(8)
        magic = r.u32() | (r.u32() << 32)
        if magic == XOB6_MAGIC:
            v = 6
        elif magic == XOB8_MAGIC:
            v = 8
        else:
            raise XOB_Error("not an XOB6/XOB8 model (unknown header)")
        model.version = v

        r.seek(0x40)
        mat_count = r.u16()
        bone_count = r.u16()
        mesh_count = r.u16()
        r.u16()                              # unknown
        r.u32()                              # unknown
        strtab = r.read(r.i32())

        strings = []
        s = 0
        for i, byte in enumerate(strtab):
            if byte == 0:
                strings.append(strtab[s:i].decode("ascii", "replace"))
                s = i + 1

        for _ in range(mat_count):
            idx = r.i16() if v == 6 else r.i32()
            model.materials.append(strings[idx])

        raw = []                             # (name, pos, rot, left, right)
        for _ in range(bone_count):
            name = strings[r.i32()]
            pos = (r.f32() * scale, r.f32() * scale, r.f32() * scale)
            rot = (r.f32(), r.f32(), r.f32(), r.f32())
            left = r.i16()
            right = r.i16()
            raw.append([name, pos, rot, left, right, 0])
        for i in range(bone_count):
            if i == 0:
                raw[0][5] = -1
            if raw[i][3] != -1:
                raw[raw[i][3]][5] = raw[i][5]
            if raw[i][4] != -1:
                raw[raw[i][4]][5] = i
        model.bones = [XOB_Bone(b[0], b[1], b[2], b[5]) for b in raw]

        for _ in range(mesh_count):
            mode = "ZLIB"
            if v == 8:
                m = r.u32()
                mode = {STREAM_LZ4: "LZ4", STREAM_ZLIB: "ZLIB"}.get(m, "NONE")
            sub_count = r.u32()
            r.skip(12)
            data_off = r.u32()
            clen = r.u32()
            resume = r.p
            r.seek(data_off)
            geo = _Reader(_decompress(r, clen, mode))
            r.seek(resume)

            for _ in range(sub_count):
                if v == 8:
                    r.u32()
                name = strings[r.i32() if v == 6 else r.u16()]
                r.u32() if v == 6 else r.u16()
                r.skip(24)
                r.skip(16)
                nfaces = r.u16()
                nverts = r.u16()
                num24 = r.u16()
                nweights = r.u16()
                r.u16()
                if v == 6:
                    nuv = r.u16(); r.u16(); material = r.u16()
                else:
                    r.u16(); material = r.u16(); nuv = r.u8()
                remap_size = r.u8()
                r.u8()
                r.skip(6 if v == 6 else 23)
                remap = r.read(remap_size)

                mesh = XOB_Mesh(name)
                mesh.material = material
                mesh.skinned = remap_size > 0

                mesh.faces = [(geo.u16(), geo.u16(), geo.u16()) for _ in range(nfaces)]
                geo.skip(6 * nfaces)

                for _ in range(nverts):
                    vp = (geo.f32() * scale, geo.f32() * scale, geo.f32() * scale)
                    vert = XOB_Vertex(vp)
                    if remap_size > 0:
                        vert.weights = geo.i32()   # temporarily store weight index
                    mesh.verts.append(vert)

                for vert in mesh.verts:
                    packed = geo.u32()
                    a = (packed >> 10) & 2047
                    b = (packed >> 10) >> 11
                    c = packed & 1023
                    vert.normal = (b / 1023.0 - 1.0, a / 1023.0 - 1.0, c / 511.0 - 1.0)

                for vert in mesh.verts:
                    for _ in range(nuv):
                        u = geo.i16(); w = geo.i16()
                        vert.uvs.append((u / 1024.0, 1.0 - w / 1024.0))

                geo.skip(12 * num24)

                if remap_size > 0:
                    base = geo.p
                    for vert in mesh.verts:
                        geo.seek(base + vert.weights * 16)
                        idx = [remap[geo.u8()] for _ in range(4)]
                        w0, w1, w2 = geo.f32(), geo.f32(), geo.f32()
                        w3 = 1.0 - (w0 + w1 + w2)
                        ws = [(idx[0], w0)]
                        if w1 > 0.0:
                            ws.append((idx[1], w1))
                        if w2 > 0.0:
                            ws.append((idx[2], w2))
                        if w3 > 0.0 and idx[3] not in (idx[0], idx[1], idx[2]):
                            ws.append((idx[3], w3))
                        vert.weights = ws
                    geo.seek(base + nweights * 16)
                else:
                    for vert in mesh.verts:
                        vert.weights = []

                model.meshes.append(mesh)

        return model
