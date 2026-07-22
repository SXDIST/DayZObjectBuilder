import os

import bpy

from ..utilities import generic as utils
from ..utilities import materials as matutils
from ..utilities import texsearch


class A3OB_OT_material_autosearch(bpy.types.Operator):
    """Auto-search the texture and RVMAT for the active material from its Base Color image"""

    bl_label = "Auto Search Texture"
    bl_idname = "a3ob.material_autosearch"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hasattr(context, "material") and context.material

    def execute(self, context):
        scene_props = context.scene.a3ob_materials
        root = utils.abspath(scene_props.mod_root)

        if not root or not os.path.isdir(root):
            self.report({'ERROR'}, "Set a valid Mod Root in the Materials panel first")
            return {'CANCELLED'}

        index = texsearch.get_index(root, scene_props.search_source_textures)
        result = matutils.search_and_apply(context.material, index, overwrite=True)

        if result is None:
            self.report({'WARNING'}, "Material has no Base Color image to search by")
            return {'CANCELLED'}

        if result.status == 'FOUND':
            msg = "Found texture and RVMAT"
            if result.ambiguous:
                msg += " (multiple RVMATs matched, picked best)"
            self.report({'INFO'}, msg)
        elif result.status == 'PARTIAL':
            found = "texture" if result.texture_path else "RVMAT"
            self.report({'WARNING'}, "Only found %s" % found)
        else:
            self.report({'WARNING'}, "No matching texture or RVMAT found")

        return {'FINISHED'}


class A3OB_OT_paste_common_material(bpy.types.Operator):
    """Paste a common material path"""
    
    bl_label = "Paste Common Material"
    bl_idname = "a3ob.paste_common_material"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return hasattr(context, "material") and context.material
    
    def invoke(self, context, event):
        utils.load_common_data(context.scene)
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        scene_props = context.scene.a3ob_commons
        layout = self.layout
        layout.template_list("A3OB_UL_common_data_materials", "A3OB_common_materials", scene_props, "items", scene_props, "items_index", item_dyntip_propname="value")


    def execute(self, context):
        mat = context.material
        scene_props = context.scene.a3ob_commons

        if utils.is_valid_idx(scene_props.items_index, scene_props.items):
            new_item = scene_props.items[scene_props.items_index]
            mat_props = mat.a3ob_properties_material
            mat_props.material_path = new_item.value
        
        return {'FINISHED'}


class A3OB_OT_paste_common_procedural(bpy.types.Operator):
    """Paste a common procedural texture"""
    
    bl_label = "Paste Common Procedural"
    bl_idname = "a3ob.paste_common_procedural"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return hasattr(context, "material") and context.material
    
    def invoke(self, context, event):
        utils.load_common_data(context.scene)
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        scene_props = context.scene.a3ob_commons
        layout = self.layout
        layout.template_list("A3OB_UL_common_data_procedurals", "A3OB_common_procedurals", scene_props, "items", scene_props, "items_index", item_dyntip_propname="value")

    def execute(self, context):
        mat = context.material
        scene_props = context.scene.a3ob_commons

        if utils.is_valid_idx(scene_props.items_index, scene_props.items):
            new_item = scene_props.items[scene_props.items_index]
            mat_props = mat.a3ob_properties_material
            mat_props.color_raw = new_item.value
        
        return {'FINISHED'}


class A3OB_UL_common_procedurals(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.label(text=item.name)


class A3OB_PT_material(bpy.types.Panel):
    bl_region_type = 'WINDOW'
    bl_space_type = 'PROPERTIES'
    bl_label = "Object Builder: Material Properties"
    bl_context = "material"

    doc_url = "https://mrcmodding.gitbook.io/arma-3-object-builder/properties/material"
    
    @classmethod
    def poll(cls, context):
        return hasattr(context, "material") and context.material
        
    def draw_header(self, context):
        utils.draw_panel_header(self)
        
    def draw(self, context):
        material = context.material
        material_props = material.a3ob_properties_material
        
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        row = layout.row()
        row.prop(material_props, "texture_type", expand=True)
        layout.separator()
        
        texture_type = material_props.texture_type
        if texture_type == 'TEX':
            row_texture = layout.row(align=True)
            row_texture.operator("a3ob.material_autosearch", text="", icon='VIEWZOOM')
            row_texture.prop(material_props, "texture_path", text="", icon='TEXTURE')
        elif texture_type == 'COLOR':
            row_color = layout.row(align=True)
            row_color.prop(material_props, "color_value", icon='COLOR')
            row_color.prop(material_props, "color_type", text="")
        elif texture_type == 'CUSTOM':
            row_raw = layout.row(align=True)
            row_raw.operator("a3ob.paste_common_procedural", text="", icon='PASTEDOWN')
            row_raw.prop(material_props, "color_raw", text="", icon='TEXT')
        
        row_material = layout.row(align=True)
        row_material.operator("a3ob.paste_common_material", text="", icon='PASTEDOWN')
        row_material.prop(material_props, "material_path", text="", icon='MATERIAL')


classes = (
    A3OB_OT_material_autosearch,
    A3OB_OT_paste_common_material,
    A3OB_OT_paste_common_procedural,
    A3OB_UL_common_procedurals,
    A3OB_PT_material,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    print("\t" + "UI: material properties")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    print("\t" + "UI: material properties")
