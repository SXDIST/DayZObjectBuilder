import traceback
import os
import struct
import uuid

import bpy
import mathutils
from bpy.app.handlers import persistent

from .. import get_icon
from ..utilities import generic as utils
from ..utilities import lod as lodutils
from ..utilities import compat as computils
from ..io import import_p3d


legacy_proxy_preview_prop = "a3ob_proxy_live_preview"
proxy_preview_owner_prop = "a3ob_proxy_live_preview_owner"
proxy_preview_owner_key_prop = "a3ob_proxy_live_preview_owner_key"
proxy_preview_object_prop = "a3ob_proxy_live_preview_object"
proxy_preview_path_prop = "a3ob_proxy_live_preview_path"
proxy_owner_key_prop = "a3ob_proxy_live_preview_key"
proxy_preview_collection = "A3OB Live Proxy Preview"
proxy_preview_syncing = False


class ProxyLivePreviewSettings:
    enclose = False
    groupby = 'NONE'
    additional_data_allowed = True
    additional_data = {'NORMALS', 'UV', 'MATERIALS'}
    validate_meshes = True
    proxy_action = 'NOTHING'
    first_lod_only = True
    translate_selections = False
    cleanup_empty_selections = False
    sections = 'PRESERVE'
    absolute_paths = True

    def __init__(self, filepath):
        self.filepath = filepath


def get_selected_proxies(context):
    return [obj for obj in context.selected_objects if obj.type == 'MESH' and obj.mode == 'OBJECT' and obj.a3ob_properties_object_proxy.is_a3_proxy]


def is_valid_proxy_path(obj):
    path = utils.abspath(obj.a3ob_properties_object_proxy.proxy_path)
    return os.path.exists(path) and os.path.splitext(path)[1].lower() == '.p3d'


def get_proxy_preview_matrix(obj):
    location, rotation, _scale = obj.matrix_world.decompose()
    return mathutils.Matrix.Translation(location) @ rotation.to_matrix().to_4x4()


def is_transform_only_update(depsgraph):
    updates = list(depsgraph.updates)

    if len(updates) == 0:
        return False

    for update in updates:
        if not isinstance(update.id, bpy.types.Object):
            return False

        if not update.is_updated_transform:
            return False

        if getattr(update, "is_updated_geometry", False):
            return False

        if getattr(update, "is_updated_shading", False):
            return False

    return True


def sync_missing_previews_from_updates(context, depsgraph):
    if proxy_preview_syncing or not context or not context.scene:
        return

    if not hasattr(context.scene, "a3ob_proxies") or not context.scene.a3ob_proxies.live_preview:
        return

    for update in depsgraph.updates:
        obj = update.id
        if not isinstance(obj, bpy.types.Object):
            continue

        if obj.type != 'MESH' or not obj.a3ob_properties_object_proxy.is_a3_proxy:
            continue

        if get_preview_for_owner(obj) or not is_valid_proxy_path(obj):
            continue

        sync_live_preview_for_owner(context, obj)


def ensure_proxy_preview_key(obj):
    key = obj.get(proxy_owner_key_prop)

    if not key:
        key = uuid.uuid4().hex
        obj[proxy_owner_key_prop] = key

    return key


def find_proxy_owner(preview):
    for name in ("A3OB Live Proxy Location", "A3OB Live Proxy Rotation"):
        constraint = preview.constraints.get(name)
        if not constraint or not constraint.target:
            continue

        owner = constraint.target
        if owner.a3ob_properties_object_proxy.is_a3_proxy:
            ensure_proxy_preview_key(owner)
            preview[proxy_preview_owner_prop] = owner.name
            preview[proxy_preview_owner_key_prop] = owner.get(proxy_owner_key_prop)
            owner[proxy_preview_object_prop] = preview.name
            return owner

    owner_name = preview.get(proxy_preview_owner_prop)
    owner = bpy.data.objects.get(owner_name)

    if owner and owner.a3ob_properties_object_proxy.is_a3_proxy:
        ensure_proxy_preview_key(owner)
        preview[proxy_preview_owner_key_prop] = owner.get(proxy_owner_key_prop)
        owner[proxy_preview_object_prop] = preview.name
        return owner

    return None


def preview_targets_owner(preview, owner):
    if not preview or not preview.get(legacy_proxy_preview_prop):
        return False

    for name in ("A3OB Live Proxy Location", "A3OB Live Proxy Rotation"):
        constraint = preview.constraints.get(name)
        if constraint and constraint.target == owner:
            return True

    return False


def get_preview_for_owner(owner):
    preview_name = owner.get(proxy_preview_object_prop)
    preview = bpy.data.objects.get(preview_name)

    if preview_targets_owner(preview, owner):
        return preview

    if preview_name:
        try:
            del owner[proxy_preview_object_prop]
        except Exception:
            pass

    owner_key = ensure_proxy_preview_key(owner)
    collection = bpy.data.collections.get(proxy_preview_collection)
    if not collection:
        return None

    for obj in collection.objects:
        if obj.get(legacy_proxy_preview_prop) and obj.get(proxy_preview_owner_key_prop) == owner_key and preview_targets_owner(obj, owner):
            owner[proxy_preview_object_prop] = obj.name
            return obj

    if owner_key:
        owner[proxy_owner_key_prop] = uuid.uuid4().hex

    return None


def get_preview_collection(context):
    collection = bpy.data.collections.get(proxy_preview_collection)

    if collection is None:
        collection = bpy.data.collections.new(proxy_preview_collection)
        collection.hide_render = True
        try:
            collection.hide_select = True
        except Exception:
            pass

    if context.scene.collection.children.get(collection.name) is None:
        context.scene.collection.children.link(collection)

    return collection


def remove_preview_object(obj):
    mesh = obj.data if obj.type == 'MESH' else None
    material_names = [material.name for material in mesh.materials if material] if mesh else []

    bpy.data.objects.remove(obj, do_unlink=True)

    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)

    for name in material_names:
        material = bpy.data.materials.get(name)
        if material and material.users == 0:
            bpy.data.materials.remove(material)


def ensure_preview_constraints(preview, proxy_object):
    constraint = preview.constraints.get("A3OB Live Proxy Location")
    if constraint is None:
        constraint = preview.constraints.new(type='COPY_LOCATION')
        constraint.name = "A3OB Live Proxy Location"

    constraint.target = proxy_object
    constraint.owner_space = 'WORLD'
    constraint.target_space = 'WORLD'

    constraint = preview.constraints.get("A3OB Live Proxy Rotation")
    if constraint is None:
        constraint = preview.constraints.new(type='COPY_ROTATION')
        constraint.name = "A3OB Live Proxy Rotation"

    constraint.target = proxy_object
    constraint.owner_space = 'WORLD'
    constraint.target_space = 'WORLD'


def clear_legacy_preview_objects():
    collection = bpy.data.collections.get(proxy_preview_collection)
    objects = list(collection.objects) if collection else []

    for obj in objects:
        if not obj.get(legacy_proxy_preview_prop):
            continue

        remove_preview_object(obj)


def clear_live_previews():
    global proxy_preview_syncing

    proxy_preview_syncing = True
    try:
        clear_legacy_preview_objects()

        collection = bpy.data.collections.get(proxy_preview_collection)
        if collection and len(collection.objects) == 0:
            for scene in bpy.data.scenes:
                if scene.collection.children.get(collection.name):
                    scene.collection.children.unlink(collection)
            bpy.data.collections.remove(collection)

    finally:
        proxy_preview_syncing = False


def sync_live_preview(context, preview, owner):
    global proxy_preview_syncing

    current_path = utils.abspath(owner.a3ob_properties_object_proxy.proxy_path)

    preview.hide_set(owner.hide_get())
    preview.hide_viewport = owner.hide_viewport
    preview.scale = mathutils.Vector((1, 1, 1))
    ensure_preview_constraints(preview, owner)

    if preview.get(proxy_preview_path_prop) == current_path:
        return

    proxy_preview_syncing = True
    try:
        remove_preview_object(preview)

        if is_valid_proxy_path(owner):
            load_live_preview(context, owner)
    finally:
        proxy_preview_syncing = False


def sync_live_preview_for_owner(context, owner):
    global proxy_preview_syncing

    if proxy_preview_syncing or not context or not context.scene:
        return

    if not hasattr(context.scene, "a3ob_proxies"):
        return

    preview = get_preview_for_owner(owner)

    if preview:
        sync_live_preview(context, preview, owner)
    elif context.scene.a3ob_proxies.live_preview and is_valid_proxy_path(owner):
        proxy_preview_syncing = True
        try:
            load_live_preview(context, owner)
        finally:
            proxy_preview_syncing = False


def cleanup_live_preview_for_preview(preview):
    owner = find_proxy_owner(preview)

    if owner and owner.a3ob_properties_object_proxy.is_a3_proxy:
        return owner

    remove_preview_object(preview)
    return None


def remove_empty_preview_collection():
    collection = bpy.data.collections.get(proxy_preview_collection)
    if collection and len(collection.objects) == 0:
        for item_scene in bpy.data.scenes:
            if item_scene.collection.children.get(collection.name):
                item_scene.collection.children.unlink(collection)
        bpy.data.collections.remove(collection)


@persistent
def depsgraph_update_post_handler(scene, depsgraph):
    if is_transform_only_update(depsgraph):
        sync_missing_previews_from_updates(bpy.context, depsgraph)
        return

    if proxy_preview_syncing:
        return

    context = bpy.context
    for update in depsgraph.updates:
        obj = update.id
        if not isinstance(obj, bpy.types.Object):
            continue

        if obj.get(legacy_proxy_preview_prop):
            owner = cleanup_live_preview_for_preview(obj)
            if owner:
                sync_live_preview(context, obj, owner)
            continue

        if obj.type == 'MESH' and obj.a3ob_properties_object_proxy.is_a3_proxy:
            sync_live_preview_for_owner(context, obj)

    remove_empty_preview_collection()


def setup_preview_object(context, preview, proxy_object):
    scene_props = context.scene.a3ob_proxies
    collection = get_preview_collection(context)
    name = "proxy preview: %s" % proxy_object.a3ob_properties_object_proxy.get_name()
    filepath = utils.abspath(proxy_object.a3ob_properties_object_proxy.proxy_path)
    owner_key = ensure_proxy_preview_key(proxy_object)

    preview.name = name
    preview.data.name = name
    preview.parent = None
    preview.matrix_parent_inverse = mathutils.Matrix.Identity(4)
    preview.matrix_world = get_proxy_preview_matrix(proxy_object)
    preview.scale = mathutils.Vector((1, 1, 1))
    ensure_preview_constraints(preview, proxy_object)
    preview.display_type = scene_props.live_preview_mode
    preview.show_in_front = False
    preview.show_name = False
    preview.hide_select = True
    preview.hide_render = True
    preview.a3ob_properties_object.is_a3_lod = False
    preview[legacy_proxy_preview_prop] = True
    preview[proxy_preview_owner_prop] = proxy_object.name
    preview[proxy_preview_owner_key_prop] = owner_key
    preview[proxy_preview_path_prop] = filepath
    proxy_object[proxy_preview_object_prop] = preview.name

    proxy_object.show_name = True

    if collection.objects.get(preview.name) is None:
        collection.objects.link(preview)

    for item in list(preview.users_collection):
        if item != collection:
            item.objects.unlink(preview)


def restore_selection(context, selected, active):
    bpy.ops.object.select_all(action='DESELECT')

    for obj in selected:
        if context.scene.objects.get(obj.name):
            obj.select_set(True)

    if active and context.scene.objects.get(active.name):
        context.view_layer.objects.active = active


def load_live_preview(context, proxy_object):
    filepath = utils.abspath(proxy_object.a3ob_properties_object_proxy.proxy_path)
    settings = ProxyLivePreviewSettings(filepath)
    selected = [obj for obj in context.selected_objects if not obj.get(legacy_proxy_preview_prop)]
    active = context.active_object
    if active and active.get(legacy_proxy_preview_prop):
        active = None

    with utils.open_long(filepath, "rb") as file:
        lod_objects = import_p3d.read_file(settings, context, file)

    if len(lod_objects) == 0:
        restore_selection(context, selected, active)
        return None

    preview = lod_objects[0]
    setup_preview_object(context, preview, proxy_object)

    for obj in lod_objects[1:]:
        remove_preview_object(obj)

    restore_selection(context, selected, active)

    return preview


def rebuild_live_previews(context):
    proxies = get_selected_proxies(context)
    loaded = 0
    skipped = 0

    clear_live_previews()

    for proxy_object in proxies:
        if not is_valid_proxy_path(proxy_object):
            skipped += 1
            continue

        try:
            preview = load_live_preview(context, proxy_object)
            if preview:
                loaded += 1
        except struct.error:
            skipped += 1
            traceback.print_exc()
        except Exception:
            skipped += 1
            traceback.print_exc()

    return loaded, skipped


class A3OB_OT_proxy_realign_ocs(bpy.types.Operator):
    """Realign the proxy object coordinate system with proxy directions"""
    
    bl_idname = "a3ob.proxy_realign_ocs"
    bl_label = "Realign Coordinate System"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        proxies = get_selected_proxies(context)
        return len(proxies) > 0 and len(proxies) == len(context.selected_objects)
    
    def execute(self, context):
        for obj in get_selected_proxies(context):
            import_p3d.transform_proxy(obj)
            
        return {'FINISHED'}


class A3OB_OT_proxy_live_preview_toggle(bpy.types.Operator):
    """Toggle non-selectable proxy preview meshes"""

    bl_idname = "a3ob.proxy_live_preview_toggle"
    bl_label = "Live Editing"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.scene is None:
            return False

        if context.scene.a3ob_proxies.live_preview:
            return True

        return len(get_selected_proxies(context)) > 0

    def execute(self, context):
        scene_props = context.scene.a3ob_proxies

        if scene_props.live_preview:
            clear_live_previews()
            scene_props.live_preview = False
            return {'FINISHED'}

        loaded, skipped = rebuild_live_previews(context)
        scene_props.live_preview = True

        if loaded:
            self.report({'INFO'}, "Live editing loaded %d proxy preview(s)" % loaded)
        if skipped:
            self.report({'WARNING'}, "Live editing skipped %d proxy preview(s)" % skipped)

        return {'FINISHED'}


class A3OB_OT_proxy_live_preview_refresh(bpy.types.Operator):
    """Refresh non-selectable proxy preview meshes"""

    bl_idname = "a3ob.proxy_live_preview_refresh"
    bl_label = "Refresh Live Editing"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.scene.a3ob_proxies.live_preview and len(get_selected_proxies(context)) > 0

    def execute(self, context):
        loaded, skipped = rebuild_live_previews(context)
        context.scene.a3ob_proxies.live_preview = True

        if loaded:
            self.report({'INFO'}, "Live editing refreshed %d proxy preview(s)" % loaded)
        if skipped:
            self.report({'WARNING'}, "Live editing skipped %d proxy preview(s)" % skipped)

        return {'FINISHED'}


class A3OB_OT_proxy_align(bpy.types.Operator):
    """Align the proxy object to another selected object"""
    
    bl_idname = "a3ob.proxy_align"
    bl_label = "Align To Object"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        selected = context.selected_objects
        
        if not obj or len(selected) != 2:
            return False
            
        selected.remove(obj)
        return obj.mode == 'OBJECT' and selected[0] and selected[0].mode == 'OBJECT' and selected[0].a3ob_properties_object_proxy.is_a3_proxy
    
    def execute(self, context):
        obj = context.active_object
        selected = context.selected_objects.copy()
        selected.remove(obj)
        proxy = selected[0]
        
        proxy.matrix_world = obj.matrix_world
        proxy.scale = mathutils.Vector((1, 1, 1))
                    
        return {'FINISHED'}


class A3OB_OT_proxy_align_object(bpy.types.Operator):
    """Align an object to a selected proxy object"""
    
    bl_idname = "a3ob.proxy_align_object"
    bl_label = "Align To Proxy"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        selected = context.selected_objects
        
        if not obj or len(selected) != 2:
            return False
            
        selected.remove(obj)
        return obj.mode == 'OBJECT' and obj.a3ob_properties_object_proxy.is_a3_proxy and selected[0] and selected[0].mode == 'OBJECT'
    
    def execute(self, context):
        proxy = context.active_object
        selected = context.selected_objects.copy()
        selected.remove(proxy)
        obj = selected[0]
        
        obj.matrix_world = proxy.matrix_world
        obj.scale = mathutils.Vector((1, 1, 1))
                    
        return {'FINISHED'}


class A3OB_OT_proxy_extract(bpy.types.Operator):
    """Import 1st LOD of proxy model in place of proxy object"""
    
    bl_idname = "a3ob.proxy_extract"
    bl_label = "Extract Proxy"
    bl_options = {'REGISTER', 'UNDO'}
    
    enclose: bpy.props.BoolProperty()
    groupby: bpy.props.EnumProperty(default='NONE', items=(('NONE', "", ""),))
    additional_data_allowed: bpy.props.BoolProperty(default=True)
    additional_data: bpy.props.EnumProperty(
        options = {'ENUM_FLAG'},
        items = (
            ('NORMALS', "", ""),
            ("FLAGS", "", ""),
            ('PROPS', "", ""),
            ('MASS', "", ""),
            ('SELECTIONS', "", ""),
            ('UV', "", ""),
            ('MATERIALS', "", "")
        ),
        default = {'NORMALS', 'PROPS', 'MASS', 'SELECTIONS', 'UV', 'MATERIALS'}
    )
    validate_meshes: bpy.props.BoolProperty(default=True)
    proxy_action: bpy.props.EnumProperty(items=(('SEPARATE', "", ""),), default='SEPARATE')
    first_lod_only: bpy.props.BoolProperty(default=True)
    translate_selections: bpy.props.BoolProperty()
    cleanup_empty_selections: bpy.props.BoolProperty()
    sections: bpy.props.EnumProperty(items=(("PRESERVE", "", ""),), default="PRESERVE")
    absolute_paths: bpy.props.BoolProperty(default=True)
    filepath: bpy.props.StringProperty()
    
    @classmethod
    def poll(cls, context):
        proxies = get_selected_proxies(context)
        return len(proxies) > 0 and len(proxies) == len(context.selected_objects) and all(is_valid_proxy_path(obj) for obj in proxies)
    
    def execute(self, context):
        extracted = 0
        proxies = get_selected_proxies(context)

        for proxy_object in proxies:
            self.filepath = utils.abspath(proxy_object.a3ob_properties_object_proxy.proxy_path)

            try:
                with utils.open_long(self.filepath, "rb") as file:
                    matrix_world = proxy_object.matrix_world.copy()
                    lod_objects = import_p3d.read_file(self, context, file)
                    imported_object = lod_objects[0]
                    imported_object.matrix_world = matrix_world
                    imported_object.name = os.path.basename(self.filepath)
                    imported_object.data.name = os.path.basename(self.filepath)
                    bpy.data.meshes.remove(proxy_object.data)
                    extracted += 1
            except struct.error as ex:
                self.report({'ERROR'}, "Unexpected EndOfFile (check the system console)")
                traceback.print_exc()
            except Exception as ex:
                self.report({'ERROR'}, "%s (check the system console)" % ex)
                traceback.print_exc()

        if extracted:
            self.report({'INFO'}, "Successfully extracted %d proxy object(s) (check the logs in the system console)" % extracted)
        
        return {'FINISHED'}


class A3OB_OT_proxy_copy(bpy.types.Operator):
    """Copy proxy to LOD objects"""
    
    bl_idname = "a3ob.proxy_copy"
    bl_label = "Copy Proxy"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.mode == 'OBJECT' and len(context.selected_objects) == 1 and obj.type == 'MESH' and obj.a3ob_properties_object_proxy.is_a3_proxy
    
    def invoke(self, context, event):
        scene_props = context.scene.a3ob_proxies
        scene_props.lod_objects.clear()
        
        object_pool = context.scene.objects
        
        proxy_object = context.active_object
        parent_object = proxy_object.parent
        
        for obj in context.scene.objects:
            if obj.type != 'MESH' or not obj.a3ob_properties_object.is_a3_lod or obj.parent != None or obj == parent_object:
                continue
            
            object_props = obj.a3ob_properties_object
            
            item = scene_props.lod_objects.add()
            item.name = obj.name
            item.lod = lodutils.format_lod_name(int(object_props.lod), object_props.resolution)
            
            scene_props.lod_objects_index = len(scene_props.lod_objects) - 1
            
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        scene_props = context.scene.a3ob_proxies
        layout = self.layout
        split = layout.split(factor=0.5)
        split.label(text="Object Name")
        split.label(text="LOD Type")
        layout.template_list("A3OB_UL_lod_objects_selector", "A3OB_proxies_copy", scene_props, "lod_objects", scene_props, "lod_objects_index")
    
    def execute(self, context):
        proxy_object = context.active_object
        scene = context.scene
        scene_props = scene.a3ob_proxies
        
        target_objects = [scene.objects[item.name] for item in scene_props.lod_objects if item.enabled]
        
        for obj in target_objects:
            new_proxy = proxy_object.copy()
            new_proxy.data = proxy_object.data.copy()
            
            obj.users_collection[0].objects.link(new_proxy)
            new_proxy.matrix_parent_inverse = obj.matrix_world.inverted()
            new_proxy.parent = obj
        
        return {'FINISHED'}


class A3OB_OT_proxy_copy_all(bpy.types.Operator):
    """Copy all proxies from a LOD object to another"""
    
    bl_idname = "a3ob.proxy_copy_all"
    bl_label = "Copy Proxies"
    bl_options = {'REGISTER', 'UNDO'}
    
    keep_transform: bpy.props.BoolProperty(
        name = "Keep Transformation",
        description = "Keep the visual world space transformations",
        default = True
    )
    
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        selected = [item for item in context.selected_objects if item.type == 'MESH' and item.mode == 'OBJECT' and item != obj and item.a3ob_properties_object.is_a3_lod]
        
        return obj and obj.type == 'MESH' and obj.mode == 'OBJECT' and obj.a3ob_properties_object.is_a3_lod and len(selected) == 1
    
    def execute(self, context):
        target = context.active_object
        source = [item for item in context.selected_objects if item.type == 'MESH' and item.mode == 'OBJECT' and item != target][0]
        proxies = [item for item in source.children if item.type == 'MESH' and item.a3ob_properties_object_proxy.is_a3_proxy]
        
        for item in proxies:
            new_proxy = item.copy()
            new_proxy.data = item.data.copy()
            target.users_collection[0].objects.link(new_proxy)
            ctx = {
                "selected_editable_objects": [new_proxy]
            }
            if self.keep_transform:
                computils.call_operator_ctx(bpy.ops.object.parent_clear, ctx, type='CLEAR_KEEP_TRANSFORM')
                ctx.update({
                    "active_object": target,
                    "selected_objects": [target, new_proxy],
                    "selected_editable_objects": [target, new_proxy]
                })
                computils.call_operator_ctx(bpy.ops.object.parent_set, ctx, type='OBJECT', keep_transform=True)
            else:
                computils.call_operator_ctx(bpy.ops.object.parent_clear, ctx)
                ctx.update({
                    "active_object": target,
                    "selected_objects": [target, new_proxy],
                    "selected_editable_objects": [target, new_proxy]
                })
                computils.call_operator_ctx(bpy.ops.object.parent_set, ctx, type='OBJECT')
        
        return {'FINISHED'}


class A3OB_OT_proxy_transfer(bpy.types.Operator):
    """Transfer proxies to a different LOD object"""
    
    bl_idname = "a3ob.proxy_transfer"
    bl_label = "Transfer Proxies"
    bl_options = {'REGISTER', 'UNDO'}
    
    keep_transform: bpy.props.BoolProperty(
        name = "Keep Transformation",
        description = "Keep the visual world space transformations",
        default = True
    )
    
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        selected = [item for item in context.selected_objects if item.type == 'MESH' and item.mode == 'OBJECT' and item != obj and item.a3ob_properties_object.is_a3_lod]
        
        return obj and obj.type == 'MESH' and obj.mode == 'OBJECT' and obj.a3ob_properties_object.is_a3_lod and len(selected) == 1
    
    def execute(self, context):
        target = context.active_object
        source = [item for item in context.selected_objects if item.type == 'MESH' and item.mode == 'OBJECT' and item != target][0]
        proxies = [item for item in source.children if item.type == 'MESH' and item.a3ob_properties_object_proxy.is_a3_proxy]
        
        for item in proxies:
            ctx = {
                "selected_editable_objects": [item]
            }
            if self.keep_transform:
                computils.call_operator_ctx(bpy.ops.object.parent_clear, ctx, type='CLEAR_KEEP_TRANSFORM')
                ctx.update({
                    "active_object": target,
                    "selected_objects": [target, item],
                    "selected_editable_objects": [target, item]
                })
                computils.call_operator_ctx(bpy.ops.object.parent_set, ctx, type='OBJECT', keep_transform=True)
            else:
                computils.call_operator_ctx(bpy.ops.object.parent_clear, ctx)
                ctx.update({
                    "active_object": target,
                    "selected_objects": [target, item],
                    "selected_editable_objects": [target, item]
                })
                computils.call_operator_ctx(bpy.ops.object.parent_set, ctx, type='OBJECT')
        
        return {'FINISHED'}
    

class A3OB_PT_proxies(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Object Builder"
    bl_label = "Proxies"
    bl_options = {'DEFAULT_CLOSED'}

    doc_url = "https://mrcmodding.gitbook.io/arma-3-object-builder/tools/proxies"
    
    @classmethod
    def poll(cls, context):
        return True
        
    def draw_header(self, context):
        utils.draw_panel_header(self)
        
    def draw(self, context):
        layout = self.layout
        scene_props = context.scene.a3ob_proxies

        row_live = layout.row(align=True)
        row_live.operator("a3ob.proxy_live_preview_toggle", icon='HIDE_OFF', depress=scene_props.live_preview)
        row_live.operator("a3ob.proxy_live_preview_refresh", text="", icon_value=get_icon("op_refresh"))

        row_mode = layout.row(align=True)
        row_mode.prop(scene_props, "live_preview_mode", expand=True)
        
        col_align = layout.column(align=True)
        col_align.operator("a3ob.proxy_align", icon_value=get_icon("op_proxy_align"))
        col_align.operator("a3ob.proxy_align_object", icon_value=get_icon("op_proxy_align_object"))
        layout.operator("a3ob.proxy_realign_ocs", icon_value=get_icon("op_proxy_realign"))
        layout.operator("a3ob.proxy_extract", icon_value=get_icon("op_proxy_extract"))
        col_move = layout.column(align=True)
        col_move.operator("a3ob.proxy_copy", icon_value=get_icon("op_proxy_copy"))
        col_move.operator("a3ob.proxy_copy_all", icon_value=get_icon("op_proxy_copy_all"))
        col_move.operator("a3ob.proxy_transfer", icon_value=get_icon("op_proxy_transfer"))


class A3OB_UL_lod_objects_selector(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.name)
        row.label(text=item.lod)


classes = (
    A3OB_OT_proxy_align,
    A3OB_OT_proxy_align_object,
    A3OB_OT_proxy_realign_ocs,
    A3OB_OT_proxy_extract,
    A3OB_OT_proxy_live_preview_toggle,
    A3OB_OT_proxy_live_preview_refresh,
    A3OB_OT_proxy_copy,
    A3OB_OT_proxy_copy_all,
    A3OB_OT_proxy_transfer,
    A3OB_PT_proxies,
    A3OB_UL_lod_objects_selector
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if depsgraph_update_post_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_update_post_handler)
    
    print("\t" + "UI: Proxies")


def unregister():
    clear_live_previews()

    if depsgraph_update_post_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_update_post_handler)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    print("\t" + "UI: Proxies")
