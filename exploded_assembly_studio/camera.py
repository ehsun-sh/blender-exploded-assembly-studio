"""Camera rig and orbit animation.

The rig is deliberately simple and hand editable:

    EAS_Camera_Pivot   empty at the assembly center, only its Z rotation is keyed
      +- EAS_Camera    parented to the pivot, local Y offset is the orbit radius
    EAS_Camera_Target  empty at the assembly center, aimed at by a Track To

Because the orbit is a single rotation channel, the motion is a perfect circle
and easing works the way you would expect. Dolly moves are keyed on the
camera's own local location, so they layer on top of the orbit.
"""

import math

from mathutils import Vector

import bpy

from . import core

PIVOT_NAME = "EAS_Camera_Pivot"
TARGET_NAME = "EAS_Camera_Target"
CAMERA_NAME = "EAS_Camera"
CONSTRAINT_NAME = "EAS Aim"

#: Full frame sensor width in mm, used before a camera exists.
DEFAULT_SENSOR = 36.0

CAMERA_PATHS = ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle')


def _scene_collection(context):
    return context.scene.collection


def _ensure_empty(context, existing, name, display_type='PLAIN_AXES'):
    obj = existing
    if obj is not None and obj.name not in context.scene.objects:
        obj = None
    if obj is None:
        data_name = name
        obj = bpy.data.objects.new(data_name, None)
        obj.empty_display_type = display_type
        _scene_collection(context).objects.link(obj)
    obj.eas.is_rig = True
    return obj


def _ensure_camera(context, existing, name):
    obj = existing
    if obj is not None and (obj.name not in context.scene.objects or obj.type != 'CAMERA'):
        obj = None
    if obj is None:
        data = bpy.data.cameras.new(name)
        obj = bpy.data.objects.new(name, data)
        _scene_collection(context).objects.link(obj)
    obj.eas.is_rig = True
    return obj


def lens_fov(lens, sensor_width=DEFAULT_SENSOR):
    """Horizontal field of view of a lens on a given sensor."""
    return 2.0 * math.atan(sensor_width / (2.0 * max(lens, 1e-6)))


def visible_fov(context, angle):
    """Narrow a horizontal field of view down to the render's short side."""
    render = context.scene.render
    width = render.resolution_x * render.pixel_aspect_x
    height = render.resolution_y * render.pixel_aspect_y
    if angle <= 0.0:
        angle = math.radians(39.6)
    if width <= 0.0 or height <= 0.0:
        return angle
    ratio = min(width, height) / max(width, height)
    return 2.0 * math.atan(math.tan(angle * 0.5) * ratio)


def framing_distance(context, angle, radius, margin):
    """Distance at which a sphere of ``radius`` fits inside the frame.

    The sphere is tangent to the frame edges at ``d = r / sin(fov/2)``; the
    margin then backs the camera off a little so the subject is not cropped by
    its own corners.
    """
    fov = visible_fov(context, angle)
    sine = math.sin(fov * 0.5)
    if sine <= core.EPSILON:
        return max(radius * 3.0, 1.0)
    return (radius * margin) / sine


def subject_bounds(obj):
    """Center and bounding sphere radius of one object at its assembled pose.

    Measured from the assembled transform, so an object that flies off during
    the explosion still frames from where it belongs in the finished product.
    """
    world = core.parent_matrix(obj) @ core.assembled_basis(obj)
    corners = core.bound_corners(obj, world)
    low, high = core.bounds_of(corners)
    center = (low + high) * 0.5
    radius = max((corner - center).length for corner in corners) if corners else 0.0
    if radius <= core.EPSILON:
        # Empties and other size-less objects still need something to frame.
        radius = max(getattr(obj, 'empty_display_size', 0.0), 0.1)
    return center, radius


def sensor_width_for(props):
    camera = props.camera_object
    if camera is not None and camera.type == 'CAMERA':
        return camera.data.sensor_width
    return DEFAULT_SENSOR


def subject_distance(context, obj):
    """The distance the camera picks for a subject, without building anything.

    Used both by the rig and by the panel readout, so what the user is shown is
    exactly what they will get.
    """
    props = context.scene.eas
    _, radius = subject_bounds(obj)
    angle = lens_fov(props.camera_focal, sensor_width_for(props))
    return framing_distance(context, angle, radius, props.camera_margin)


def resolve_framing(context, center, radius):
    """Override the framing with the chosen subject when in Frame Object mode.

    Call this while the scene still sits at the assembled pose and the depsgraph
    is in sync. Object transforms written without a view layer update leave
    ``matrix_world`` stale, which would measure the subject in the wrong place.
    """
    props = context.scene.eas
    if props.camera_mode == 'SUBJECT' and props.camera_subject is not None:
        return subject_bounds(props.camera_subject)
    return center, radius


def viewport_view(context):
    """Return the (space, region_3d) of a 3D viewport, or (None, None)."""
    space = context.space_data
    if space is None or space.type != 'VIEW_3D':
        space = None
        screen = getattr(context, 'screen', None)
        if screen is not None:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    space = area.spaces.active
                    break
    if space is None or space.type != 'VIEW_3D':
        return None, None

    region = space.region_3d
    if region is None and len(space.region_quadviews):
        region = space.region_quadviews[-1]
    return space, region


def capture_from_view(context):
    """Read the current viewport as a camera pose.

    Works both when looking through the camera (with Lock Camera to View on,
    this is exactly the framing in the Camera Preview) and when navigating a
    normal user view, because in camera view the region's view matrix *is* the
    camera's. Returns ``(matrix, focal_length, is_perspective)`` or ``None``.
    """
    space, region = viewport_view(context)
    if region is None:
        return None

    matrix = region.view_matrix.inverted()

    if region.view_perspective == 'CAMERA' and context.scene.camera is not None:
        camera_data = context.scene.camera.data
        focal = camera_data.lens if camera_data.type == 'PERSP' else space.lens
    else:
        focal = space.lens

    return matrix, focal, region.is_perspective


def look_through_pose(context, matrix, focal):
    """Point the viewport at a stored pose so the user can check it."""
    space, region = viewport_view(context)
    if region is None:
        return False

    # The view matrix is ignored while the region is locked to the camera.
    if region.view_perspective == 'CAMERA':
        region.view_perspective = 'PERSP'
    region.view_matrix = matrix.inverted()
    space.lens = focal
    update = getattr(region, 'update', None)
    if update is not None:
        update()
    return True


def _detach_camera(camera):
    """Free the camera from the orbit rig so a captured pose is not overridden."""
    if camera.parent is not None:
        camera.parent = None
        camera.matrix_parent_inverse.identity()
    for constraint in [c for c in camera.constraints if c.name == CONSTRAINT_NAME]:
        camera.constraints.remove(constraint)


def _set_clipping(camera, distance):
    camera.data.clip_start = max(distance * 0.001, 1e-5)
    camera.data.clip_end = max(camera.data.clip_end, distance * 10.0)


def ensure_pose_camera(context, center, radius):
    """Camera used by the From Viewport mode: no parent, no aim constraint."""
    props = context.scene.eas
    camera = _ensure_camera(context, props.camera_object, CAMERA_NAME)
    props.camera_object = camera

    _detach_camera(camera)
    camera.rotation_mode = 'QUATERNION'

    distance = max(radius, 0.001) * 3.0
    for stored, is_set in ((props.camera_pose_start, props.camera_pose_start_set),
                           (props.camera_pose_end, props.camera_pose_end_set)):
        if is_set:
            pose = core.flat_to_matrix(stored)
            distance = max(distance, (pose.translation - center).length)
    _set_clipping(camera, distance)

    if props.camera_set_active:
        context.scene.camera = camera
    return camera


def ensure_rig(context, center, radius):
    """Create or update the rig. Returns (pivot, target, camera, distance).

    ``center`` and ``radius`` are expected to be already resolved by the caller
    via :func:`resolve_framing`.
    """
    props = context.scene.eas

    if props.camera_mode == 'POSES':
        camera = ensure_pose_camera(context, center, radius)
        return None, None, camera, 0.0

    pivot = _ensure_empty(context, props.camera_pivot, PIVOT_NAME, 'SPHERE')
    target = _ensure_empty(context, props.camera_target, TARGET_NAME, 'PLAIN_AXES')
    camera = _ensure_camera(context, props.camera_object, CAMERA_NAME)

    props.camera_pivot = pivot
    props.camera_target = target
    props.camera_object = camera

    scale = max(radius, 0.001)
    pivot.location = center
    pivot.rotation_mode = 'XYZ'
    pivot.empty_display_size = scale * 0.15
    target.location = center
    target.empty_display_size = scale * 0.1

    camera.data.lens = props.camera_focal
    camera.rotation_mode = 'XYZ'
    if camera.parent != pivot:
        camera.parent = pivot
    camera.matrix_parent_inverse.identity()

    constraint = camera.constraints.get(CONSTRAINT_NAME)
    if constraint is None or constraint.type != 'TRACK_TO':
        for old in [c for c in camera.constraints if c.name == CONSTRAINT_NAME]:
            camera.constraints.remove(old)
        constraint = camera.constraints.new('TRACK_TO')
        constraint.name = CONSTRAINT_NAME
    constraint.target = target
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    constraint.up_axis = 'UP_Y'

    # Frame Object mode exists to work the distance out, so it always auto frames.
    if props.camera_auto_distance or props.camera_mode == 'SUBJECT':
        distance = framing_distance(context, camera.data.angle, scale, props.camera_margin)
    else:
        distance = props.camera_distance

    # Clip planes wide enough for the framing we just chose.
    _set_clipping(camera, distance)

    if props.camera_set_active:
        context.scene.camera = camera

    return pivot, target, camera, distance


def clear_camera_animation(context):
    props = context.scene.eas
    for obj in (props.camera_pivot, props.camera_object, props.camera_target):
        if obj is not None and obj.name in bpy.data.objects:
            core.clear_transform_animation(obj)
    camera = props.camera_object
    if camera is not None and camera.name in bpy.data.objects and camera.type == 'CAMERA':
        core.clear_transform_animation(camera.data, ('lens',))


def poses_ready(props):
    return props.camera_pose_start_set and props.camera_pose_end_set


def animate_poses(context, center, radius, reverse=False):
    """Move the camera between the two poses captured from the viewport."""
    props = context.scene.eas
    if not poses_ready(props):
        return None

    camera = ensure_pose_camera(context, center, radius)
    start, end = core.frame_range_of(props)

    pose_start = core.flat_to_matrix(props.camera_pose_start)
    pose_end = core.flat_to_matrix(props.camera_pose_end)
    lens_start = props.camera_pose_start_lens
    lens_end = props.camera_pose_end_lens
    if reverse:
        pose_start, pose_end = pose_end, pose_start
        lens_start, lens_end = lens_end, lens_start

    core.clear_transform_animation(camera, CAMERA_PATHS)
    core.clear_transform_animation(camera.data, ('lens',))

    # Quaternion channels so the orientation blends the short way round
    # instead of unwinding through euler gimbal.
    for matrix, frame in ((pose_start, start), (pose_end, end)):
        core.apply_basis(camera, matrix)
        camera.keyframe_insert('location', frame=frame, group="EAS Camera")
        camera.keyframe_insert('rotation_quaternion', frame=frame, group="EAS Camera")

    if props.camera_animate_focal and abs(lens_start - lens_end) > 1e-4:
        for lens, frame in ((lens_start, start), (lens_end, end)):
            camera.data.lens = lens
            camera.data.keyframe_insert('lens', frame=frame, group="EAS Camera")
        core.apply_interpolation(
            camera.data, props.camera_interpolation, props.camera_easing, ('lens',)
        )
    else:
        camera.data.lens = lens_start

    core.apply_interpolation(
        camera, props.camera_interpolation, props.camera_easing, CAMERA_PATHS
    )
    return camera


def animate(context, center, radius, reverse=False):
    """Build the rig and key the orbit over the scene's animation range.

    ``reverse`` mirrors the orbit so an Assemble pass travels back the way the
    Explode pass came, which reads as one continuous camera move.
    """
    props = context.scene.eas
    if props.camera_mode == 'POSES':
        return animate_poses(context, center, radius, reverse)

    pivot, target, camera, distance = ensure_rig(context, center, radius)

    start, end = core.frame_range_of(props)
    scale = max(radius, 0.001)

    angle_start = props.camera_start_angle
    angle_end = angle_start + props.camera_orbit
    if reverse:
        angle_start, angle_end = angle_end, angle_start

    if props.camera_use_dolly:
        distance_start = distance * props.camera_zoom_start
        distance_end = distance * props.camera_zoom_end
        height_start = scale * props.camera_height
        height_end = scale * props.camera_height_end
    else:
        distance_start = distance_end = distance
        height_start = height_end = scale * props.camera_height
    if reverse:
        distance_start, distance_end = distance_end, distance_start
        height_start, height_end = height_end, height_start

    core.clear_transform_animation(pivot)
    core.clear_transform_animation(camera, CAMERA_PATHS)

    pivot.rotation_euler = (0.0, 0.0, angle_start)
    pivot.keyframe_insert('rotation_euler', index=2, frame=start, group="EAS Camera")
    pivot.rotation_euler = (0.0, 0.0, angle_end)
    pivot.keyframe_insert('rotation_euler', index=2, frame=end, group="EAS Camera")

    camera.location = Vector((0.0, -distance_start, height_start))
    camera.keyframe_insert('location', frame=start, group="EAS Camera")
    camera.location = Vector((0.0, -distance_end, height_end))
    camera.keyframe_insert('location', frame=end, group="EAS Camera")

    core.apply_interpolation(pivot, props.camera_interpolation, props.camera_easing)
    core.apply_interpolation(camera, props.camera_interpolation, props.camera_easing, CAMERA_PATHS)

    return camera


def delete_rig(context):
    """Remove the generated rig objects."""
    props = context.scene.eas
    removed = 0
    for attribute in ('camera_object', 'camera_pivot', 'camera_target'):
        obj = getattr(props, attribute)
        if obj is None:
            continue
        if obj.name in bpy.data.objects:
            data = obj.data if obj.type == 'CAMERA' else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.cameras.remove(data)
            removed += 1
        setattr(props, attribute, None)
    return removed
