"""Sidebar panels for Exploded Assembly Studio (3D Viewport, N panel)."""

import bpy
from bpy.types import Panel, UIList

from . import camera, core

CATEGORY = "Exploded"


def format_length(context, value):
    """Format a distance using the scene's own unit settings."""
    settings = context.scene.unit_settings
    try:
        return bpy.utils.units.to_string(
            settings.system, 'LENGTH', value * settings.scale_length, precision=3
        )
    except (RuntimeError, ValueError, TypeError):
        return f"{value:.3f}"


class EAS_UL_camera_poses(UIList):
    """The camera path, one row per captured viewpoint."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        props = context.scene.eas
        start, end = camera.camera_frame_range(props)
        frame = start + item.position * (end - start)
        is_last = index == len(props.camera_poses) - 1

        row = layout.row(align=True)
        row.label(text=f"{index + 1}", icon='CON_CAMERASOLVER')
        row.label(text=f"f{frame:.0f}")
        row.label(text=f"{item.lens:.0f}mm")
        if is_last:
            row.label(text="end")
        else:
            row.label(text=item.motion.title())


class EASPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY


class EAS_PT_main(EASPanel, Panel):
    bl_idname = "EAS_PT_main"
    bl_label = "Exploded Assembly Studio"

    def draw(self, context):
        layout = self.layout
        props = context.scene.eas

        # ----------------------------------------------------------- source
        box = layout.box()
        box.label(text="Source", icon='OUTLINER')
        box.row().prop(props, "source", expand=True)
        if props.source == 'COLLECTION':
            box.prop(props, "collection", text="")

        objects = core.collect_objects(context)
        saved = sum(1 for obj in objects if obj.eas.has_state)
        info = box.row()
        if objects:
            info.label(text=f"{len(objects)} part(s), {saved} with saved state", icon='CHECKMARK')
        else:
            info.label(text="No parts found", icon='ERROR')

        # ------------------------------------------------------------ state
        column = layout.column(align=True)
        column.scale_y = 1.2
        column.operator("eas.set_assembly_position", icon='PINNED')

        row = layout.row(align=True)
        row.scale_y = 1.6
        row.operator("eas.animate", text="EXPLODE", icon='MOD_EXPLODE').mode = 'EXPLODE'
        row.operator("eas.animate", text="ASSEMBLE", icon='MOD_BUILD').mode = 'ASSEMBLE'

        row = layout.row(align=True)
        row.operator("eas.preview", text="Preview Exploded", icon='HIDE_OFF').state = 'EXPLODED'
        row.operator("eas.preview", text="Restore", icon='LOOP_BACK').state = 'ASSEMBLED'

        layout.operator("eas.clear_animation", icon='TRASH')


class EAS_PT_presets(EASPanel, Panel):
    bl_idname = "EAS_PT_presets"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Presets"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        column = layout.column(align=True)
        column.scale_y = 1.1
        column.operator("eas.apply_preset", text="PCB Product", icon='NODE_MATERIAL').preset = 'PCB_STACK'
        column.operator("eas.apply_preset", text="Radial Technical", icon='FULLSCREEN_ENTER').preset = 'RADIAL'
        column.operator("eas.apply_preset", text="Product Showcase", icon='CAMERA_DATA').preset = 'SHOWCASE'
        layout.label(text="Presets overwrite the settings below", icon='INFO')


class EAS_PT_explosion(EASPanel, Panel):
    bl_idname = "EAS_PT_explosion"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Explosion"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.eas

        layout.prop(props, "direction")
        if props.direction != 'CENTER':
            layout.row().prop(props, "axis", expand=True)
        layout.prop(props, "distance")
        layout.prop(props, "magnitude")
        layout.prop(props, "center_mode")
        if props.direction == 'AXIS_SPLIT' and props.center_mode == 'ACTIVE':
            layout.label(text="Active object defines the split plane", icon='INFO')
        if props.direction == 'AXIS_SPLIT' or props.magnitude == 'LAYERED':
            layout.prop(props, "layer_tolerance")
        layout.prop(props, "use_bounds_center")


class EAS_PT_rotation(EASPanel, Panel):
    bl_idname = "EAS_PT_rotation"
    bl_parent_id = "EAS_PT_explosion"
    bl_label = "Rotation"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.eas, "use_rotation", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.eas

        column = layout.column()
        column.active = props.use_rotation
        column.prop(props, "rotation_angle", text="Angle")
        column.row().prop(props, "rotation_axis", expand=True)
        column.prop(props, "rotation_local")


class EAS_PT_sequence(EASPanel, Panel):
    bl_idname = "EAS_PT_sequence"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Sequence"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.eas, "use_sequence", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.eas

        column = layout.column()
        column.active = props.use_sequence
        column.prop(props, "order_mode")
        column.prop(props, "overlap")
        column.prop(props, "reverse_order")
        column.prop(props, "reverse_on_assemble")
        column.operator("eas.auto_order", icon='SORTSIZE')


class EAS_PT_enclosure(EASPanel, Panel):
    bl_idname = "EAS_PT_enclosure"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Enclosure"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.eas, "use_phases", text="")

    def draw(self, context):
        layout = self.layout
        props = context.scene.eas

        block = layout.column()
        block.active = props.use_phases

        info = block.column(align=True)
        info.scale_y = 0.85
        info.label(text="Parts land first, then the shell", icon='INFO')
        info.label(text="closes over them from each side.")

        block.separator()
        row = block.row(align=True)
        row.operator("eas.mark_role", text="Mark Enclosure", icon='MESH_CUBE').role = 'ENCLOSURE'
        row.operator("eas.mark_role", text="Mark Part", icon='MESH_DATA').role = 'PART'
        block.operator("eas.detect_sides", text="Detect Sides", icon='ORIENTATION_NORMAL')

        settings = block.column()
        settings.use_property_split = True
        settings.separator()
        settings.prop(props, "parts_share")
        settings.prop(props, "phase_gap")
        settings.prop(props, "enclosure_distance_factor", text="Shell Distance")

        # Summarise what is currently tagged, so the split is not a mystery.
        objects = core.collect_objects(context)
        panels = [obj for obj in objects if obj.eas.role == 'ENCLOSURE']
        if panels:
            summary = block.box().column(align=True)
            summary.scale_y = 0.85
            summary.label(text=f"{len(panels)} panel(s), {len(objects) - len(panels)} part(s)")
            for obj in panels[:8]:
                side = obj.eas.side
                label = side.title() if side != 'AUTO' else "Auto"
                summary.label(text=f"{obj.name}  -  {label}")
            if len(panels) > 8:
                summary.label(text=f"and {len(panels) - 8} more")
        elif props.use_phases:
            block.label(text="Nothing marked as enclosure yet", icon='ERROR')


class EAS_PT_animation(EASPanel, Panel):
    bl_idname = "EAS_PT_animation"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Animation"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.eas

        column = layout.column(align=True)
        column.prop(props, "frame_start")
        column.prop(props, "frame_end")

        layout.prop(props, "interpolation")
        row = layout.row()
        row.active = props.interpolation not in {'LINEAR', 'BEZIER'}
        row.prop(props, "easing")

        layout.prop(props, "replace_animation")
        layout.prop(props, "set_scene_range")
        layout.prop(props, "auto_store_state")


class EAS_PT_camera(EASPanel, Panel):
    bl_idname = "EAS_PT_camera"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Camera"

    def draw_header(self, context):
        self.layout.prop(context.scene.eas, "use_camera", text="")

    def draw_subject(self, context, column, props):
        picker = column.column(align=True)
        picker.prop(props, "camera_subject", text="Frame")
        row = picker.row(align=True)
        row.use_property_split = False
        row.operator("eas.camera_use_active_subject", icon='EYEDROPPER')

        subject = props.camera_subject
        if subject is None:
            column.label(text="Pick the object to frame, usually the PCB", icon='ERROR')
            return

        column.prop(props, "camera_focal")
        column.prop(props, "camera_margin", text="Framing Margin")

        # Show the distance the camera will choose, so it is not a surprise.
        _, radius = camera.subject_bounds(subject)
        distance = camera.subject_distance(context, subject)
        info = column.box().column(align=True)
        info.scale_y = 0.85
        info.label(text=f"Subject size:  {format_length(context, radius * 2.0)}", icon='FIXED_SIZE')
        info.label(text=f"Camera distance:  {format_length(context, distance)}", icon='DRIVER_DISTANCE')

        column.separator()
        column.prop(props, "camera_start_angle")
        column.prop(props, "camera_orbit")
        column.prop(props, "camera_height")

        column.separator()
        column.prop(props, "camera_use_dolly")
        dolly = column.column(align=True)
        dolly.active = props.camera_use_dolly
        dolly.prop(props, "camera_zoom_start")
        dolly.prop(props, "camera_zoom_end")
        dolly.prop(props, "camera_height_end")

    def draw_orbit(self, context, column, props):
        column.prop(props, "camera_focal")
        column.prop(props, "camera_auto_distance")
        if props.camera_auto_distance:
            column.prop(props, "camera_margin")
        else:
            column.prop(props, "camera_distance")

        column.separator()
        column.prop(props, "camera_start_angle")
        column.prop(props, "camera_orbit")
        column.prop(props, "camera_height")

        column.separator()
        column.prop(props, "camera_use_dolly")
        dolly = column.column(align=True)
        dolly.active = props.camera_use_dolly
        dolly.prop(props, "camera_zoom_start")
        dolly.prop(props, "camera_zoom_end")
        dolly.prop(props, "camera_height_end")

    def draw_poses(self, context, column, props):
        space = context.space_data
        poses = props.camera_poses

        block = column.column()
        block.use_property_split = False

        if not len(poses):
            block.label(text="Frame the shot, then capture it:", icon='INFO')

        row = block.row()
        row.template_list(
            "EAS_UL_camera_poses", "", props, "camera_poses",
            props, "camera_pose_index", rows=3,
        )
        side = row.column(align=True)
        side.operator("eas.camera_capture_pose", text="", icon='ADD').mode = 'APPEND'
        side.operator("eas.camera_pose_remove", text="", icon='REMOVE')
        side.separator()
        side.operator("eas.camera_pose_move", text="", icon='TRIA_UP').direction = 'UP'
        side.operator("eas.camera_pose_move", text="", icon='TRIA_DOWN').direction = 'DOWN'

        row = block.row(align=True)
        row.operator("eas.camera_capture_pose", text="Add From View", icon='KEYFRAME_HLT').mode = 'APPEND'
        sub = row.row(align=True)
        sub.enabled = bool(len(poses))
        sub.operator("eas.camera_capture_pose", text="", icon='FILE_REFRESH').mode = 'REPLACE'
        sub.operator("eas.camera_view_pose", text="", icon='HIDE_OFF').index = -1

        if space is not None and space.type == 'VIEW_3D':
            row = block.row(align=True)
            row.operator("view3d.view_camera", text="Camera View", icon='CAMERA_DATA')
            row.prop(space, "lock_camera", text="Lock To View", toggle=True)

        row = block.row(align=True)
        row.operator("eas.camera_respace_poses", text="Space Evenly", icon='MOD_ARRAY')
        row.operator("eas.camera_clear_poses", text="", icon='X')

        if len(poses) == 1:
            block.label(text="Add one more viewpoint to build a move", icon='ERROR')

        # ---- settings for the active viewpoint -----------------------------
        if len(poses):
            index = min(props.camera_pose_index, len(poses) - 1)
            pose = poses[index]
            is_last = index == len(poses) - 1

            box = column.box().column()
            box.use_property_split = True
            box.label(text=f"Viewpoint {index + 1}", icon='CON_CAMERASOLVER')
            box.prop(pose, "position", text="Time")
            box.prop(pose, "lens", text="Focal Length")
            box.prop(pose, "roll")

            segment = box.column()
            segment.enabled = not is_last
            segment.separator()
            segment.label(text="Segment To Next" if not is_last else "Last viewpoint")
            segment.prop(pose, "motion")
            segment.prop(pose, "interpolation")
            easing_row = segment.row()
            easing_row.active = pose.interpolation not in {'LINEAR', 'BEZIER'}
            easing_row.prop(pose, "easing")

        column.separator()
        column.prop(props, "camera_animate_focal")
        if any(p.motion == 'ARC' for p in poses):
            column.prop(props, "camera_arc_samples")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.eas

        column = layout.column()
        column.active = props.use_camera

        row = column.row()
        row.use_property_split = False
        row.prop(props, "camera_mode", expand=True)
        column.separator()

        if props.camera_mode == 'POSES':
            self.draw_poses(context, column, props)
        elif props.camera_mode == 'SUBJECT':
            self.draw_subject(context, column, props)
        else:
            self.draw_orbit(context, column, props)

        column.separator()
        hold = column.column(align=True)
        hold.prop(props, "camera_delay_start", text="Hold Start")
        hold.prop(props, "camera_delay_end", text="Hold End")
        start, end = camera.camera_frame_range(props)
        low, high = core.frame_range_of(props)
        if props.camera_delay_start or props.camera_delay_end:
            column.label(text=f"Camera moves frames {start:.0f} - {end:.0f} of {low}-{high}",
                         icon='TIME')

        column.separator()
        # Per viewpoint timing replaces these in From Viewport mode.
        if props.camera_mode != 'POSES':
            column.prop(props, "camera_interpolation", text="Interpolation")
            row = column.row()
            row.active = props.camera_interpolation not in {'LINEAR', 'BEZIER'}
            row.prop(props, "camera_easing", text="Easing")
        column.prop(props, "camera_mirror_on_assemble", text="Mirror On Assemble")
        column.prop(props, "camera_set_active")

        column.separator()
        row = column.row(align=True)
        build = row.row(align=True)
        if props.camera_mode == 'POSES':
            build.enabled = props.camera_pose_start_set and props.camera_pose_end_set
            build.operator("eas.camera_setup", text="Apply Camera Move", icon='CON_CAMERASOLVER')
        elif props.camera_mode == 'SUBJECT':
            build.enabled = props.camera_subject is not None
            build.operator("eas.camera_setup", text="Frame Subject", icon='CON_CAMERASOLVER')
        else:
            build.operator("eas.camera_setup", text="Build Rig", icon='CON_CAMERASOLVER')
        row.operator("eas.camera_delete", text="", icon='X')


class EAS_PT_part(EASPanel, Panel):
    bl_idname = "EAS_PT_part"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Active Part"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        obj = context.active_object
        if obj is None:
            layout.label(text="No active object", icon='INFO')
            return

        layout.label(text=obj.name, icon='OBJECT_DATA')
        settings = obj.eas
        layout.prop(settings, "role")
        if settings.role == 'ENCLOSURE':
            layout.prop(settings, "side")
            if settings.side == 'AUTO':
                layout.label(text="Side worked out from its position", icon='INFO')
        layout.prop(settings, "distance_multiplier")
        layout.prop(settings, "order")
        layout.prop(settings, "exclude")

        row = layout.row()
        if settings.has_state:
            row.label(text="Assembly state saved", icon='CHECKMARK')
        else:
            row.label(text="No assembly state", icon='ERROR')

        layout.separator()
        column = layout.column(align=True)
        column.operator("eas.select_parts", icon='RESTRICT_SELECT_OFF')
        column.operator("eas.clear_assembly_state", icon='X')


class EAS_PT_hierarchy(EASPanel, Panel):
    bl_idname = "EAS_PT_hierarchy"
    bl_parent_id = "EAS_PT_main"
    bl_label = "Filtering"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        props = context.scene.eas

        layout.prop(props, "visible_only")
        layout.prop(props, "skip_child_parts")


CLASSES = (
    EAS_UL_camera_poses,
    EAS_PT_main,
    EAS_PT_presets,
    EAS_PT_explosion,
    EAS_PT_rotation,
    EAS_PT_sequence,
    EAS_PT_enclosure,
    EAS_PT_animation,
    EAS_PT_camera,
    EAS_PT_part,
    EAS_PT_hierarchy,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
