"""Operators for Exploded Assembly Studio."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator

from . import camera as camera_module
from . import core

ANIMATION_GROUP = "Exploded Assembly"


def _object_mode(context):
    return context.mode == 'OBJECT'


def _camera_not_ready(props):
    """Why the camera cannot be built yet, or an empty string when it can."""
    if props.camera_mode == 'POSES' and not camera_module.poses_ready(props):
        return "capture at least two viewpoints in the Camera panel first"
    if props.camera_mode == 'SUBJECT' and props.camera_subject is None:
        return "pick the object to frame in the Camera panel first"
    return ""


def _framing_for(context, parts, center):
    """Resolve the camera framing, ignoring panels that get parked off camera.

    A shell panel sent far out of frame should not drag the camera back with
    it, so it is left out of the bounds the framing is measured from.
    """
    props = context.scene.eas
    skip = None
    if props.use_phases and props.enclosure_offscreen:
        skip = {
            part.obj.name for part in parts
            if core.is_enclosure(props, part.obj)
        }

    exploded = {part.obj.name: part.parent @ part.basis_exploded for part in parts}
    radius = max(
        core.assembly_radius(parts, center, skip=skip),
        core.assembly_radius(parts, center, exploded, skip=skip),
    )
    return camera_module.resolve_framing(context, center, radius)


def _no_parts_message(props):
    if props.source == 'COLLECTION':
        if props.collection is None:
            return "Pick a collection first"
        return "The collection has no usable objects"
    return "Select the assembly parts first"


class EAS_OT_set_assembly_position(Operator):
    """Record the current transform of every source part as the assembled state"""

    bl_idname = "eas.set_assembly_position"
    bl_label = "Set Assembly Position"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        props = context.scene.eas
        objects = core.collect_objects(context)
        if not objects:
            self.report({'ERROR'}, _no_parts_message(props))
            return {'CANCELLED'}

        for obj in objects:
            core.store_state(obj)

        self.report({'INFO'}, f"Assembly position saved for {len(objects)} part(s)")
        return {'FINISHED'}


class EAS_OT_clear_assembly_state(Operator):
    """Forget the recorded assembled state of the source parts"""

    bl_idname = "eas.clear_assembly_state"
    bl_label = "Clear Assembly State"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        objects = core.collect_objects(context)
        for obj in objects:
            obj.eas.has_state = False
        self.report({'INFO'}, f"Cleared state on {len(objects)} part(s)")
        return {'FINISHED'}


class EAS_OT_preview(Operator):
    """Jump the parts to a state without creating any keyframes"""

    bl_idname = "eas.preview"
    bl_label = "Preview"
    bl_options = {'REGISTER', 'UNDO'}

    state: EnumProperty(
        name="State",
        items=[
            ('EXPLODED', "Exploded", "Move parts to the exploded position"),
            ('ASSEMBLED', "Assembled", "Move parts back to the saved assembly position"),
        ],
        default='EXPLODED',
    )

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        props = context.scene.eas
        parts, stored = core.build_parts(context)
        if not parts:
            self.report({'ERROR'}, _no_parts_message(props))
            return {'CANCELLED'}

        if self.state == 'EXPLODED':
            core.compute_explosion(context, parts)
            for part in parts:
                core.apply_basis(part.obj, part.basis_exploded)

        animated = [part.obj.name for part in parts if core.iter_fcurves(part.obj)]
        if animated:
            self.report(
                {'WARNING'},
                "Preview applied, but existing keyframes will override it on the next frame change",
            )
        else:
            self.report({'INFO'}, f"{self.state.title()} preview on {len(parts)} part(s)")
        return {'FINISHED'}


class EAS_OT_animate(Operator):
    """Build the explode or assemble animation"""

    bl_idname = "eas.animate"
    bl_label = "Animate"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=[
            ('EXPLODE', "Explode", "Assembled at the start frame, exploded at the end frame"),
            ('ASSEMBLE', "Assemble", "Exploded at the start frame, assembled at the end frame"),
        ],
        default='EXPLODE',
    )

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        props = context.scene.eas
        scene = context.scene

        parts, stored = core.build_parts(context)
        if not parts:
            self.report({'ERROR'}, _no_parts_message(props))
            return {'CANCELLED'}

        center = core.compute_explosion(context, parts)

        # Measure the camera framing now, while the scene is still at the
        # assembled pose and in sync. Writing keyframes below leaves
        # matrix_world stale, which would measure the subject in the wrong spot.
        camera_framing = None
        camera_problem = _camera_not_ready(props) if props.use_camera else ""
        if props.use_camera and not camera_problem:
            camera_framing = _framing_for(context, parts, center)

        # Enclosure panels are placed against the camera, and the camera frames
        # the product without them, so the two are resolved in that order.
        if props.use_phases and (props.enclosure_offscreen or props.enclosure_avoid_camera):
            framing = camera_framing or _framing_for(context, parts, center)
            info = camera_module.camera_info(context, *framing)
            core.apply_enclosure_camera_rules(context, parts, center, info, camera_module)

        mirror = self.mode == 'ASSEMBLE' and props.reverse_on_assemble
        ordered = core.order_parts(context, parts, reverse=mirror)
        count = len(ordered)

        rotate = props.use_rotation and abs(props.rotation_angle) > core.EPSILON

        if props.replace_animation:
            for part in ordered:
                core.clear_transform_animation(part.obj)

        start, end = core.frame_range_of(props)
        timing = core.build_timing(props, ordered)

        for part in ordered:
            obj = part.obj
            if self.mode == 'EXPLODE':
                first, last = part.basis_assembled, part.basis_exploded
            else:
                first, last = part.basis_exploded, part.basis_assembled

            part_start, part_end = timing[obj.name]

            core.apply_basis(obj, first)
            core.key_transform(obj, part_start, rotate, ANIMATION_GROUP)
            core.apply_basis(obj, last)
            core.key_transform(obj, part_end, rotate, ANIMATION_GROUP)

            core.apply_interpolation(obj, props.interpolation, props.easing)

        if camera_problem:
            self.report({'WARNING'}, f"Camera skipped: {camera_problem}")
        elif camera_framing is not None:
            # The start framing means the first frame of whatever is being
            # built. Only mirror it when the user explicitly asks, for stitching
            # a rendered Explode and Assemble pass together.
            mirror_camera = self.mode == 'ASSEMBLE' and props.camera_mirror_on_assemble
            camera_module.animate(context, *camera_framing, reverse=mirror_camera)

        if props.set_scene_range:
            scene.frame_start = start
            scene.frame_end = end

        scene.frame_set(start)

        verb = "Explode" if self.mode == 'EXPLODE' else "Assemble"
        extra = f", {stored} state(s) auto saved" if stored else ""
        self.report({'INFO'}, f"{verb} animation built for {count} part(s), frames {start}-{end}{extra}")
        return {'FINISHED'}


class EAS_OT_clear_animation(Operator):
    """Remove the generated transform keyframes and return the parts to the assembly position"""

    bl_idname = "eas.clear_animation"
    bl_label = "Clear Animation"
    bl_options = {'REGISTER', 'UNDO'}

    include_camera: BoolProperty(
        name="Include Camera Rig",
        description="Also clear the generated camera animation",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        objects = core.collect_objects(context)
        if not objects:
            self.report({'ERROR'}, _no_parts_message(context.scene.eas))
            return {'CANCELLED'}

        removed = 0
        for obj in objects:
            removed += core.clear_transform_animation(obj)

        core.restore_assembled(objects)

        if self.include_camera:
            camera_module.clear_camera_animation(context)

        self.report({'INFO'}, f"Removed {removed} channel(s) and restored {len(objects)} part(s)")
        return {'FINISHED'}


class EAS_OT_auto_order(Operator):
    """Write the computed move order into each part, then switch to Manual so it can be tweaked"""

    bl_idname = "eas.auto_order"
    bl_label = "Bake Order To Parts"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        props = context.scene.eas
        parts, _ = core.build_parts(context)
        if not parts:
            self.report({'ERROR'}, _no_parts_message(props))
            return {'CANCELLED'}

        core.compute_explosion(context, parts)
        ordered = core.order_parts(context, parts)
        for index, part in enumerate(ordered):
            part.obj.eas.order = index

        props.order_mode = 'MANUAL'
        self.report({'INFO'}, f"Order baked onto {len(ordered)} part(s)")
        return {'FINISHED'}


class EAS_OT_select_parts(Operator):
    """Select every object that has a saved assembly state"""

    bl_idname = "eas.select_parts"
    bl_label = "Select Saved Parts"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        count = 0
        for obj in context.view_layer.objects:
            if obj.eas.has_state and not obj.eas.is_rig:
                if obj.visible_get():
                    obj.select_set(True)
                    count += 1
            else:
                obj.select_set(False)
        self.report({'INFO'}, f"Selected {count} part(s)")
        return {'FINISHED'}


class EAS_OT_apply_preset(Operator):
    """Set the explosion, sequence and camera options for a common look"""

    bl_idname = "eas.apply_preset"
    bl_label = "Apply Preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Preset",
        items=[
            ('PCB_STACK', "PCB Product",
             "Layered vertical build up: bottom shell drops in from below, PCB stays, components and "
             "top shell come down from above"),
            ('RADIAL', "Radial Technical",
             "Even radial spread from the assembly center, all parts together"),
            ('SHOWCASE', "Product Showcase",
             "Staggered radial explosion with a spin and a slow orbiting camera"),
        ],
        default='PCB_STACK',
    )

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def _auto_distance(self, context, fallback):
        """Pick a distance that suits the size of the current assembly."""
        objects = core.collect_objects(context)
        if not objects:
            return fallback
        parts, _ = core.build_parts(context, objects, store_missing=False)
        if not parts:
            return fallback
        center = core.assembly_center(context, parts)
        radius = core.assembly_radius(parts, center)
        if radius <= core.EPSILON:
            return fallback
        return round(radius * 0.5, 4)

    def execute(self, context):
        props = context.scene.eas

        if self.preset == 'PCB_STACK':
            props.direction = 'AXIS_SPLIT'
            props.axis = 'Z'
            props.magnitude = 'LAYERED'
            # The active object (the PCB) becomes the split plane: everything
            # above it lifts off upwards, everything below drops away.
            props.center_mode = 'ACTIVE'
            props.layer_tolerance = 0.02
            props.distance = self._auto_distance(context, 0.5)
            props.use_rotation = False
            props.use_sequence = True
            props.order_mode = 'AXIS'
            props.overlap = 0.55
            props.interpolation = 'SINE'
            props.easing = 'EASE_IN_OUT'
            props.frame_start = 1
            props.frame_end = 120
            props.use_camera = True
            props.camera_orbit = 2.0943951
            props.camera_use_dolly = True
            # The board defines the split plane, so it is also the right thing
            # to frame: the shot stays on the product, not on the flying parts.
            active = context.active_object
            if active is not None and not active.eas.is_rig:
                props.camera_subject = active
                props.camera_mode = 'SUBJECT'
                props.camera_margin = 1.6
        elif self.preset == 'RADIAL':
            props.direction = 'CENTER'
            props.magnitude = 'PROPORTIONAL'
            props.center_mode = 'BOUNDS'
            props.distance = self._auto_distance(context, 2.0) * 2.0
            props.use_rotation = False
            props.use_sequence = False
            props.interpolation = 'BEZIER'
            props.easing = 'EASE_IN_OUT'
            props.frame_start = 1
            props.frame_end = 60
            props.use_camera = False
        else:  # SHOWCASE
            props.direction = 'CENTER'
            props.magnitude = 'PROPORTIONAL'
            props.center_mode = 'BOUNDS'
            props.distance = self._auto_distance(context, 2.0) * 2.0
            props.use_rotation = True
            props.rotation_angle = 0.261799  # 15 degrees
            props.rotation_axis = 'Z'
            props.rotation_local = True
            props.use_sequence = True
            props.order_mode = 'DISTANCE'
            props.overlap = 0.7
            props.interpolation = 'BACK'
            props.easing = 'EASE_OUT'
            props.frame_start = 1
            props.frame_end = 150
            props.use_camera = True
            props.camera_orbit = 3.14159265
            props.camera_use_dolly = True

        self.report({'INFO'}, f"Preset applied: {self.preset.replace('_', ' ').title()}")
        return {'FINISHED'}


class EAS_OT_camera_setup(Operator):
    """Create or update the camera rig around the current assembly"""

    bl_idname = "eas.camera_setup"
    bl_label = "Build Camera Rig"
    bl_options = {'REGISTER', 'UNDO'}

    animate_now: BoolProperty(
        name="Animate",
        description="Also key the orbit over the animation range",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        props = context.scene.eas
        problem = _camera_not_ready(props)
        if problem:
            self.report({'ERROR'}, problem[0].upper() + problem[1:])
            return {'CANCELLED'}

        parts, _ = core.build_parts(context)
        if not parts:
            self.report({'ERROR'}, _no_parts_message(props))
            return {'CANCELLED'}

        center = core.compute_explosion(context, parts)
        framing = _framing_for(context, parts, center)

        if self.animate_now:
            camera_module.animate(context, *framing)
        else:
            camera_module.ensure_rig(context, *framing)

        if props.camera_mode == 'POSES':
            message = "Camera move applied"
        elif props.camera_mode == 'SUBJECT':
            distance = camera_module.subject_distance(context, props.camera_subject)
            message = f"Framing {props.camera_subject.name} from {distance:.3f}"
        else:
            message = "Camera rig ready"
        self.report({'INFO'}, message)
        return {'FINISHED'}


class EAS_OT_camera_use_active_subject(Operator):
    """Use the active object as the object the camera frames"""

    bl_idname = "eas.camera_use_active_subject"
    bl_label = "Use Active Object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        props = context.scene.eas
        subject = context.active_object

        if subject.eas.is_rig:
            self.report({'ERROR'}, "That object is part of the camera rig")
            return {'CANCELLED'}

        props.camera_subject = subject
        props.camera_mode = 'SUBJECT'
        props.use_camera = True

        distance = camera_module.subject_distance(context, subject)
        self.report({'INFO'}, f"Framing {subject.name} from {distance:.3f}")
        return {'FINISHED'}


class EAS_OT_camera_capture_pose(Operator):
    """Capture the current viewport framing as a camera viewpoint"""

    bl_idname = "eas.camera_capture_pose"
    bl_label = "Add Viewpoint From View"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=[
            ('APPEND', "Add", "Add a new viewpoint at the end of the path"),
            ('INSERT', "Insert After Active", "Add a new viewpoint after the active one"),
            ('REPLACE', "Update Active", "Re-capture the active viewpoint from this view"),
        ],
        default='APPEND',
    )

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        props = context.scene.eas
        captured = camera_module.capture_from_view(context)
        if captured is None:
            self.report({'ERROR'}, "Run this from a 3D viewport")
            return {'CANCELLED'}

        matrix, focal, is_perspective = captured
        poses = props.camera_poses

        if self.mode == 'REPLACE':
            if not len(poses):
                self.report({'ERROR'}, "No viewpoint to update yet")
                return {'CANCELLED'}
            index = min(props.camera_pose_index, len(poses) - 1)
            pose = poses[index]
        else:
            pose = poses.add()
            index = len(poses) - 1
            if self.mode == 'INSERT' and len(poses) > 1:
                index = min(props.camera_pose_index + 1, len(poses) - 1)
                poses.move(len(poses) - 1, index)
                pose = poses[index]

        pose.matrix = core.matrix_to_flat(matrix)
        pose.lens = focal
        props.camera_pose_index = index

        if self.mode != 'REPLACE':
            camera_module.respace_poses(props)

        # Capturing a view is a clear statement of intent about the camera.
        props.camera_mode = 'POSES'
        props.use_camera = True

        if not is_perspective:
            self.report(
                {'WARNING'},
                "Viewpoint captured from an orthographic view, the rendered framing will differ",
            )
        else:
            self.report({'INFO'}, f"Viewpoint {index + 1} of {len(poses)} at {focal:.0f} mm")
        return {'FINISHED'}


class EAS_OT_camera_view_pose(Operator):
    """Point the viewport at a captured viewpoint so you can check or adjust it"""

    bl_idname = "eas.camera_view_pose"
    bl_label = "Look Through Viewpoint"
    bl_options = {'REGISTER'}

    index: IntProperty(name="Viewpoint", default=-1)

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        props = context.scene.eas
        poses = props.camera_poses
        index = self.index if self.index >= 0 else props.camera_pose_index
        if not len(poses) or index >= len(poses):
            self.report({'ERROR'}, "No such viewpoint")
            return {'CANCELLED'}

        pose = poses[index]
        if not camera_module.look_through_pose(
            context, core.flat_to_matrix(pose.matrix), pose.lens
        ):
            self.report({'ERROR'}, "Run this from a 3D viewport")
            return {'CANCELLED'}

        props.camera_pose_index = index
        self.report({'INFO'}, f"Viewport moved to viewpoint {index + 1}")
        return {'FINISHED'}


class EAS_OT_camera_pose_remove(Operator):
    """Remove the active camera viewpoint"""

    bl_idname = "eas.camera_pose_remove"
    bl_label = "Remove Viewpoint"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.eas.camera_poses) > 0

    def execute(self, context):
        props = context.scene.eas
        index = min(props.camera_pose_index, len(props.camera_poses) - 1)
        props.camera_poses.remove(index)
        props.camera_pose_index = max(0, min(index, len(props.camera_poses) - 1))
        camera_module.respace_poses(props)
        self.report({'INFO'}, f"{len(props.camera_poses)} viewpoint(s) left")
        return {'FINISHED'}


class EAS_OT_camera_pose_move(Operator):
    """Move the active viewpoint earlier or later in the camera path"""

    bl_idname = "eas.camera_pose_move"
    bl_label = "Move Viewpoint"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction",
        items=[('UP', "Up", "Earlier"), ('DOWN', "Down", "Later")],
        default='UP',
    )

    @classmethod
    def poll(cls, context):
        return len(context.scene.eas.camera_poses) > 1

    def execute(self, context):
        props = context.scene.eas
        poses = props.camera_poses
        index = min(props.camera_pose_index, len(poses) - 1)
        target = index - 1 if self.direction == 'UP' else index + 1
        if target < 0 or target >= len(poses):
            return {'CANCELLED'}

        poses.move(index, target)
        props.camera_pose_index = target
        camera_module.respace_poses(props)
        return {'FINISHED'}


class EAS_OT_camera_respace_poses(Operator):
    """Spread the viewpoints evenly across the camera move"""

    bl_idname = "eas.camera_respace_poses"
    bl_label = "Space Evenly"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.eas.camera_poses) > 1

    def execute(self, context):
        camera_module.respace_poses(context.scene.eas)
        self.report({'INFO'}, "Viewpoints spaced evenly")
        return {'FINISHED'}


class EAS_OT_camera_clear_poses(Operator):
    """Forget every captured camera viewpoint"""

    bl_idname = "eas.camera_clear_poses"
    bl_label = "Clear Viewpoints"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.eas
        props.camera_poses.clear()
        props.camera_pose_index = 0
        props.camera_pose_start_set = False
        props.camera_pose_end_set = False
        self.report({'INFO'}, "Viewpoints cleared")
        return {'FINISHED'}


class EAS_OT_mark_role(Operator):
    """Mark the selected objects as inner parts or as enclosure panels"""

    bl_idname = "eas.mark_role"
    bl_label = "Mark Role"
    bl_options = {'REGISTER', 'UNDO'}

    role: EnumProperty(
        name="Role",
        items=[
            ('PART', "Part", "Inner component"),
            ('ENCLOSURE', "Enclosure", "Shell panel"),
        ],
        default='ENCLOSURE',
    )

    @classmethod
    def poll(cls, context):
        return _object_mode(context) and bool(context.selected_objects)

    def execute(self, context):
        props = context.scene.eas
        targets = [
            obj for obj in context.selected_objects
            if obj.type not in core.SKIPPED_TYPES and not obj.eas.is_rig
        ]
        if not targets:
            self.report({'ERROR'}, "Select the objects to mark first")
            return {'CANCELLED'}

        for obj in targets:
            obj.eas.role = self.role

        if self.role == 'ENCLOSURE':
            props.use_phases = True

        label = "enclosure panel" if self.role == 'ENCLOSURE' else "part"
        self.report({'INFO'}, f"Marked {len(targets)} object(s) as {label}")
        return {'FINISHED'}


class EAS_OT_detect_sides(Operator):
    """Work out which way each enclosure panel opens and write it onto the objects"""

    bl_idname = "eas.detect_sides"
    bl_label = "Detect Sides"
    bl_options = {'REGISTER', 'UNDO'}

    mark_selected: BoolProperty(
        name="Mark Selected As Enclosure",
        description="Also mark the selected objects as enclosure panels before detecting",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return _object_mode(context)

    def execute(self, context):
        props = context.scene.eas

        if self.mark_selected:
            for obj in context.selected_objects:
                if obj.type not in core.SKIPPED_TYPES and not obj.eas.is_rig:
                    obj.eas.role = 'ENCLOSURE'
            props.use_phases = True

        parts, _ = core.build_parts(context)
        if not parts:
            self.report({'ERROR'}, _no_parts_message(props))
            return {'CANCELLED'}

        center = core.assembly_center(context, parts)
        found = []
        for part in parts:
            if part.obj.eas.role != 'ENCLOSURE':
                continue
            side = core.detect_side(part.center - center)
            part.obj.eas.side = side
            found.append(f"{part.obj.name}: {side.title()}")

        if not found:
            self.report({'WARNING'}, "No objects are marked as enclosure panels yet")
            return {'CANCELLED'}

        props.use_phases = True
        self.report({'INFO'}, f"Detected {len(found)} side(s) - " + ", ".join(found[:4]))
        return {'FINISHED'}


class EAS_OT_camera_delete(Operator):
    """Delete the generated camera rig"""

    bl_idname = "eas.camera_delete"
    bl_label = "Delete Camera Rig"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.eas
        return _object_mode(context) and any(
            (props.camera_object, props.camera_pivot, props.camera_target)
        )

    def execute(self, context):
        removed = camera_module.delete_rig(context)
        self.report({'INFO'}, f"Removed {removed} rig object(s)")
        return {'FINISHED'}


CLASSES = (
    EAS_OT_set_assembly_position,
    EAS_OT_clear_assembly_state,
    EAS_OT_preview,
    EAS_OT_animate,
    EAS_OT_clear_animation,
    EAS_OT_auto_order,
    EAS_OT_select_parts,
    EAS_OT_apply_preset,
    EAS_OT_camera_setup,
    EAS_OT_camera_use_active_subject,
    EAS_OT_camera_capture_pose,
    EAS_OT_camera_view_pose,
    EAS_OT_camera_pose_remove,
    EAS_OT_camera_pose_move,
    EAS_OT_camera_respace_poses,
    EAS_OT_camera_clear_poses,
    EAS_OT_camera_delete,
    EAS_OT_mark_role,
    EAS_OT_detect_sides,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
