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
        'group', 'shell',
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
        # Alone until compute_explosion says otherwise, so every code path that
        # groups by this key behaves exactly as it did before grouping existed.
        self.group = obj.name
        self.shell = False


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

    # Choosing an enclosure collection in the add-on's own panel says those
    # objects belong to the assembly. Requiring them to *also* sit inside the
    # Source collection was a hidden coupling: the panels were named, tagged
    # and listed, and then silently never animated.
    if props.enclosure_collection is not None:
        candidates += list(props.enclosure_collection.all_objects)

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


def _layer_path(layer, collection, trail=None):
    """Layer collections from the root down to ``collection``, or None."""
    trail = (trail or []) + [layer]
    if layer.collection == collection:
        return trail
    for child in layer.children:
        found = _layer_path(child, collection, trail)
        if found:
            return found
    return None


def visibility_reason(context, collection):
    """Which switch is hiding a collection, named the way the Outliner names it.

    Exclusion, the eye and the monitor are three different controls in three
    different places, and inheriting from a parent collection means the one to
    click may not even be on the row you are looking at.
    """
    path = _layer_path(context.view_layer.layer_collection, collection) or []
    for layer in path:
        name = layer.collection.name
        if layer.exclude:
            return f"'{name}' is excluded from the view layer (the checkbox in the Outliner)"
        if layer.hide_viewport:
            return f"'{name}' is hidden in the Outliner (the eye icon)"
        if layer.collection.hide_viewport:
            return f"'{name}' is disabled in viewports (the monitor icon)"
    return "the objects are hidden one by one"


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
                f"All {len(usable)} object(s) in '{collection.name}' are invisible because "
                f"{visibility_reason(context, collection)}. Fix that in the Outliner, or press "
                "Use Hidden Objects to work on them where they are"
            )

    return f"Source collection '{collection.name}' has no usable objects"


def missing_from_source(context, collection):
    """Split a collection's objects into (hidden, outside, parented).

    Three reasons an object never reaches the animation, and three different
    places to fix it: unhide it in the outliner, point Source at something that
    holds it, or turn off Skip Parented Children so a panel stops riding along
    with the part it hangs off.
    """
    props = context.scene.eas
    if collection is None:
        return [], [], []

    collected = list(collect_objects(context))
    reachable = {obj.name for obj in collected}
    members = set(collected)
    if props.source == 'COLLECTION' and props.collection is not None:
        in_source = {obj.name for obj in props.collection.all_objects}
    else:
        in_source = {obj.name for obj in context.selected_objects}
    # The enclosure collection is a source in its own right.
    if props.enclosure_collection is not None:
        in_source |= {obj.name for obj in props.enclosure_collection.all_objects}

    hidden, outside, parented = [], [], []
    for obj in collection.all_objects:
        if obj.type in SKIPPED_TYPES or obj.name in reachable:
            continue
        if obj.name not in in_source:
            outside.append(obj.name)
        elif props.visible_only and not obj.visible_get():
            hidden.append(obj.name)
        elif props.skip_child_parts and _has_ancestor_in(obj, members):
            # Dropped on purpose: it follows a part that *is* animated. Only a
            # surviving ancestor is checked, because the chain above a dropped
            # object always ends at one.
            parented.append(obj.name)
        else:
            hidden.append(obj.name)
    return hidden, outside, parented


def unreachable(context, objects):
    """The names among ``objects`` the add-on cannot collect right now.

    Marking a role is only half the job - an object outside the Source set is
    never animated - so the operators that mark things ask this before calling
    it a success.
    """
    reachable = {obj.name for obj in collect_objects(context)}
    return [obj.name for obj in objects if obj.name not in reachable]


def enclosure_report(context):
    """Say why nothing counts as a shell panel, with the numbers behind it.

    Membership has two independent sources - the collection and the per object
    role - so the message names both, and how much of the collection the add-on
    can actually see.
    """
    props = context.scene.eas
    collection = props.enclosure_collection
    tagged = sum(
        1 for obj in context.view_layer.objects
        if obj.eas.role == 'ENCLOSURE' and not obj.eas.is_rig
    )

    if collection is None:
        where = "no enclosure collection is set"
    else:
        usable = [obj for obj in collection.all_objects if obj.type not in SKIPPED_TYPES]
        reachable = {obj.name for obj in collect_objects(context)}
        inside = sum(1 for obj in usable if obj.name in reachable)
        where = (
            f"enclosure collection '{collection.name}' holds {len(usable)} object(s), "
            f"{inside} of them in range"
        )

    return (
        f"Nothing is an enclosure panel yet: {where}, and {tagged} object(s) are marked "
        "Enclosure by hand. Pick an enclosure collection, or select the panels and press "
        "Mark Enclosure"
    )


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


def group_key(props, obj):
    """Which unit this object moves with. Distinct keys move independently."""
    mode = props.group_mode

    if mode == 'COLLECTION':
        # users_collection is ordered, so the first entry is stable for an
        # object that has been linked into more than one place.
        collections = obj.users_collection
        if collections:
            return ('collection', collections[0].name)

    elif mode == 'PREFIX':
        separator = props.group_separator
        if separator:
            head, found, _tail = obj.name.partition(separator)
            if found and head:
                return ('prefix', head)

    return ('object', obj.name)


#: Boxes are padded by this before overlap is measured, so a flat object with
#: no thickness on one axis can still be found inside something.
BOX_PAD = 1e-6


def _overlap_scores(low_a, high_a, low_b, high_b):
    """(shared fraction of the smaller box, size ratio) for two boxes.

    The shared fraction is measured against the smaller of the two on purpose:
    a chip body swallowing its own pins should read as one part, while the same
    chip merely standing on a board that dwarfs it should not.

    The size ratio is what separates a sibling from a container. Boxes are the
    only thing available here and a hollow shell's box holds the entire product,
    so containment alone would make the case and everything in it one part.
    """
    shared = 1.0
    volume_a = 1.0
    volume_b = 1.0
    for axis in range(3):
        low = max(low_a[axis] - BOX_PAD, low_b[axis] - BOX_PAD)
        high = min(high_a[axis] + BOX_PAD, high_b[axis] + BOX_PAD)
        if high <= low:
            return 0.0, 0.0
        shared *= high - low
        volume_a *= high_a[axis] - low_a[axis] + 2.0 * BOX_PAD
        volume_b *= high_b[axis] - low_b[axis] + 2.0 * BOX_PAD

    smaller = min(volume_a, volume_b)
    larger = max(volume_a, volume_b)
    if smaller <= 0.0 or larger <= 0.0:
        return 0.0, 0.0
    return shared / smaller, smaller / larger


def _find(parent, item):
    root = item
    while parent[root] != root:
        root = parent[root]
    while parent[item] != root:  # path compression, so deep chains stay cheap
        parent[item], item = root, parent[item]
    return root


def overlap_role(props, obj):
    """The boundary grouping must never cross.

    A shell panel and an ordinary part move in different phases, so a group
    spanning both could not be animated at all - and a case wrapped round a
    product contains every part of it by definition. Two panels that open
    towards different sides are the same problem one level down: a lid and a
    base overlap at the seam, and joining them would send both the same way.
    """
    if not is_enclosure_member(props, obj):
        return None
    return obj.eas.side


def _overlap_assignments(objects, boxes, roles, threshold, size_match):
    """Cluster objects whose boxes sit inside each other, transitively.

    Sweep and prune along X rather than testing every pair: an assembly of a
    few thousand parts is spread out along the board, so the active list stays
    short. One big object - the board itself - simply stays active for the whole
    sweep, which costs one comparison per part rather than blowing up.

    Objects only ever join within one :func:`overlap_role`.
    """
    usable = [obj.name for obj in objects if boxes.get(obj.name) is not None]
    parent = {name: name for name in usable}

    order = sorted(usable, key=lambda name: boxes[name][0].x)
    active = []
    for name in order:
        low, high = boxes[name]
        active = [other for other in active if boxes[other][1].x >= low.x]
        for other in active:
            if roles.get(name) != roles.get(other):
                continue
            other_low, other_high = boxes[other]
            shared, ratio = _overlap_scores(low, high, other_low, other_high)
            if shared >= threshold and ratio >= size_match:
                root_a, root_b = _find(parent, name), _find(parent, other)
                if root_a != root_b:
                    parent[root_a] = root_b
        active.append(name)

    return {
        obj.name: ('overlap', _find(parent, obj.name)) if obj.name in parent
        else ('object', obj.name)
        for obj in objects
    }


def group_assignments(props, objects, matrices=None):
    """``{object name: group key}`` under the current Move Together rule.

    ``matrices`` supplies world transforms by name, for callers that have
    already resolved the assembled pose; without it each object is measured
    where it stands.
    """
    mode = props.group_mode
    if mode == 'NONE':
        return {obj.name: ('object', obj.name) for obj in objects}

    if mode == 'OVERLAP':
        boxes = {}
        roles = {}
        for obj in objects:
            world = matrices.get(obj.name) if matrices else obj.matrix_world
            corners = bound_corners(obj, world) if world is not None else None
            boxes[obj.name] = bounds_of(corners) if corners else None
            roles[obj.name] = overlap_role(props, obj)
        return _overlap_assignments(
            objects, boxes, roles, props.group_overlap, props.group_size_match
        )

    return {obj.name: group_key(props, obj) for obj in objects}


#: Last group_sizes answer, so panel redraws do not re-cluster the assembly.
_SIZES_CACHE = {}


def group_sizes(props, objects):
    """``{group key: member count}``, cached for the panel's sake.

    Overlap clustering is far too heavy to run on every redraw of a sidebar
    panel, and the answer only moves when the rule or the object set does.
    """
    signature = (
        props.group_mode,
        props.group_separator,
        round(props.group_overlap, 6),
        round(props.group_size_match, 6),
        props.enclosure_collection.name if props.enclosure_collection else None,
        len(objects),
        # Role and side feed the overlap boundary, so tagging a panel has to
        # invalidate this as surely as adding an object does.
        hash(tuple((obj.name, obj.eas.role, obj.eas.side) for obj in objects)),
    )
    if _SIZES_CACHE.get('signature') == signature:
        return _SIZES_CACHE['sizes']

    sizes = {}
    for key in group_assignments(props, objects).values():
        sizes[key] = sizes.get(key, 0) + 1

    _SIZES_CACHE['signature'] = signature
    _SIZES_CACHE['sizes'] = sizes
    return sizes


def iter_groups(parts):
    """The parts split into groups, in first-appearance order."""
    order = []
    blocks = {}
    for part in parts:
        if part.group not in blocks:
            blocks[part.group] = []
            order.append(part.group)
        blocks[part.group].append(part)
    return [blocks[key] for key in order]


def _apply_grouping(props, parts):
    """Give every member of a group one shared centre, and return the groups.

    Direction, distance, layer rank and the rotation pivot are all derived from
    ``part.center``, so a common centre is enough to make the members travel as
    one rigid piece - there is no special case anywhere downstream. The offsets
    are still equalised afterwards, because per object overrides can pull two
    members of a group apart even from the same centre.
    """
    for part in parts:
        part.shell = is_enclosure(props, part.obj)

    if props.group_mode == 'NONE':
        return [[part] for part in parts]

    keys = group_assignments(
        props,
        [part.obj for part in parts],
        {part.obj.name: part.world_assembled for part in parts},
    )
    for part in parts:
        part.group = keys[part.obj.name]

    blocks = iter_groups(parts)
    for members in blocks:
        if len(members) < 2:
            continue

        points = []
        for part in members:
            points.extend(bound_corners(part.obj, part.world_assembled))
        if points:
            low, high = bounds_of(points)
            centre = (low + high) * 0.5
            for part in members:
                part.center = centre.copy()

        # A group is a single part, so it is a shell panel or it is not.
        if any(part.shell for part in members):
            for part in members:
                part.shell = True

    return blocks


def _share_offsets(props, blocks, axis):
    """Make every member of a group carry the group's offset.

    Distance multipliers and hand set sides are per object, so two members can
    come out of the explosion with different offsets even from a shared centre.
    The first movable member wins; anything explicitly excluded still stays put.
    """
    for members in blocks:
        if len(members) < 2:
            continue
        movable = [part for part in members if not part.obj.eas.exclude]
        if len(movable) < 2:
            continue
        offset = movable[0].offset
        for part in movable[1:]:
            if (part.offset - offset).length <= EPSILON:
                continue
            part.offset = offset.copy()
            part.basis_exploded = _exploded_basis(props, part, axis)


def compute_explosion(context, parts):
    """Fill in ``offset``, ``rank`` and ``basis_exploded`` on every part.

    Returns the assembly center that was used.
    """
    props = context.scene.eas
    center = assembly_center(context, parts)
    axis = AXIS_VECTORS[props.axis]
    size = assembly_radius(parts, center)
    band = size * props.layer_tolerance

    # Grouping comes after the assembly centre, which is measured from where the
    # objects really are, and before everything that reads part.center.
    blocks = _apply_grouping(props, parts)

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

    _share_offsets(props, blocks, axis)

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
    if part.shell:
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

    if part.shell:
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
    for members in iter_groups(parts):
        movers = [
            part for part in members
            if not part.obj.eas.exclude and not part.shell
            and part.offset.length > EPSILON  # not pinned, e.g. the board itself
        ]
        if not movers:
            continue

        # One test for the whole group: the members share a centre and a
        # direction, so the distance that clears the frame is whichever of them
        # sticks out furthest.
        lead = movers[0]
        direction = lead.offset.normalized()
        radius = max(part_radius(part) for part in movers)
        needed = camera_module.offscreen_distance(
            info, lead.center, radius, direction, props.enclosure_camera_margin
        )
        if needed is None:
            stuck.extend(part.obj.name for part in movers)
            continue

        for part in movers:
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

    for members in iter_groups(parts):
        panels = [part for part in members if not part.obj.eas.exclude and part.shell]
        if not panels:
            continue

        # The group opens as one panel: the first member's side leads, and the
        # travel is whatever gets the whole group clear.
        part = panels[0]
        obj = part.obj
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
            radius = max(part_radius(member) for member in panels)
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

        for member in panels:
            member.offset = direction * distance
            member.basis_exploded = _exploded_basis(props, member, AXIS_VECTORS[props.axis])
            changes.append((member.obj, side, distance))

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

    if props.group_mode != 'NONE':
        # Whatever the sort said, the members of one part belong side by side:
        # the group takes the position of whichever member came first.
        ordered = [part for members in iter_groups(ordered) for part in members]

    if props.use_phases:
        # Explode opens the shell before the parts come out; the mirror below
        # then makes Assemble land the parts first and close the shell last.
        ordered.sort(key=lambda part: 0 if part.shell else 1)

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
        flag = part.shell
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
        return _windows(parts, window[0], window[1], props)

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
    for (parts, _flag), (phase_low, phase_high) in zip(groups, bounds):
        timing.update(_windows(parts, phase_low, phase_high, props))
    return timing


def _windows(parts, low, high, props):
    """One frame window per group, shared by every member of it.

    Sequencing counts groups, not objects, so a component made of five pieces
    takes one slot in the stagger rather than five.
    """
    blocks = iter_groups(parts)
    timing = {}
    for position, members in enumerate(blocks):
        window = _staggered(position, len(blocks), low, high, props)
        for part in members:
            timing[part.obj.name] = window
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
