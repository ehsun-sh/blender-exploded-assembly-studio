"""Restore points for the add-on's settings and part placement.

A snapshot is a JSON payload holding every scene setting, the camera path, and
each part's transform and per object data. It lives in the .blend, so it
survives saving and reloading — but it is stored *inside* the file, so it is a
complement to saving, not a replacement for it.

JSON rather than a mirrored set of properties, because settings get added and
renamed between versions and a snapshot taken by an older build should still be
readable: anything unknown on restore is skipped rather than failing.
"""

import json

import bpy

from . import core

#: Settings that describe the snapshot machinery itself, or that mean nothing
#: outside the moment they were written.
SKIPPED_SETTINGS = {'rna_type', 'snapshots', 'snapshot_index', 'camera_poses', 'last_report'}

#: Where each kind of ID pointer is looked up when restoring.
ID_COLLECTIONS = {
    'Collection': 'collections',
    'Object': 'objects',
    'Scene': 'scenes',
    'Material': 'materials',
}


def pointer_source(props, name):
    """The bpy.data collection a pointer setting resolves against.

    Derived from the property's own type rather than a hand written map, so a
    pointer added later cannot be silently looked up in the wrong place and
    come back as None.
    """
    prop = props.bl_rna.properties.get(name)
    fixed = getattr(prop, 'fixed_type', None)
    if fixed is None:
        return None
    return ID_COLLECTIONS.get(fixed.identifier)

OBJECT_FIELDS = ('role', 'side', 'order', 'distance_multiplier', 'exclude', 'has_state')

POSE_FIELDS = ('lens', 'position', 'motion', 'roll', 'interpolation', 'easing')


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------

def _capture_settings(props):
    values = {}
    for prop in props.bl_rna.properties:
        name = prop.identifier
        if name in SKIPPED_SETTINGS or prop.is_readonly:
            continue

        if prop.type == 'POINTER':
            target = getattr(props, name, None)
            values[name] = {'__ref__': target.name if target is not None else None}
        elif prop.type == 'COLLECTION':
            continue
        elif getattr(prop, 'array_length', 0) > 1:
            values[name] = list(getattr(props, name))
        else:
            values[name] = getattr(props, name)
    return values


def _snapshot_objects(context):
    """Every object the add-on has an opinion about right now."""
    objects = list(core.collect_objects(context))
    seen = {obj.name for obj in objects}
    for obj in context.view_layer.objects:
        if obj.name in seen or obj.eas.is_rig:
            continue
        settings = obj.eas
        if settings.has_state or settings.role != 'PART' or settings.exclude:
            objects.append(obj)
            seen.add(obj.name)
    return objects


def capture(context):
    """Build the snapshot payload for the current state."""
    props = context.scene.eas

    objects = {}
    for obj in _snapshot_objects(context):
        entry = {field: getattr(obj.eas, field) for field in OBJECT_FIELDS}
        entry['basis'] = core.matrix_to_flat(obj.matrix_basis)
        entry['assembly_matrix'] = list(obj.eas.assembly_matrix)
        objects[obj.name] = entry

    poses = []
    for pose in props.camera_poses:
        entry = {field: getattr(pose, field) for field in POSE_FIELDS}
        entry['matrix'] = list(pose.matrix)
        poses.append(entry)

    return {
        'version': 1,
        'settings': _capture_settings(props),
        'objects': objects,
        'camera_poses': poses,
    }


def describe(payload):
    """Short human readable summary for the snapshot list."""
    objects = len(payload.get('objects', {}))
    poses = len(payload.get('camera_poses', []))
    parts = [f"{objects} object{'s' if objects != 1 else ''}"]
    if poses:
        parts.append(f"{poses} viewpoint{'s' if poses != 1 else ''}")
    return ", ".join(parts)


def to_json(payload):
    return json.dumps(payload, separators=(',', ':'))


def from_json(text):
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

def _is_reference(value):
    return isinstance(value, dict) and '__ref__' in value


def _restore_settings(props, values):
    # Pointers go back first, then everything else. Assigning a pointer can run
    # an update that switches a companion setting on - picking the enclosure
    # collection turns the enclosure phase on - and the snapshot's own value has
    # to be the one that survives.
    for name, value in sorted(values.items(), key=lambda item: not _is_reference(item[1])):
        if not hasattr(props, name):
            continue  # written by a version that had a setting this one lacks

        if _is_reference(value):
            target = None
            reference = value['__ref__']
            if reference:
                attribute = pointer_source(props, name)
                source = getattr(bpy.data, attribute, None) if attribute else None
                if source is not None:
                    target = source.get(reference)
            try:
                setattr(props, name, target)
            except (TypeError, ValueError, AttributeError):
                pass
            continue

        try:
            setattr(props, name, value)
        except (TypeError, ValueError, AttributeError):
            # An enum item that no longer exists, or a changed type.
            pass


def _restore_poses(props, poses):
    props.camera_poses.clear()
    for entry in poses:
        pose = props.camera_poses.add()
        matrix = entry.get('matrix')
        if matrix and len(matrix) == 16:
            pose.matrix = matrix
        for field in POSE_FIELDS:
            if field in entry:
                try:
                    setattr(pose, field, entry[field])
                except (TypeError, ValueError):
                    pass
    props.camera_pose_index = min(props.camera_pose_index, max(len(props.camera_poses) - 1, 0))


def apply(context, payload, clear_animation=True):
    """Put the scene back to a snapshot.

    Returns (restored, missing) object name counts. Generated transform
    animation is removed by default, because a snapshot means "back to here"
    and leftover keyframes would drive the parts straight off it again.
    """
    props = context.scene.eas

    _restore_settings(props, payload.get('settings', {}))
    _restore_poses(props, payload.get('camera_poses', []))

    restored = []
    missing = []
    for name, entry in payload.get('objects', {}).items():
        obj = context.scene.objects.get(name)
        if obj is None:
            missing.append(name)
            continue

        for field in OBJECT_FIELDS:
            if field in entry:
                try:
                    setattr(obj.eas, field, entry[field])
                except (TypeError, ValueError):
                    pass

        assembly = entry.get('assembly_matrix')
        if assembly and len(assembly) == 16:
            obj.eas.assembly_matrix = assembly

        if clear_animation:
            core.clear_transform_animation(obj)

        basis = entry.get('basis')
        if basis and len(basis) == 16:
            core.apply_basis(obj, core.flat_to_matrix(basis))

        restored.append(name)

    if clear_animation:
        from . import camera as camera_module
        camera_module.clear_camera_animation(context)

    # last_build_mode comes back with the settings on purpose: with every
    # setting restored, pressing Rebuild reproduces the animation that existed
    # when the snapshot was taken.
    context.view_layer.update()
    return restored, missing
