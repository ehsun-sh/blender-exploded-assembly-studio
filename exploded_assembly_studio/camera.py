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

from mathutils import Matrix, Quaternion, Vector

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


class CameraInfo:
    """Where the camera looks over the shot, for hiding parked panels from it."""

    __slots__ = ('samples', 'fov_x', 'fov_y')

    def __init__(self, samples, fov_x, fov_y):
        self.samples = samples
        self.fov_x = fov_x
        self.fov_y = fov_y

    def positions(self):
        return [matrix.translation for matrix in self.samples]


def split_fov(context, angle):
    """Horizontal and vertical field of view for the current render aspect."""
    render = context.scene.render
    width = render.resolution_x * render.pixel_aspect_x
    height = render.resolution_y * render.pixel_aspect_y
    if angle <= 0.0:
        angle = math.radians(39.6)
    if width <= 0.0 or height <= 0.0:
        return angle, angle
    if width >= height:
        return angle, 2.0 * math.atan(math.tan(angle * 0.5) * height / width)
    return 2.0 * math.atan(math.tan(angle * 0.5) * width / height), angle


def _look_at(position, target):
    direction = Vector(position) - Vector(target)
    if direction.length <= core.EPSILON:
        direction = Vector((0.0, -1.0, 0.0))
    matrix = direction.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    matrix.translation = Vector(position)
    return matrix


def camera_path_samples(context, center, radius, count=9):
    """World matrices the camera passes through during the animation.

    Poses mode uses the captured viewpoints directly; the orbit modes are
    reconstructed from the rig parameters, which avoids having to build and
    evaluate the animation before the parts have been placed.
    """
    props = context.scene.eas

    if props.camera_mode == 'POSES':
        if poses_ready(props):
            return [_rolled(core.flat_to_matrix(p.matrix), p.roll) for p in sorted_poses_raw(props)]
        return []

    scale = max(radius, 0.001)
    lens = props.camera_focal
    sensor = sensor_width_for(props)
    if props.camera_auto_distance or props.camera_mode == 'SUBJECT':
        distance = framing_distance(context, lens_fov(lens, sensor), scale, props.camera_margin)
    else:
        distance = props.camera_distance

    if props.camera_use_dolly:
        near, far = distance * props.camera_zoom_start, distance * props.camera_zoom_end
        high, low = scale * props.camera_height, scale * props.camera_height_end
    else:
        near = far = distance
        high = low = scale * props.camera_height

    samples = []
    for step in range(count):
        t = step / float(max(count - 1, 1))
        angle = props.camera_start_angle + props.camera_orbit * t
        offset = Matrix.Rotation(angle, 4, 'Z') @ Vector((
            0.0, -(near + (far - near) * t), high + (low - high) * t,
        ))
        samples.append(_look_at(Vector(center) + offset, center))
    return samples


def sorted_poses_raw(props):
    """The pose property groups themselves, in time order."""
    return sorted(props.camera_poses, key=lambda pose: pose.position)


def camera_info(context, center, radius):
    """Camera sampling plus field of view, or None when there is no camera."""
    props = context.scene.eas

    if props.use_camera:
        samples = camera_path_samples(context, center, radius)
        lens = props.camera_focal
        if props.camera_mode == 'POSES' and len(props.camera_poses):
            lens = min(pose.lens for pose in props.camera_poses)
        angle = lens_fov(lens, sensor_width_for(props))
    else:
        scene_camera = context.scene.camera
        if scene_camera is None or scene_camera.type != 'CAMERA':
            return None
        samples = [scene_camera.matrix_world.copy()]
        angle = scene_camera.data.angle

    if not samples:
        return None
    fov_x, fov_y = split_fov(context, angle)
    return CameraInfo(samples, fov_x, fov_y)


def _frustum_planes(fov_x, fov_y):
    """Inward normals of the four side planes, in camera space (looking down -Z)."""
    half_x, half_y = fov_x * 0.5, fov_y * 0.5
    return (
        Vector((-math.cos(half_x), 0.0, -math.sin(half_x))),   # right edge
        Vector((math.cos(half_x), 0.0, -math.sin(half_x))),    # left edge
        Vector((0.0, -math.cos(half_y), -math.sin(half_y))),   # top edge
        Vector((0.0, math.cos(half_y), -math.sin(half_y))),    # bottom edge
    )


def offscreen_distance(info, point, radius, direction, margin=1.0):
    """How far to travel along ``direction`` to leave the frame, for every camera.

    The frustum planes all pass through the camera, so the test for one plane is
    linear in the travel distance and solves directly instead of by search.
    Returns None when no distance along this direction ever gets clear.
    """
    planes = _frustum_planes(info.fov_x, info.fov_y)
    padded = radius * margin
    needed = 0.0

    for matrix in info.samples:
        inverse = matrix.inverted()
        local_point = inverse @ point
        local_dir = inverse.to_3x3() @ direction

        best = None
        for normal in planes:
            offset = normal.dot(local_point)
            slope = normal.dot(local_dir)
            if offset < -padded:
                best = 0.0
                break
            if slope < -1e-9:
                candidate = (-padded - offset) / slope
                best = candidate if best is None else min(best, candidate)
        if best is None:
            return None
        needed = max(needed, best)
    return needed


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
    for pose in props.camera_poses:
        matrix = core.flat_to_matrix(pose.matrix)
        distance = max(distance, (matrix.translation - center).length)
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


def respace_poses(props):
    """Spread the viewpoints evenly from the first frame to the last."""
    count = len(props.camera_poses)
    if count == 0:
        return
    if count == 1:
        props.camera_poses[0].position = 0.0
        return
    for index, pose in enumerate(props.camera_poses):
        pose.position = index / float(count - 1)


def migrate_poses(props):
    """Carry a 1.1/1.2 style start+end pair into the viewpoint list.

    Returns True when something was migrated, so a scene saved with the old
    two-pose camera keeps working after an update.
    """
    if len(props.camera_poses):
        return False
    if not (props.camera_pose_start_set and props.camera_pose_end_set):
        return False

    for matrix, lens in ((props.camera_pose_start, props.camera_pose_start_lens),
                         (props.camera_pose_end, props.camera_pose_end_lens)):
        pose = props.camera_poses.add()
        pose.matrix = matrix
        pose.lens = lens
        pose.interpolation = props.camera_interpolation
        pose.easing = props.camera_easing
    respace_poses(props)
    return True


def poses_ready(props):
    if len(props.camera_poses) < 2:
        migrate_poses(props)
    return len(props.camera_poses) >= 2


def camera_frame_range(props):
    """The frames the camera actually moves over, after the start/end holds.

    Holding on the first viewpoint keeps a camera move from competing with the
    beginning of the assembly, which is the whole point of the delays.
    """
    low, high = core.frame_range_of(props)
    start = float(low) + props.camera_delay_start
    end = float(high) - props.camera_delay_end
    if end <= start:
        # Delays swallowed the range; keep a degenerate but valid pair.
        middle = (float(low) + float(high)) * 0.5
        start = min(max(start, float(low)), middle)
        end = start + 1.0
    return start, end


def sorted_poses(props):
    """Poses in play order, as (matrix, lens, position, motion, roll, interp, easing)."""
    entries = []
    for index, pose in enumerate(props.camera_poses):
        entries.append({
            'matrix': core.flat_to_matrix(pose.matrix),
            'lens': pose.lens,
            'position': pose.position,
            'motion': pose.motion,
            'roll': pose.roll,
            'interpolation': pose.interpolation,
            'easing': pose.easing,
            'index': index,
        })
    entries.sort(key=lambda entry: (entry['position'], entry['index']))
    return entries


def _rolled(matrix, roll):
    """Tilt a camera pose around its own view axis."""
    if abs(roll) <= core.EPSILON:
        return matrix
    return matrix @ Matrix.Rotation(roll, 4, 'Z')


def _arc_samples(matrix_a, matrix_b, center, count):
    """Positions and rotations along a circular arc from one pose to another.

    A straight keyframe pair always gives a straight line, so an arc has to be
    baked: the direction from the framing centre is slerped while the radius is
    blended, which sweeps the camera around the subject.
    """
    a = matrix_a.translation - center
    b = matrix_b.translation - center
    radius_a = a.length
    radius_b = b.length

    quat_a = matrix_a.to_quaternion()
    quat_b = matrix_b.to_quaternion()

    if radius_a <= core.EPSILON or radius_b <= core.EPSILON:
        return None

    dir_a = a.normalized()
    dir_b = b.normalized()
    swing = dir_a.rotation_difference(dir_b)

    samples = []
    for step in range(1, count + 1):
        t = step / float(count + 1)
        direction = Quaternion().slerp(swing, t) @ dir_a
        radius = radius_a + (radius_b - radius_a) * t
        location = center + direction * radius
        rotation = quat_a.slerp(quat_b, t)
        samples.append((t, location, rotation))
    return samples


def _key_camera(camera, matrix, frame):
    core.apply_basis(camera, matrix)
    camera.keyframe_insert('location', frame=frame, group="EAS Camera")
    camera.keyframe_insert('rotation_quaternion', frame=frame, group="EAS Camera")


def _key_pose(camera, location, rotation, frame):
    camera.location = location
    camera.rotation_quaternion = rotation
    camera.keyframe_insert('location', frame=frame, group="EAS Camera")
    camera.keyframe_insert('rotation_quaternion', frame=frame, group="EAS Camera")


def animate_poses(context, center, radius, reverse=False):
    """Move the camera along the captured viewpoints."""
    props = context.scene.eas
    if not poses_ready(props):
        return None

    camera = ensure_pose_camera(context, center, radius)
    start, end = camera_frame_range(props)
    span = end - start

    entries = sorted_poses(props)
    if reverse:
        entries = list(reversed(entries))
        # Mirroring flips the path, so the segment settings have to shift with
        # it: each segment keeps the motion of the pose it now leaves.
        motions = [entry['motion'] for entry in entries]
        rolls = [entry['roll'] for entry in entries]
        interps = [(entry['interpolation'], entry['easing']) for entry in entries]
        for index, entry in enumerate(entries):
            entry['position'] = 1.0 - entry['position']
            entry['roll'] = rolls[index]
            source = min(index + 1, len(entries) - 1)
            entry['motion'] = motions[source]
            entry['interpolation'], entry['easing'] = interps[source]

    frames = [start + entry['position'] * span for entry in entries]
    # Guarantee a strictly increasing timeline even if two poses share a time.
    for index in range(1, len(frames)):
        frames[index] = max(frames[index], frames[index - 1] + 1.0)

    core.clear_transform_animation(camera, CAMERA_PATHS)
    core.clear_transform_animation(camera.data, ('lens',))

    matrices = [_rolled(entry['matrix'], entry['roll']) for entry in entries]

    # Quaternion channels so the orientation blends the short way round
    # instead of unwinding through euler gimbal.
    for matrix, frame in zip(matrices, frames):
        _key_camera(camera, matrix, frame)

    arc_frames = set()
    for index in range(len(entries) - 1):
        if entries[index]['motion'] != 'ARC':
            continue
        frame_a = frames[index]
        frame_b = frames[index + 1]
        gap = frame_b - frame_a
        count = int(gap // max(props.camera_arc_samples, 1)) - 1
        if count < 1:
            continue
        samples = _arc_samples(matrices[index], matrices[index + 1], center, count)
        if samples is None:
            continue
        interpolation = entries[index]['interpolation']
        easing = entries[index]['easing']
        for t, location, rotation in samples:
            # Easing is baked into where each sample lands in time, so the
            # curve shape survives the linear interpolation between samples.
            eased = core.evaluate_easing(t, interpolation, easing)
            frame = frame_a + gap * eased
            _key_pose(camera, location, rotation, frame)
            arc_frames.add(round(frame, 4))

    _apply_segment_interpolation(camera, entries, frames, arc_frames)

    lenses = [entry['lens'] for entry in entries]
    if props.camera_animate_focal and max(lenses) - min(lenses) > 1e-4:
        for lens, frame in zip(lenses, frames):
            camera.data.lens = lens
            camera.data.keyframe_insert('lens', frame=frame, group="EAS Camera")
        _apply_segment_interpolation(camera.data, entries, frames, set(), ('lens',))
    else:
        camera.data.lens = lenses[0]

    return camera


def _apply_segment_interpolation(target, entries, frames, arc_frames, paths=CAMERA_PATHS):
    """Give each keyframe the interpolation of the segment that leaves it.

    Keys baked along an arc are already positioned in time to carry their
    easing, so they interpolate linearly between one another.
    """
    lookup = {}
    for entry, frame in zip(entries, frames):
        lookup[round(frame, 4)] = (entry['interpolation'], entry['easing'])

    for curve in core.iter_fcurves(target, paths):
        for keyframe in curve.keyframe_points:
            key = round(keyframe.co.x, 4)
            if key in arc_frames:
                keyframe.interpolation = 'LINEAR'
                continue
            interpolation, easing = lookup.get(key, ('BEZIER', 'AUTO'))
            keyframe.interpolation = interpolation
            if interpolation not in {'CONSTANT', 'LINEAR', 'BEZIER'}:
                keyframe.easing = easing
        curve.update()


def animate(context, center, radius, reverse=False):
    """Build the rig and key the orbit over the scene's animation range.

    ``reverse`` mirrors the orbit so an Assemble pass travels back the way the
    Explode pass came, which reads as one continuous camera move.
    """
    props = context.scene.eas
    if props.camera_mode == 'POSES':
        return animate_poses(context, center, radius, reverse)

    pivot, target, camera, distance = ensure_rig(context, center, radius)

    start, end = camera_frame_range(props)
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
