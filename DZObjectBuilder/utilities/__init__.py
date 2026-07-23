if "data" in locals():
    from importlib import reload
    
    if "data" in locals():
        reload(data)
    if "dayz_naming" in locals():
        reload(dayz_naming)
    if "logger" in locals():
        reload(logger)
    if "compat" in locals():
        reload(compat)
    if "clouds" in locals():
        reload(clouds)
    if "colors" in locals():
        reload(colors)
    if "proxy" in locals():
        reload(proxy)
    if "renaming" in locals():
        reload(renaming)
    if "generic" in locals():
        reload(generic)
    if "texsearch" in locals():
        reload(texsearch)
    if "materials" in locals():
        reload(materials)
    if "validator" in locals():
        reload(validator)
    if "flags" in locals():
        reload(flags)
    if "lod" in locals():
        reload(lod)
    if "masses" in locals():
        reload(masses)
    if "outliner" in locals():
        reload(outliner)
    if "rigging" in locals():
        reload(rigging)
    if "structure" in locals():
        reload(structure)


# In order of dependency
from . import data
from . import dayz_naming
from . import logger
from . import compat
from . import clouds
from . import colors
from . import proxy
from . import renaming
from . import generic
from . import texsearch
from . import materials
from . import validator
from . import flags
from . import lod
from . import masses
from . import outliner
from . import rigging
from . import structure
