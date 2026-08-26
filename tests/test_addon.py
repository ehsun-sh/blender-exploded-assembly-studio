"""Headless test for Exploded Assembly Studio.

Run with:

    blender.exe -b --factory-startup --python tests/test_addon.py

Builds a mock PCB product (bottom shell, PCB, components, connector, top shell,
screws), drives the add-on through the whole workflow and checks that parts come
back to their exact assembled transforms.
"""

import math
import os
import sys

import bpy
from mathutils import Vector

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TOLERANCE = 1e-5

FAILURES = []
CHECKS = [0]


def check(condition, message):
    CHECKS[0] += 1
    if condition:
        print(f"  ok   | {message}")
    else:
        print(f"  FAIL | {message}")
        FAILURES.append(message)


def close(a, b, tolerance=TOLERANCE):
    return abs(a - b) <= tolerance


def matrices_equal(a, b, tolerance=TOLERANCE):
    return max(abs(x - y) for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b)) <= tolerance


# ---------------------------------------------------------------------------
# scene
# ---------------------------------------------------------------------------

def add_box(name, size, location, collection):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = Vector(size)
    for other in list(obj.users_collection):
        other.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    collection = bpy.data.collections.new("PRODUCT_ASSEMBLY")
    scene.collection.children.link(collection)

    parts = {}
    parts['bottom_case'] = add_box("Bottom_Case", (0.12, 0.08, 0.02), (0, 0, -0.012), collection)
    parts['pcb'] = add_box("PCB", (0.10, 0.06, 0.0016), (0, 0, 0), collection)

    for index, (x, y) in enumerate([(-0.03, 0.015), (0.02, 0.02), (0.03, -0.015), (-0.02, -0.02)]):
        name = f"Component_{index + 1}"
        parts[name] = add_box(name, (0.012, 0.010, 0.004), (x, y, 0.0028), collection)

    parts['connector'] = add_box("Connector", (0.02, 0.012, 0.006), (0.04, 0.0, 0.0038), collection)
    parts['top_case'] = add_box("Top_Case", (0.12, 0.08, 0.018), (0, 0, 0.014), collection)

    for index, (x, y) in enumerate([(-0.05, 0.03), (0.05, 0.03), (0.05, -0.03), (-0.05, -0.03)]):
        name = f"Screw_{index + 1}"
        parts[name] = add_box(name, (0.004, 0.004, 0.006), (x, y, 0.024), collection)

    return scene, collection, parts


def select(objects, active=None):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[0]


def world_matrices(objects):
    bpy.context.view_layer.update()
    return {obj.name: obj.matrix_world.copy() for obj in objects}


def at_frame(frame, objects):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    return {obj.name: obj.matrix_world.copy() for obj in objects}


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_pcb_workflow():
    print("\n[1] PCB product workflow (preset, explode, assemble)")
    scene, collection, parts = build_scene()

    import exploded_assembly_studio
    exploded_assembly_studio.register()

    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection

    objects = list(collection.all_objects)
    # The PCB is the active object, so it defines the split plane.
    select(objects, active=parts['pcb'])

    result = bpy.ops.eas.apply_preset(preset='PCB_STACK')
    check(result == {'FINISHED'}, "PCB preset applied")
    check(props.direction == 'AXIS_SPLIT', "preset selected Axis +/- direction")
    check(props.center_mode == 'ACTIVE', "preset splits around the active object")
    check(props.distance > 0.0, f"preset picked a distance from the model size ({props.distance})")

    result = bpy.ops.eas.set_assembly_position()
    check(result == {'FINISHED'}, "assembly position saved")
    check(all(obj.eas.has_state for obj in objects), "every part has a saved state")

    assembled = world_matrices(objects)

    result = bpy.ops.eas.animate(mode='EXPLODE')
    check(result == {'FINISHED'}, "explode animation built")
    check(scene.frame_start == props.frame_start, "scene frame range updated")

    start_state = at_frame(props.frame_start, objects)
    check(
        all(matrices_equal(assembled[name], start_state[name]) for name in assembled),
        "frame 1 of the explode matches the assembled model exactly",
    )

    end_state = at_frame(props.frame_end, objects)

    pcb_move = (end_state['PCB'].translation - assembled['PCB'].translation).length
    check(close(pcb_move, 0.0, 1e-6), f"PCB stays put during the explode (moved {pcb_move:.6f})")

    bottom_delta = end_state['Bottom_Case'].translation.z - assembled['Bottom_Case'].translation.z
    check(bottom_delta < -1e-4, f"bottom shell drops away downwards ({bottom_delta:+.4f})")

    top_delta = end_state['Top_Case'].translation.z - assembled['Top_Case'].translation.z
    check(top_delta > 1e-4, f"top shell lifts upwards ({top_delta:+.4f})")

    screw_delta = end_state['Screw_1'].translation.z - assembled['Screw_1'].translation.z
    check(screw_delta > top_delta, "screws travel further than the top shell")

    component_deltas = [
        end_state[f'Component_{i}'].translation.z - assembled[f'Component_{i}'].translation.z
        for i in range(1, 5)
    ]
    check(all(delta > 1e-4 for delta in component_deltas), "all components lift off the board")
    spread = max(component_deltas) - min(component_deltas)
    check(close(spread, 0.0, 1e-6), f"identical components share one layer (spread {spread:.6f})")
    check(
        component_deltas[0] < top_delta,
        "components stay below the top shell, so the stack order is preserved",
    )

    # ------------------------------------------------------------- assemble
    result = bpy.ops.eas.animate(mode='ASSEMBLE')
    check(result == {'FINISHED'}, "assemble animation built")

    final = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for row_a, row_b in zip(assembled[name], final[name]) for x, y in zip(row_a, row_b))
        for name in assembled
    )
    check(worst <= TOLERANCE, f"assemble returns every part exactly home (max error {worst:.3e})")

    exploded_start = at_frame(props.frame_start, objects)
    check(
        exploded_start['Top_Case'].translation.z > assembled['Top_Case'].translation.z,
        "assemble starts from the exploded state",
    )

    # --------------------------------------------------------------- camera
    check(props.use_camera, "preset enabled the camera")
    camera = props.camera_object
    check(camera is not None and camera.type == 'CAMERA', "camera rig was created")
    check(scene.camera == camera, "generated camera is the active scene camera")
    pivot = props.camera_pivot
    check(pivot is not None and pivot.animation_data is not None, "camera pivot is animated")

    cam_start = at_frame(props.frame_start, [camera])[camera.name].translation
    cam_end = at_frame(props.frame_end, [camera])[camera.name].translation
    check((cam_start - cam_end).length > 1e-4, "camera actually travels during the animation")

    center = Vector((0.0, 0.0, 0.0))
    radius_start = (cam_start - center).length
    check(radius_start > 0.05, f"camera sits outside the product ({radius_start:.3f} m)")

    # camera parts must never be treated as assembly parts
    from exploded_assembly_studio import core
    select(objects + [camera, pivot], active=parts['pcb'])
    props.source = 'SELECTED'
    collected = core.collect_objects(bpy.context)
    check(camera not in collected and pivot not in collected, "camera rig is excluded from the parts")
    props.source = 'COLLECTION'

    # ---------------------------------------------------------------- clear
    select(objects, active=parts['pcb'])
    result = bpy.ops.eas.clear_animation()
    check(result == {'FINISHED'}, "clear animation ran")
    check(
        all(not obj.animation_data or not obj.animation_data.action for obj in objects),
        "no transform animation is left on the parts",
    )
    cleared = world_matrices(objects)
    check(
        all(matrices_equal(assembled[name], cleared[name]) for name in assembled),
        "clearing restores the assembled model",
    )


def test_direction_modes():
    print("\n[2] Every direction mode round trips")
    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    for direction in ('CENTER', 'AXIS_SPLIT', 'WORLD_AXIS', 'LOCAL_AXIS'):
        for magnitude in ('UNIFORM', 'PROPORTIONAL', 'LAYERED'):
            props.direction = direction
            props.magnitude = magnitude
            props.distance = 0.05
            props.use_sequence = True
            props.use_rotation = True
            props.rotation_angle = math.radians(35.0)

            bpy.ops.eas.animate(mode='EXPLODE')
            exploded = at_frame(props.frame_end, objects)
            moved = sum(
                1 for name in assembled
                if (exploded[name].translation - assembled[name].translation).length > 1e-6
            )

            bpy.ops.eas.animate(mode='ASSEMBLE')
            home = at_frame(props.frame_end, objects)
            worst = max(
                max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
                for n in assembled
            )
            check(
                moved > 0 and worst <= TOLERANCE,
                f"{direction}/{magnitude}: {moved} part(s) moved, returns home (error {worst:.3e})",
            )

    props.use_rotation = False
    props.use_sequence = False


def test_parenting():
    print("\n[3] Parented and rotated parts")
    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False
    props.direction = 'CENTER'
    props.magnitude = 'UNIFORM'
    props.distance = 0.05

    # Parent the screws to the top shell and give the parent an odd transform.
    top = parts['top_case']
    top.rotation_euler = (math.radians(12.0), math.radians(-7.0), math.radians(31.0))
    bpy.context.view_layer.update()
    for index in range(1, 5):
        screw = parts[f'Screw_{index}']
        screw.parent = top
        screw.matrix_parent_inverse = top.matrix_world.inverted()
    bpy.context.view_layer.update()

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    # Children of a moving parent should follow it, not move twice.
    props.skip_child_parts = True
    bpy.ops.eas.animate(mode='EXPLODE')
    from exploded_assembly_studio import core
    screw = parts['Screw_1']
    check(not core.iter_fcurves(screw), "child part is not keyed while its parent moves")

    exploded = at_frame(props.frame_end, objects)
    offset_parent = exploded['Top_Case'].translation - assembled['Top_Case'].translation
    offset_child = exploded['Screw_1'].translation - assembled['Screw_1'].translation
    check(
        (offset_parent - offset_child).length <= 1e-6,
        "child rides along with its parent exactly once",
    )

    bpy.ops.eas.animate(mode='ASSEMBLE')
    home = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"parented assembly returns home (error {worst:.3e})")

    # Now animate children independently.
    props.skip_child_parts = False
    bpy.ops.eas.animate(mode='EXPLODE')
    check(bool(core.iter_fcurves(screw)), "child part is keyed when Skip Parented Children is off")
    bpy.ops.eas.animate(mode='ASSEMBLE')
    home = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"independent children also return home (error {worst:.3e})")
    props.skip_child_parts = True


def test_sequence_and_extras():
    print("\n[4] Sequencing, exclusion and per part distance")
    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False
    props.direction = 'CENTER'
    props.magnitude = 'UNIFORM'
    props.distance = 0.05
    props.use_sequence = True
    props.overlap = 0.0
    props.order_mode = 'DISTANCE'
    props.frame_start = 1
    props.frame_end = 100

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    parts['pcb'].eas.exclude = True
    parts['connector'].eas.distance_multiplier = 2.0

    bpy.ops.eas.animate(mode='EXPLODE')

    end = at_frame(props.frame_end, objects)
    pcb_move = (end['PCB'].translation - assembled['PCB'].translation).length
    check(close(pcb_move, 0.0, 1e-9), "excluded part never moves")

    connector_move = (end['Connector'].translation - assembled['Connector'].translation).length
    check(connector_move > props.distance * 1.5, f"per part multiplier applied ({connector_move:.4f})")

    from exploded_assembly_studio import core
    curves = core.iter_fcurves(parts['top_case'], ('location',))
    check(bool(curves), "location channels exist")
    frames = sorted({round(kp.co.x, 3) for curve in curves for kp in curve.keyframe_points})
    check(len(frames) == 2, f"two keys per part ({frames})")
    check(frames[-1] <= props.frame_end, "no key runs past the end frame")

    # With zero overlap the parts must not share the same time window.
    all_starts = set()
    for obj in objects:
        obj_curves = core.iter_fcurves(obj, ('location',))
        if obj_curves:
            all_starts.add(round(min(kp.co.x for kp in obj_curves[0].keyframe_points), 2))
    check(len(all_starts) > 1, f"staggered sequence produced {len(all_starts)} distinct start times")

    check(
        curves[0].keyframe_points[0].interpolation == props.interpolation,
        f"interpolation set to {props.interpolation}",
    )

    result = bpy.ops.eas.auto_order()
    check(result == {'FINISHED'} and props.order_mode == 'MANUAL', "order baked to parts")
    orders = sorted(obj.eas.order for obj in objects)
    check(orders == list(range(len(objects))), "baked orders are a clean sequence")

    parts['pcb'].eas.exclude = False
    props.use_sequence = False
    props.order_mode = 'DISTANCE'


def test_selection_source():
    print("\n[5] Selected Objects source and no-selection handling")
    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'SELECTED'
    props.use_camera = False
    props.direction = 'WORLD_AXIS'
    props.axis = 'Z'
    props.magnitude = 'UNIFORM'
    props.distance = 0.03

    subset = [parts['top_case'], parts['pcb'], parts['bottom_case']]
    select(subset, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(subset)

    bpy.ops.eas.animate(mode='EXPLODE')
    end = at_frame(props.frame_end, subset)
    check(
        all(
            close((end[o.name].translation - assembled[o.name].translation).z, props.distance)
            for o in subset
        ),
        "world axis mode moves every selected part the same distance",
    )

    untouched = parts['Component_1']
    check(not untouched.eas.has_state, "unselected objects are left alone")

    # An operator that reports an error raises RuntimeError through bpy.ops,
    # which is how a refusal surfaces to the user as a red status message.
    bpy.ops.object.select_all(action='DESELECT')
    try:
        bpy.ops.eas.animate(mode='EXPLODE')
        refused = False
        message = ""
    except RuntimeError as error:
        refused = True
        message = str(error)
    check(refused, "explode with nothing selected is refused, not crashed")
    check("select" in message.lower(), f"refusal explains what to do ({message.strip()})")


def test_camera_poses():
    print("\n[6] Camera poses captured from the viewport")
    from exploded_assembly_studio import camera as camera_module
    from exploded_assembly_studio import core

    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.direction = 'CENTER'
    props.magnitude = 'UNIFORM'
    props.distance = 0.05
    props.frame_start = 1
    props.frame_end = 60

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()

    # Poses that a user would capture by framing the shot in the viewport.
    # Building them from a to_track_quat aim matches what the viewport hands
    # back: an orthonormal world matrix looking at the product.
    def look_at(eye, focus=Vector((0.0, 0.0, 0.0))):
        direction = Vector(eye) - focus
        rotation = direction.to_track_quat('Z', 'Y')
        matrix = rotation.to_matrix().to_4x4()
        matrix.translation = Vector(eye)
        return matrix

    pose_a = look_at((0.35, -0.35, 0.25))
    pose_b = look_at((-0.10, -0.18, 0.06))

    props.use_camera = True
    props.camera_mode = 'POSES'
    props.camera_animate_focal = True
    props.camera_pose_start = core.matrix_to_flat(pose_a)
    props.camera_pose_start_lens = 35.0
    props.camera_pose_start_set = True
    props.camera_pose_end = core.matrix_to_flat(pose_b)
    props.camera_pose_end_lens = 85.0
    props.camera_pose_end_set = True

    check(camera_module.poses_ready(props), "both poses report as captured")

    bpy.ops.eas.animate(mode='EXPLODE')
    camera = props.camera_object
    check(camera is not None and camera.type == 'CAMERA', "pose mode created a camera")
    check(camera.parent is None, "pose camera is detached from the orbit pivot")
    check(not camera.constraints, "pose camera has no aim constraint overriding the capture")
    check(camera.rotation_mode == 'QUATERNION', "pose camera uses quaternion rotation")

    start = at_frame(props.frame_start, [camera])[camera.name]
    end = at_frame(props.frame_end, [camera])[camera.name]
    check(matrices_equal(start, pose_a, 1e-5), "first frame reproduces the captured start view")
    check(matrices_equal(end, pose_b, 1e-5), "last frame reproduces the captured end view")

    scene.frame_set(props.frame_start)
    bpy.context.view_layer.update()
    check(close(camera.data.lens, 35.0, 1e-3), f"focal starts at 35 mm ({camera.data.lens:.1f})")
    scene.frame_set(props.frame_end)
    bpy.context.view_layer.update()
    check(close(camera.data.lens, 85.0, 1e-3), f"focal ends at 85 mm ({camera.data.lens:.1f})")

    middle = at_frame((props.frame_start + props.frame_end) // 2, [camera])[camera.name]
    between = (middle.translation - pose_a.translation).length
    total = (pose_b.translation - pose_a.translation).length
    check(0.05 * total < between < 0.95 * total, "camera is genuinely travelling between the poses")

    # The captured start framing is the first frame of whatever is built, so an
    # Assemble animation must not silently play the camera backwards.
    check(not props.camera_mirror_on_assemble, "camera mirroring is off by default")
    bpy.ops.eas.animate(mode='ASSEMBLE')
    start = at_frame(props.frame_start, [camera])[camera.name]
    end = at_frame(props.frame_end, [camera])[camera.name]
    check(matrices_equal(start, pose_a, 1e-5), "assemble also starts from the captured start pose")
    check(matrices_equal(end, pose_b, 1e-5), "assemble also finishes on the captured end pose")

    scene.frame_set(props.frame_start)
    bpy.context.view_layer.update()
    check(close(camera.data.lens, 35.0, 1e-3), "assemble starts on the start pose focal length")

    # Opting in brings the old continuity behaviour back, for stitching a
    # rendered explode and assemble pass together.
    props.camera_mirror_on_assemble = True
    bpy.ops.eas.animate(mode='ASSEMBLE')
    start = at_frame(props.frame_start, [camera])[camera.name]
    end = at_frame(props.frame_end, [camera])[camera.name]
    check(matrices_equal(start, pose_b, 1e-5), "with mirroring on, assemble starts from the end pose")
    check(matrices_equal(end, pose_a, 1e-5), "with mirroring on, assemble finishes on the start pose")

    # Explode is unaffected either way.
    bpy.ops.eas.animate(mode='EXPLODE')
    start = at_frame(props.frame_start, [camera])[camera.name]
    check(matrices_equal(start, pose_a, 1e-5), "explode always starts from the captured start pose")
    props.camera_mirror_on_assemble = False

    # Switching back to orbit must restore the parented rig.
    props.camera_mode = 'ORBIT'
    bpy.ops.eas.animate(mode='EXPLODE')
    check(camera.parent is not None, "switching back to orbit re-parents the camera")
    check(bool(camera.constraints), "switching back to orbit restores the aim constraint")

    # Orbit mode has the same contract: Start Angle is the first frame.
    pivot = props.camera_pivot
    for mode in ('EXPLODE', 'ASSEMBLE'):
        bpy.ops.eas.animate(mode=mode)
        scene.frame_set(props.frame_start)
        bpy.context.view_layer.update()
        check(
            close(pivot.rotation_euler.z, props.camera_start_angle, 1e-5),
            f"orbit {mode.lower()} begins at the configured start angle",
        )

    # Missing poses must not break the explode.
    props.camera_mode = 'POSES'
    bpy.ops.eas.camera_clear_poses()
    check(not camera_module.poses_ready(props), "poses cleared")
    result = bpy.ops.eas.animate(mode='EXPLODE')
    check(result == {'FINISHED'}, "explode still succeeds when no poses are captured")

    bpy.ops.eas.clear_animation()
    check(
        not camera.animation_data or not camera.animation_data.action,
        "clear animation also strips the pose camera",
    )
    check(
        not camera.data.animation_data or not camera.data.animation_data.action,
        "clear animation strips the animated focal length too",
    )


def test_subject_framing():
    print("\n[7] Frame Object camera mode")
    import math as _math
    from exploded_assembly_studio import camera as camera_module

    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.direction = 'CENTER'
    props.magnitude = 'UNIFORM'
    props.distance = 0.08
    props.frame_start = 1
    props.frame_end = 60

    objects = list(collection.all_objects)
    pcb = parts['pcb']
    select(objects, active=pcb)
    bpy.ops.eas.set_assembly_position()

    # The PCB is 0.10 x 0.06 x 0.0016, so its bounding sphere is half the
    # diagonal of that box.
    expected_radius = Vector((0.10, 0.06, 0.0016)).length * 0.5
    center, radius = camera_module.subject_bounds(pcb)
    check(close(radius, expected_radius, 1e-6), f"subject radius measured ({radius:.5f})")
    check(center.length < 1e-6, "subject center found at the board center")

    props.use_camera = True
    props.camera_mode = 'SUBJECT'
    props.camera_focal = 50.0
    props.camera_margin = 1.25

    result = bpy.ops.eas.camera_use_active_subject()
    check(result == {'FINISHED'} and props.camera_subject == pcb, "active object became the subject")

    distance = camera_module.subject_distance(bpy.context, pcb)

    # Independently derive the distance the camera should sit at.
    fov_h = 2.0 * _math.atan(36.0 / (2.0 * 50.0))
    render = scene.render
    width = render.resolution_x * render.pixel_aspect_x
    height = render.resolution_y * render.pixel_aspect_y
    ratio = min(width, height) / max(width, height)
    fov = 2.0 * _math.atan(_math.tan(fov_h * 0.5) * ratio)
    expected = (radius * 1.25) / _math.sin(fov * 0.5)
    check(close(distance, expected, 1e-4), f"distance matches the framing formula ({distance:.4f})")

    bpy.ops.eas.animate(mode='EXPLODE')
    cam = props.camera_object
    check(cam is not None, "subject mode built a camera")
    check(props.camera_pivot is not None, "subject mode uses the orbit rig")

    pivot_location = props.camera_pivot.matrix_world.translation
    check((pivot_location - center).length < 1e-6, "orbit pivot sits on the subject, not the assembly")
    target_location = props.camera_target.matrix_world.translation
    check((target_location - center).length < 1e-6, "camera aims at the subject")

    scene.frame_set(props.frame_start)
    bpy.context.view_layer.update()
    actual = (cam.matrix_world.translation - center).length
    # The framing distance is the horizontal orbit radius; the camera is also
    # lifted by the height offset, so its true distance is the hypotenuse. The
    # dolly multiplies the radius at the first frame.
    orbit_radius = distance * props.camera_zoom_start
    height = radius * props.camera_height
    expected_eye = _math.hypot(orbit_radius, height)
    check(
        close(actual, expected_eye, 1e-3),
        f"camera really sits at the computed distance ({actual:.4f} vs {expected_eye:.4f})",
    )

    # The camera must actually look at the board.
    forward = -(cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    to_subject = (center - cam.matrix_world.translation).normalized()
    check(forward.dot(to_subject) > 0.999, "camera is pointing straight at the subject")

    # A bigger subject must push the camera further back, proportionally.
    big_distance = camera_module.subject_distance(bpy.context, parts['bottom_case'])
    _, big_radius = camera_module.subject_bounds(parts['bottom_case'])
    check(big_distance > distance, "a larger subject moves the camera further away")
    check(
        close(big_distance / distance, big_radius / radius, 1e-4),
        "distance scales with subject size",
    )

    # A longer lens must also push the camera back.
    props.camera_focal = 100.0
    long_lens = camera_module.subject_distance(bpy.context, pcb)
    check(long_lens > distance * 1.8, f"doubling the focal length roughly doubles the distance ({long_lens:.4f})")
    props.camera_focal = 50.0

    # Framing the board is much tighter than framing the whole exploded model.
    props.camera_mode = 'ORBIT'
    props.camera_auto_distance = True
    bpy.ops.eas.animate(mode='EXPLODE')
    scene.frame_set(props.frame_start)
    bpy.context.view_layer.update()
    orbit_distance = (cam.matrix_world.translation - Vector((0, 0, 0))).length
    check(orbit_distance > actual * 1.5, "orbit mode frames the whole explosion, so it pulls back further")

    # Refusing cleanly with no subject chosen.
    props.camera_mode = 'SUBJECT'
    props.camera_subject = None
    result = bpy.ops.eas.animate(mode='EXPLODE')
    check(result == {'FINISHED'}, "explode still succeeds when no subject is picked")
    try:
        bpy.ops.eas.camera_setup()
        refused = False
    except RuntimeError:
        refused = True
    check(refused, "building the rig with no subject is refused")

    # The PCB preset should wire the subject up on its own.
    select(objects, active=pcb)
    bpy.ops.eas.apply_preset(preset='PCB_STACK')
    check(props.camera_mode == 'SUBJECT', "PCB preset switched the camera to Frame Object")
    check(props.camera_subject == pcb, "PCB preset framed the active object")


def main():
    print("=" * 72)
    print(f"Exploded Assembly Studio - headless test on Blender {bpy.app.version_string}")
    print("=" * 72)

    test_pcb_workflow()
    test_direction_modes()
    test_parenting()
    test_sequence_and_extras()
    test_selection_source()
    test_camera_poses()
    test_subject_framing()

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} of {CHECKS[0]} checks FAILED")
        for failure in FAILURES:
            print(f"  - {failure}")
    else:
        print(f"RESULT: all {CHECKS[0]} checks passed")
    print("=" * 72)

    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
