import os
import re

from . import generic


def _trace_to_image(socket, visited=None):
    """Follow an input socket upstream until an Image Texture with an image is hit.

    Handles intermediate nodes (Normal Map, color adjustments, etc.) by recursing
    into their inputs.
    """
    if socket is None or not socket.is_linked:
        return None

    if visited is None:
        visited = set()

    for link in socket.links:
        node = link.from_node
        if node in visited:
            continue
        visited.add(node)

        if node.type == 'TEX_IMAGE' and node.image:
            return node.image

        for inp in node.inputs:
            img = _trace_to_image(inp, visited)
            if img:
                return img

    return None


def _find_principled(nodes):
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node

    return None


def _image_nodes(nodes):
    return [node for node in nodes if node.type == 'TEX_IMAGE' and node.image]


def _is_data_image(image):
    # Normal/specular/etc. maps are stored as non-color data; color maps are sRGB.
    return image.colorspace_settings.name == 'Non-Color'


def get_base_color_image(material):
    """Return the image feeding the Base Color of a material's shader, or None.

    Traces the Principled BSDF Base Color input first; falls back to the first
    color (non-data) image node, then any image node. Works with relabeled image
    nodes and custom node setups that have no directly-wired image.
    """
    if not material or not material.use_nodes or not material.node_tree:
        return None

    nodes = material.node_tree.nodes

    bsdf = _find_principled(nodes)
    if bsdf:
        img = _trace_to_image(bsdf.inputs.get("Base Color"))
        if img:
            return img

    images = _image_nodes(nodes)
    for node in images:
        if not _is_data_image(node.image):
            return node.image

    return images[0].image if images else None


def get_normal_image(material):
    """Return the normal-map image of a material's shader, or None.

    Traces the Principled BSDF Normal input first; falls back to a data (Non-Color)
    image node, or one whose label/name looks like a normal map. This is what lets
    the search disambiguate an RVMAT when the normal is named differently from the
    color (e.g. "_n" instead of "_nohq").
    """
    if not material or not material.use_nodes or not material.node_tree:
        return None

    nodes = material.node_tree.nodes

    bsdf = _find_principled(nodes)
    if bsdf:
        img = _trace_to_image(bsdf.inputs.get("Normal"))
        if img:
            return img

    base = get_base_color_image(material)
    for node in _image_nodes(nodes):
        if node.image is base:
            continue

        label = (node.label or node.name or "").lower()
        iname = (node.image.name or "").lower()
        if _is_data_image(node.image) or any(t in label or t in iname for t in ("normal", "nohq", "_n", "_nm")):
            return node.image

    return None


def image_basename(image):
    """The best file-name basename for an image: its filepath if set, else its name.

    Handles Blender's "//" blend-relative prefix and either path separator
    (os.path.basename treats a leading "//" as a UNC root on Windows).
    """
    if not image:
        return ""

    path = image.filepath or image.name
    path = path.replace("\\", "/").lstrip("/")

    return path.rsplit("/", 1)[-1]


def search_and_apply(material, index, overwrite=True):
    """Resolve a material's texture set from its Base Color image and apply it.

    Returns the ResolveResult, or None if the material has no usable image.
    Honors `overwrite` per field: when False, already filled paths are kept.
    """
    from . import generic as utils
    from . import texsearch

    image = get_base_color_image(material)
    if not image:
        return None

    normal = get_normal_image(material)
    normal_name = image_basename(normal) if normal else None

    props = material.a3ob_properties_material
    result = texsearch.resolve(index, image_basename(image), normal_name)

    if result.texture_path and (overwrite or not props.texture_path):
        props.texture_type = 'TEX'
        props.texture_path = utils.replace_slashes(result.texture_path)

    if result.material_path and (overwrite or not props.material_path):
        props.material_path = utils.replace_slashes(result.material_path)

    return result


class RVMATTemplateField:
    def __init__(self, string):
        if not string.startswith("<") or not string.endswith(">") or string.count("|") != 2:
            print(string)
            raise ValueError("Invalid RVMAT template field definition")
        
        string = string[1:-1]
        suffixes, extensions, default = string.split("|")

        self.suffixes = [("_%s" % item.strip().lower()) for item in suffixes.split(",")]
        self.extensions = [(".%s" % item.strip().lower()) for item in extensions.split(",")]

        self.default = default
    
    def generate_paths(self, folder, basename):
        return [os.path.join(folder, basename + sfx + ext) for sfx in self.suffixes for ext in self.extensions]
    
    def generate_value(self, root, folder, basename, check_files_exist):
        paths = self.generate_paths(folder, basename)
        print(paths)

        for item in paths:
            if os.path.isfile(item):
                return os.path.relpath(item, root)
        
        if not check_files_exist:
            return os.path.relpath(paths[0], root)
        
        return self.default

class RVMATTemplate:
    RE_STAGE = re.compile(r"<.*>")

    def __init__(self, filepath):
        self.fields = []
        with generic.open_long(filepath, encoding="utf-8") as file:
            self.template = file.read()

        for match in self.RE_STAGE.finditer(self.template):
            try:
                self.fields.append(RVMATTemplateField(match.group(0)))
            except ValueError as ex:
                self.fields.append(None)
    
    def write_output(self, root, folder, basename, check_files_exist):
        values = ((field.generate_value(root, folder, basename, check_files_exist) if field else None) for field in self.fields)
        
        def repl(match):
            string = next(values)
            if string is None:
                return match.group(0)
            
            return "\"%s\"" % string
        
        try:
            if not os.path.isdir(generic.long_path(folder)):
                os.makedirs(generic.long_path(folder))

            with generic.open_long(os.path.join(folder, basename + ".rvmat"), "w", encoding="utf-8") as file:
                file.write(self.RE_STAGE.sub(repl, self.template))
                return True
            
        except Exception as ex:
            print(ex)
            return False
