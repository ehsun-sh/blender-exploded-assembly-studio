"""Transform maths for Exploded Assembly Studio.

The rules this module follows:

*   The assembled state is ground truth. It is recorded as the object's local
    (basis) matrix, which is exactly what keyframes drive, so a round trip is
    lossless even for parented or non uniformly scaled parts.
*   Explosion vectors are computed in world space, then converted back into the
    object's own parent space before being written. That keeps parented parts
    moving where the user expects.
*   Nothing here writes to mesh data, materials or origins.
"""

import math

from mathutils import Matrix, Vector

EPSILON = 1e-9

#: Object types that are never treated as assembly parts.
SKIPPED_TYPES = {'CAMERA', 'LIGHT', 'SPEAKER', 'LIGHT_PROBE'}

#: Transform channels the add-on owns.
TRANSFORM_PATHS = (
    'location',
    'rotation_euler',
    'rotation_quaternion',
    'rotation_axis_angle',
    'scale',
)

AXIS_VECTORS = {
    'X': Vector((1.0, 0.0, 0.0)),
    'Y': Vector((0.0, 1.0, 0.0)),
    'Z': Vector((0.0, 0.0, 1.0)),
}

#: Outward direction of each enclosure side, in Blender's world axes.
SIDE_VECTORS = {
    'TOP': Vector((0.0, 0.0, 1.0)),
    'BOTTOM': Vector((0.0, 0.0, -1.0)),
    'FRONT': Vector((0.0, -1.0, 0.0)),
    'BACK': Vector((0.0, 1.0, 0.0)),
    'RIGHT': Vector((1.0, 0.0, 0.0)),
    'LEFT': Vector((-1.0, 0.0, 0.0)),
}

#: Order the sides are offered and auto-detected in.
SIDE_ORDER = ('TOP', 'BOTTOM', 'FRONT', 'BACK', 'RIGHT', 'LEFT')


def detect_side(offset):
    """Pick the enclosure side a panel sitting at ``offset`` from the centre faces.

    The dominant axis of the offset wins, so a lid above the product reads as
    TOP and a panel out to the left reads as LEFT.
    """
    components = (
        (abs(offset.z), 'TOP' if offset.z >= 0.0 else 'BOTTOM'),
        (abs(offset.y), 'BACK' if offset.y >= 0.0 else 'FRONT'),
        (abs(offset.x), 'RIGHT' if offset.x >= 0.0 else 'LEFT'),
    )
    return max(components, key=lambda item: item[0])[1]


def resolved_side(obj, offset):
    """The side an enclosure panel opens towards, resolving AUTO."""
    side = obj.eas.side
    if side == 'AUTO':
        return detect_side(offset)
    return side


# ---------------------------------------------------------------------------
# matrix helpers
# ---------------------------------------------------------------------------

def matrix_to_flat(matrix):
    """Flatten a 4x4 matrix row major for storage in a FloatVectorProperty."""
    return [value for row in matrix for value in row]


def flat_to_matrix(values):
    values = list(values)
    return Matrix((values[0:4], values[4:8], values[8:12], values[12:16]))


def parent_matrix(obj):
    """Return the matrix that maps the object's basis into world space.

    ``matrix_world == parent_matrix @ matrix_basis`` holds for every parent
    type (object, bone, vertex), so deriving it this way avoids special casing.
    """
    try:
        return obj.matrix_world @ obj.matrix_basis.inverted()
    except ValueError:
        return Matrix.Identity(4)


def store_state(obj):
    """Record the object's current local transform as its assembled state."""
    obj.eas.assembly_matrix = matrix_to_flat(obj.matrix_basis)
    obj.eas.has_state = True


def assembled_basis(obj):
    """The recorded assembled basis matrix, falling back to the current one."""
    if obj.eas.has_state:
        return flat_to_matrix(obj.eas.assembly_matrix)
    return obj.matrix_basis.copy()


def apply_basis(obj, matrix):
    """Write a basis matrix into loc/rot/scale honouring the rotation mode."""
    location, quaternion, scale = matrix.decompose()
    obj.location = location
    mode = obj.rotation_mode
    if mode == 'QUATERNION':
        obj.rotation_quaternion = quaternion
    elif mode == 'AXIS_ANGLE':
        axis, angle = quaternion.to_axis_angle()
        obj.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
    else:
        # Passing the current euler keeps the result continuous instead of
        # flipping to an equivalent but visually different rotation.
        obj.rotation_euler = quaternion.to_euler(mode, obj.rotation_euler)
    obj.scale = scale


def rotation_data_path(obj):
    mode = obj.rotation_mode
    if mode == 'QUATERNION':
        return 'rotation_quaternion'
    if mode == 'AXIS_ANGLE':
        return 'rotation_axis_angle'
    return 'rotation_euler'


# ---------------------------------------------------------------------------
# bounds
# ---------------------------------------------------------------------------

def bound_corners(obj, matrix_world):
    """World space corners of the object's local bounding box."""
    if obj.type == 'EMPTY' or not hasattr(obj, 'bound_box'):
        return [matrix_world.translation.copy()]
    corners = [matrix_world @ Vector(corner) for corner in obj.bound_box]
    # Objects with no geometry report eight identical corners; that is fine,
    # it collapses to the origin.
    return corners


def object_center(obj, matrix_world, use_bounds=True):
    """Reference point of a part: bounding box center or object origin."""
    if not use_bounds:
        return matrix_world.translation.copy()
    corners = bound_corners(obj, matrix_world)
    total = Vector((0.0, 0.0, 0.0))
    for corner in corners:
        total += corner
    return total / len(corners)


def bounds_of(points):
    """Return (min_corner, max_corner) of a point cloud."""
    if not points:
        return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0))
    low = Vector(points[0])
    high = Vector(points[0])
    for point in points[1:]:
        for axis in range(3):
            low[axis] = min(low[axis], point[axis])
            high[axis] = max(high[axis], point[axis])
    return low, high


# ---------------------------------------------------------------------------
# part gathering
# ---------------------------------------------------------------------------

class Part:
    """One assembly part with everything the animation builder needs."""

    __slots__ = (
        'obj', 'basis_assembled', 'parent', 'world_assembled', 'center',
        'basis_exploded', 'offset', 'rank', 'sort_key', 'sequence',
    )

    def __init__(self, obj, basis_assembled, parent, world_assembled, center):
        self.obj = obj
        self.basis_assembled = basis_assembled
        self.parent = parent
        self.world_assembled = world_assembled
        self.center = center
        self.basis_exploded = basis_assembled.copy()
        self.offset = Vector((0.0, 0.0, 0.0))
        self.rank = 1
        self.sort_key = 0.0
        self.sequence = 0


def is_rig_object(obj, props):
    if obj.eas.is_rig:
        return True
    return obj in (props.camera_object, props.camera_pivot, props.camera_target)


def collect_objects(context):
    """Gather the source objects in a stable, de-duplicated order."""
    props = context.scene.eas

    if props.source == 'COLLECTION':
        collection = props.collection
        candidates = list(collection.all_objects) if collection else []
    else:
        candidates = list(context.selected_objects)

    result = []
    seen = set()
    for obj in candidates:
        if obj.name in seen:
            continue
        seen.add(obj.name)
        if obj.type in SKIPPED_TYPES:
            continue
        if is_rig_object(obj, props):
            continue
        if props.visible_only and not obj.visible_get():
            continue
        result.append(obj)

    if props.skip_child_parts:
        members = set(result)
        result = [obj for obj in result if not _has_ancestor_in(obj, members)]

    return result


def source_report(context):
    """Say why no parts were found, in terms that point at the fix.

    "No usable objects" is true of an empty collection, a hidden one, and one
    excluded from the view layer, and those are fixed in completely different
    places, so the message has to distinguish them.
    """
    props = context.scene.eas

    if props.source != 'COLLECTION':
        if not context.selected_objects:
            return "Select the assembly parts first"
        return "Nothing in the selection can be used as a part"

    collection = props.collection
    if collection is None:
        return "Pick a collection under Source first"

    usable = [obj for obj in collection.all_objects if obj.type not in SKIPPED_TYPES]
    if not usable:
        return f"Source collection '{collection.name}' holds no objects that can be moved"

    if props.visible_only:
        visible = [obj for obj in usable if obj.visible_get()]
        if not visible:
            return (
                f"All {len(usable)} object(s) in '{collection.name}' are hidden or excluded from "
                "the view layer. Unhide them, or turn off Visible Only under Filtering"
            )

    return f"Source collection '{collection.name}' has no usable objects"


def missing_from_source(context, collection):
    """Split a collection's objects into (hidden, outside the source set).

    Either way they will not be animated, but one is fixed in the outliner and
    the other by pointing Source somewhere that contains them.
    """
    props = context.scene.eas
    if collection is None:
        return [], []

    collected = {obj.name for obj in collect_objects(context)}
    if props.source == 'COLLECTION' and props.collection is not None:
        in_source = {obj.name for obj in props.collection.all_objects}
    else:
        in_source = {obj.name for obj in context.selected_objects}

    hidden, outside = [], []
    for obj in collection.all_objects:
        if obj.type in SKIPPED_TYPES or obj.name in collected:
            continue
        (hidden if obj.name in in_source else outside).append(obj.name)
    return hidden, outside


def _has_ancestor_in(obj, members):
    parent = obj.parent
    guard = 0
    while parent is not None and guard < 256:
        if parent in members:
            return True
        parent = parent.parent
        guard += 1
    return False


def restore_assembled(objects):
    """Put the given objects back to their recorded assembled transform."""
    for obj in objects:
        apply_basis(obj, assembled_basis(obj))


# ---------------------------------------------------------------------------
# explosion
# ---------------------------------------------------------------------------

def build_parts(context, objects=None, store_missing=True):
    """Create :class:`Part` records with assembled transforms resolved.

    The objects are first snapped back to their assembled state so that parent
    matrices are read from a consistent scene, then measured.
    """
    props = context.scene.eas
    if objects is None:
        objects = collect_objects(context)
    if not objects:
        return [], 0

    stored = 0
    if store_missing and props.auto_store_state:
        for obj in objects:
            if not obj.eas.has_state:
                store_state(obj)
                stored += 1

    restore_assembled(objects)
    context.view_layer.update()

    parts = []
    for obj in objects:
        basis = assembled_basis(obj)
        parent = parent_matrix(obj)
        world = parent @ basis
        center = object_center(obj, world, props.use_bounds_center)
        parts.append(Part(obj, basis, parent, world, center))
    return parts, stored


def assembly_center(context, parts):
    """The reference point every explode vector is measured from."""
    props = context.scene.eas
    if props.center_mode == 'CURSOR':
        return context.scene.cursor.location.copy()
    if props.center_mode == 'ACTIVE':
        active = context.view_layer.objects.active
        for part in parts:
            if part.obj == active:
                return part.center.copy()
    if props.center_mode == 'MEDIAN':
        total = Vector((0.0, 0.0, 0.0))
        for part in parts:
            total += part.center
        return total / len(parts)

    points = []
    for part in parts:
        points.extend(bound_corners(part.obj, part.world_assembled))
    low, high = bounds_of(points)
    return (low + high) * 0.5


def assembly_radius(parts, center, matrices=None, skip=None):
    """Largest distance from ``center`` to any part corner.

    ``skip`` drops objects from the measurement, which is how enclosure panels
    parked off camera are kept from dragging the framing out with them.
    """
    radius = 0.0
    for part in parts:
        if skip is not None and part.obj.name in skip:
            continue
        world = matrices[part.obj.name] if matrices else part.world_assembled
        for corner in bound_corners(part.obj, world):
            radius = max(radius, (corner - center).length)
    return radius


def compute_explosion(context, parts):
    """Fill in ``offset``, ``rank`` and ``basis_exploded`` on every part.

    Returns the assembly center that was used.
    """
    props = context.scene.eas
    center = assembly_center(context, parts)
    axis = AXIS_VECTORS[props.axis]
    size = assembly_radius(parts, center)
    band = size * props.layer_tolerance

    movable = [part for part in parts if not part.obj.eas.exclude]

    # --- sort keys drive both the layered spacing and the sequence order ----
    for part in parts:
        delta = part.center - center
        if props.direction in {'AXIS_SPLIT', 'WORLD_AXIS'}:
            part.sort_key = delta.dot(axis)
        else:
            part.sort_key = delta.length

    _assign_ranks(props, movable, axis, center, band)

    max_radius = max((part.center - center).length for part in parts) if parts else 0.0

    for part in parts:
        if part.obj.eas.exclude:
            part.offset = Vector((0.0, 0.0, 0.0))
            part.basis_exploded = part.basis_assembled.copy()
            continue

        direction = _direction_for(props, part, center, axis, band)
        magnitude = _magnitude_for(props, part, center, max_radius)
        part.offset = direction * magnitude
        part.basis_exploded = _exploded_basis(props, part, axis)

    return center


def _assign_ranks(props, parts, axis, center, band):
    """Layer index per part, counted outwards from the center.

    Parts sitting at nearly the same depth share a layer, so a row of identical
    components lifts off as one sheet instead of fanning into a staircase.
    """
    if props.direction == 'AXIS_SPLIT':
        sides = {1: [], -1: [], 0: []}
        for part in parts:
            projection = (part.center - center).dot(axis)
            side = 0 if abs(projection) <= band else (1 if projection > 0.0 else -1)
            sides[side].append((abs(projection), part))
        for side, group in sides.items():
            if side == 0:
                for _, part in group:
                    part.rank = 0
            else:
                _rank_group(group, band)
        return

    _rank_group([(part.sort_key, part) for part in parts], band)


def _rank_group(pairs, tolerance):
    """Cluster (key, part) pairs by key and number the clusters from one."""
    pairs = sorted(pairs, key=lambda pair: pair[0])
    rank = 0
    previous = None
    for key, part in pairs:
        if previous is None or (key - previous) > max(tolerance, EPSILON):
            rank += 1
        part.rank = rank
        previous = key


def is_enclosure_member(props, obj):
    """True when this object counts as a shell panel, phases aside.

    Membership comes from the per object role or from the enclosure collection,
    so a shell that is already grouped in the outliner needs no tagging.
    """
    if obj.eas.role == 'ENCLOSURE':
        return True
    collection = props.enclosure_collection
    if collection is None:
        return False
    return collection.all_objects.get(obj.name) is not None


def is_enclosure(props, obj):
    """True when the enclosure feature is on and this object is a shell panel."""
    return props.use_phases and is_enclosure_member(props, obj)


def _direction_for(props, part, center, axis, band):
    mode = props.direction
    delta = part.center - center

    # A shell panel opens along its own side, whatever the global direction is.
    if is_enclosure(props, part.obj):
        return SIDE_VECTORS[resolved_side(part.obj, delta)].copy()

    if mode == 'WORLD_AXIS':
        return axis.copy()

    if mode == 'AXIS_SPLIT':
        projection = delta.dot(axis)
        if abs(projection) <= band:
            return Vector((0.0, 0.0, 0.0))
        return axis * (1.0 if projection > 0.0 else -1.0)

    if mode == 'LOCAL_AXIS':
        local = part.world_assembled.to_3x3() @ axis
        if local.length <= EPSILON:
            return axis.copy()
        return local.normalized()

    # CENTER
    if delta.length <= EPSILON:
        return Vector((0.0, 0.0, 0.0))
    return delta.normalized()


def _magnitude_for(props, part, center, max_radius):
    base = props.distance

    if is_enclosure(props, part.obj):
        # Shell panels get a flat, larger travel so they clear the parts inside
        # instead of being spread by the layering rules meant for components.
        return base * props.enclosure_distance_factor * part.obj.eas.distance_multiplier

    if props.magnitude == 'PROPORTIONAL':
        if max_radius <= EPSILON:
            factor = 0.0
        else:
            factor = (part.center - center).length / max_radius
        base *= factor
    elif props.magnitude == 'LAYERED':
        base *= part.rank

    return base * part.obj.eas.distance_multiplier


def _exploded_basis(props, part, axis):
    """World transform at the exploded state, converted back to parent space."""
    world = part.world_assembled

    if props.use_rotation and abs(props.rotation_angle) > EPSILON:
        if props.rotation_local:
            spin_axis = world.to_3x3() @ AXIS_VECTORS[props.rotation_axis]
            if spin_axis.length <= EPSILON:
                spin_axis = AXIS_VECTORS[props.rotation_axis].copy()
            spin_axis.normalize()
        else:
            spin_axis = AXIS_VECTORS[props.rotation_axis]
        rotation = Matrix.Rotation(props.rotation_angle, 4, spin_axis)
        pivot = Matrix.Translation(part.center)
        world = pivot @ rotation @ pivot.inverted() @ world

    world = Matrix.Translation(part.offset) @ world

    try:
        return part.parent.inverted() @ world
    except ValueError:
        return world


# ---------------------------------------------------------------------------
# ordering
# ---------------------------------------------------------------------------

#: A side is "facing the camera" past this much alignment with the camera.
CAMERA_FACING_LIMIT = 0.35


def part_radius(part, matrix=None):
    """Bounding sphere radius of one part about its own centre."""
    world = matrix if matrix is not None else part.world_assembled
    corners = bound_corners(part.obj, world)
    center = part.center if matrix is None else object_center(part.obj, world)
    return max((corner - center).length for corner in corners) if corners else 0.0


def choose_entry_side(natural, to_camera):
    """Pick the side a panel enters from, avoiding the camera's own side.

    Candidates are scored by how much they point at the camera; the one closest
    to the panel's natural side that is still clear of the lens wins, so the
    change stays as small as the geometry allows.
    """
    natural_vector = SIDE_VECTORS[natural]
    if natural_vector.dot(to_camera) <= CAMERA_FACING_LIMIT:
        return natural

    acceptable = [
        side for side in SIDE_ORDER
        if SIDE_VECTORS[side].dot(to_camera) <= CAMERA_FACING_LIMIT
    ]
    if not acceptable:
        # Every side faces the camera somehow; take the least bad one.
        return min(SIDE_ORDER, key=lambda side: SIDE_VECTORS[side].dot(to_camera))

    return max(acceptable, key=lambda side: SIDE_VECTORS[side].dot(natural_vector))


def apply_parts_offscreen(context, parts, info, camera_module):
    """Push ordinary parts along their own direction until they clear the frame.

    Only the distance changes: the direction the explosion already chose is
    kept, so parts still fly in from wherever the settings say. The computed
    distance is a minimum, which leaves any part that already travels further
    exactly where it was and keeps layered spacing above the threshold.
    Returns the names of parts that cannot clear the frame along their
    direction, which happens when they travel straight away from the camera.
    """
    props = context.scene.eas
    if not props.parts_offscreen or info is None:
        return []

    stuck = []
    for part in parts:
        obj = part.obj
        if obj.eas.exclude or is_enclosure(props, obj):
            continue
        if part.offset.length <= EPSILON:
            continue  # pinned by the direction mode, e.g. the board itself

        direction = part.offset.normalized()
        needed = camera_module.offscreen_distance(
            info, part.center, part_radius(part), direction, props.enclosure_camera_margin
        )
        if needed is None:
            stuck.append(obj.name)
            continue
        if needed > part.offset.length:
            part.offset = direction * needed
            part.basis_exploded = _exploded_basis(props, part, AXIS_VECTORS[props.axis])

    return stuck


def apply_enclosure_camera_rules(context, parts, center, info, camera_module):
    """Re-place enclosure panels so the camera never sees them waiting.

    Runs after the first explosion pass, because the camera framing depends on
    where the parts go and the panel placement depends on the camera.
    Returns a list of (object, side, distance) describing what changed.
    """
    props = context.scene.eas
    if not props.use_phases or info is None:
        return []

    if not (props.enclosure_offscreen or props.enclosure_avoid_camera):
        return []

    positions = info.positions()
    changes = []

    for part in parts:
        obj = part.obj
        if obj.eas.exclude or not is_enclosure(props, obj):
            continue

        side = resolved_side(obj, part.center - center)

        if props.enclosure_avoid_camera:
            # Worst case over the whole shot, so a moving camera cannot catch
            # the panel sweeping in from its side later on.
            worst = None
            for position in positions:
                towards = position - part.center
                if towards.length <= EPSILON:
                    continue
                towards.normalize()
                if worst is None or SIDE_VECTORS[side].dot(towards) > SIDE_VECTORS[side].dot(worst):
                    worst = towards
            if worst is not None:
                side = choose_entry_side(side, worst)

        direction = SIDE_VECTORS[side].copy()
        distance = _magnitude_for(props, part, center, 0.0)

        if props.enclosure_offscreen:
            radius = part_radius(part)
            needed = camera_module.offscreen_distance(
                info, part.center, radius, direction, props.enclosure_camera_margin
            )
            if needed is None:
                # This side can never clear the frame; fall back to the side
                # that can, scored the same way as the camera avoidance.
                for candidate in sorted(
                    SIDE_ORDER,
                    key=lambda s: -SIDE_VECTORS[s].dot(SIDE_VECTORS[side]),
                ):
                    alternative = camera_module.offscreen_distance(
                        info, part.center, radius, SIDE_VECTORS[candidate],
                        props.enclosure_camera_margin,
                    )
                    if alternative is not None:
                        side = candidate
                        direction = SIDE_VECTORS[candidate].copy()
                        needed = alternative
                        break
            if needed is not None:
                distance = max(distance, needed)

        part.offset = direction * distance
        part.basis_exploded = _exploded_basis(props, part, AXIS_VECTORS[props.axis])
        changes.append((obj, side, distance))

    return changes


def order_parts(context, parts, reverse=False):
    """Return the parts in the order they should move, and tag ``sequence``."""
    props = context.scene.eas
    mode = props.order_mode

    if mode == 'MANUAL':
        ordered = sorted(parts, key=lambda part: (part.obj.eas.order, part.obj.name))
    elif mode == 'NAME':
        ordered = sorted(parts, key=lambda part: part.obj.name)
    elif mode == 'COLLECTION':
        ordered = list(parts)
    elif mode == 'AXIS':
        # Top parts leave first.
        ordered = sorted(parts, key=lambda part: -part.sort_key)
    else:  # DISTANCE - outermost parts leave first
        ordered = sorted(parts, key=lambda part: -abs(part.sort_key))

    if props.reverse_order:
        ordered.reverse()

    if props.use_phases:
        # Explode opens the shell before the parts come out; the mirror below
        # then makes Assemble land the parts first and close the shell last.
        ordered.sort(key=lambda part: 0 if is_enclosure(props, part.obj) else 1)

    if reverse:
        ordered.reverse()

    for index, part in enumerate(ordered):
        part.sequence = index
    return ordered


def split_phases(props, ordered):
    """Split an ordered part list into the contiguous role runs it already has.

    Returns a list of (parts, is_enclosure) in play order; a single group when
    phases are off or every part shares one role.
    """
    if not props.use_phases or not ordered:
        return [(ordered, False)]

    groups = []
    for part in ordered:
        flag = is_enclosure(props, part.obj)
        if groups and groups[-1][1] == flag:
            groups[-1][0].append(part)
        else:
            groups.append(([part], flag))
    return [(items, flag) for items, flag in groups]


def derived_enclosure_window(props):
    """The enclosure window the automatic Parts Share / Phase Delay split gives.

    Used to seed the explicit frame fields, so switching to a custom range
    starts from what was already happening instead of from arbitrary numbers.
    """
    low, high = parts_frame_range(props)
    span = max(high - low, 0.0)
    gap = min(float(props.phase_gap_frames), span * 0.8)
    usable = max(span - gap, 0.0)
    return low + usable * props.parts_share + gap, high


def enclosure_window(props):
    """The explicit enclosure frame range, ordered and never inverted."""
    return ordered_frames(props.enclosure_frame_start, props.enclosure_frame_end)


def build_timing(props, ordered):
    """Frame range for every part, honouring the enclosure phase split.

    Returns a dict keyed by object name so callers do not depend on ordering.
    """
    low, high = parts_frame_range(props)
    groups = split_phases(props, ordered)

    # An explicit enclosure range detaches the shell from the automatic split
    # entirely: the parts keep their own window and the shell keeps this one.
    explicit = enclosure_window(props) if (
        props.use_phases and props.enclosure_custom_range
    ) else None

    if len(groups) < 2:
        parts, is_shell = groups[0] if groups else ([], False)
        window = explicit if (is_shell and explicit) else (low, high)
        return {
            part.obj.name: _staggered(index, len(parts), window[0], window[1], props)
            for index, part in enumerate(parts)
        }

    if explicit is not None:
        bounds = [explicit if flag else (low, high) for _items, flag in groups]
    else:
        # Two phases: parts get their share of the range, the shell gets the
        # rest, with an explicit pause between them. Because every part in a
        # group ends at or before the group's last frame, the shell can never
        # start moving before the last part has landed.
        span = max(high - low, 0.0)
        gap = min(float(props.phase_gap_frames), span * 0.8)
        usable = max(span - gap, 0.0)
        first_is_enclosure = groups[0][1]
        share = props.parts_share
        first_len = usable * ((1.0 - share) if first_is_enclosure else share)
        second_len = usable - first_len
        bounds = [
            (low, low + first_len),
            (low + first_len + gap, low + first_len + gap + second_len),
        ]

    timing = {}
    for (parts, _flag), (group_low, group_high) in zip(groups, bounds):
        for index, part in enumerate(parts):
            timing[part.obj.name] = _staggered(index, len(parts), group_low, group_high, props)
    return timing


def _staggered(index, count, low, high, props):
    """Stagger one part inside a frame window."""
    if not props.use_sequence or count <= 1 or high <= low:
        return low, high
    overlap = min(max(props.overlap, 0.0), 0.999)
    span = high - low
    segment = span / (count - (count - 1) * overlap)
    step = segment * (1.0 - overlap)
    part_start = low + index * step
    return part_start, min(part_start + segment, high)


def parts_frame_range(props):
    """The frames the components move over, inside the overall shot.

    Anything outside this window is time the camera still moves through, so a
    shot can open before anything assembles and carry on afterwards.
    """
    if props.component_custom_range:
        return ordered_frames(props.component_frame_start, props.component_frame_end)
    low, high = frame_range_of(props)
    return float(low), float(high)


def ordered_frames(first, second):
    """A start/end pair that is never inverted or zero length."""
    low = float(min(first, second))
    high = float(max(first, second))
    if high <= low:
        high = low + 1.0
    return low, high


# ---------------------------------------------------------------------------
# animation channel helpers
# ---------------------------------------------------------------------------

def fcurve_owner(obj):
    """Return the container exposing ``.fcurves`` for the object's action.

    Blender 4.4 moved keyframes into action slots/channelbags while keeping the
    legacy ``Action.fcurves`` accessor. Try the legacy path first, then walk the
    slotted structure.
    """
    anim = obj.animation_data
    if anim is None or anim.action is None:
        return None
    action = anim.action

    legacy = getattr(action, 'fcurves', None)
    if legacy is not None and len(legacy):
        return action

    slot = getattr(anim, 'action_slot', None)
    if slot is None:
        return action if legacy is not None else None

    for layer in getattr(action, 'layers', ()):
        for strip in getattr(layer, 'strips', ()):
            channelbag = None
            getter = getattr(strip, 'channelbag', None)
            if getter is not None:
                try:
                    channelbag = getter(slot)
                except (TypeError, RuntimeError):
                    channelbag = None
            if channelbag is not None and hasattr(channelbag, 'fcurves'):
                return channelbag
    return action if legacy is not None else None


def iter_fcurves(obj, paths=TRANSFORM_PATHS):
    owner = fcurve_owner(obj)
    if owner is None:
        return []
    return [curve for curve in owner.fcurves if curve.data_path in paths]


def clear_transform_animation(obj, paths=TRANSFORM_PATHS):
    """Remove the add-on's transform channels, keeping any other animation."""
    owner = fcurve_owner(obj)
    if owner is None:
        return 0
    removed = 0
    for curve in [c for c in owner.fcurves if c.data_path in paths]:
        owner.fcurves.remove(curve)
        removed += 1
    if len(owner.fcurves) == 0 and obj.animation_data is not None:
        obj.animation_data_clear()
    return removed


def apply_interpolation(obj, interpolation, easing, paths=TRANSFORM_PATHS):
    for curve in iter_fcurves(obj, paths):
        for keyframe in curve.keyframe_points:
            keyframe.interpolation = interpolation
            if interpolation not in {'CONSTANT', 'LINEAR', 'BEZIER'}:
                keyframe.easing = easing
        curve.update()


def key_transform(obj, frame, rotate=False, group=None):
    """Insert location (and optionally rotation) keys at ``frame``."""
    group = group or obj.name
    obj.keyframe_insert(data_path='location', frame=frame, group=group)
    if rotate:
        obj.keyframe_insert(data_path=rotation_data_path(obj), frame=frame, group=group)


def _ease_in(t, interpolation):
    """The ease-in half of each interpolation curve, on t in [0, 1]."""
    if interpolation == 'LINEAR':
        return t
    if interpolation == 'SINE':
        return 1.0 - math.cos(t * math.pi * 0.5)
    if interpolation == 'QUAD':
        return t * t
    if interpolation == 'CUBIC' or interpolation == 'BEZIER':
        return t * t * t
    if interpolation == 'EXPO':
        return 0.0 if t <= 0.0 else math.pow(2.0, 10.0 * (t - 1.0))
    if interpolation == 'BACK':
        overshoot = 1.70158
        return t * t * ((overshoot + 1.0) * t - overshoot)
    if interpolation == 'ELASTIC':
        if t <= 0.0 or t >= 1.0:
            return t
        period = 0.3
        return -math.pow(2.0, 10.0 * (t - 1.0)) * math.sin(
            (t - 1.0 - period / 4.0) * (2.0 * math.pi) / period
        )
    return t


def evaluate_easing(t, interpolation, easing):
    """Map linear time to eased time, matching Blender's F-curve shapes.

    Arc segments are baked as sampled keyframes, so the easing has to be
    applied to the sample spacing rather than left to the F-curve.
    """
    t = min(max(t, 0.0), 1.0)
    if interpolation == 'LINEAR':
        return t
    if interpolation == 'BEZIER':
        # Blender's default bezier handles read as a smooth ease in and out.
        return t * t * (3.0 - 2.0 * t)

    direction = easing
    if direction == 'AUTO':
        direction = 'EASE_IN_OUT'

    if direction == 'EASE_IN':
        return _ease_in(t, interpolation)
    if direction == 'EASE_OUT':
        return 1.0 - _ease_in(1.0 - t, interpolation)
    if t < 0.5:
        return _ease_in(t * 2.0, interpolation) * 0.5
    return 1.0 - _ease_in((1.0 - t) * 2.0, interpolation) * 0.5


def frame_range_of(props):
    start = min(props.frame_start, props.frame_end)
    end = max(props.frame_start, props.frame_end)
    return start, end


def degrees(value):
    return math.degrees(value)
