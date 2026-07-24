if "object" in locals():
    from importlib import reload

    if "material" in locals():
        reload(material)
    if "object" in locals():
        reload(object)
    if "scene" in locals():
        reload(scene)
    if "lod_generator" in locals():
        reload(lod_generator)


from . import material
from . import object
from . import scene
from . import lod_generator
