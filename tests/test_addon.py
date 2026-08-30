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
from mathutils import Matrix, Vector

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
    # Viewpoints can land on fractional frames, which frame_set only reaches
    # through its subframe argument.
    whole = int(frame // 1)
    bpy.context.scene.frame_set(whole, subframe=float(frame) - whole)
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


def build_box_scene():
    """A product with a six sided shell around a board, for enclosure tests."""
    scene, collection, parts = build_scene()
    # Six shell panels around the existing stack.
    panels = {
        "Shell_Top": ((0.130, 0.090, 0.004), (0.0, 0.0, 0.030)),
        "Shell_Bottom": ((0.130, 0.090, 0.004), (0.0, 0.0, -0.030)),
        "Shell_Front": ((0.130, 0.004, 0.060), (0.0, -0.045, 0.0)),
        "Shell_Back": ((0.130, 0.004, 0.060), (0.0, 0.045, 0.0)),
        "Shell_Right": ((0.004, 0.090, 0.060), (0.065, 0.0, 0.0)),
        "Shell_Left": ((0.004, 0.090, 0.060), (-0.065, 0.0, 0.0)),
    }
    for name, (size, location) in panels.items():
        parts[name] = add_box(name, size, location, collection)
    return scene, collection, parts


def key_frames(obj, path='location'):
    from exploded_assembly_studio import core
    curves = core.iter_fcurves(obj, (path,))
    return sorted({round(kp.co.x, 3) for curve in curves for kp in curve.keyframe_points})


def test_camera_delay():
    print("\n[8] Camera hold at the start and end")
    from exploded_assembly_studio import camera as camera_module

    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.direction = 'CENTER'
    props.distance = 0.05
    props.frame_start = 1
    props.frame_end = 60

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()

    props.use_camera = True
    props.camera_mode = 'ORBIT'
    props.camera_delay_start = 10
    props.camera_delay_end = 5

    start, end = camera_module.camera_frame_range(props)
    check(close(start, 11.0) and close(end, 55.0), f"camera range shrinks to {start:.0f}-{end:.0f}")

    bpy.ops.eas.animate(mode='ASSEMBLE')
    pivot = props.camera_pivot
    frames = key_frames(pivot, 'rotation_euler')
    check(frames and close(frames[0], 11.0), f"first camera key is held to frame 11 ({frames})")
    check(frames and close(frames[-1], 55.0), f"last camera key lands on frame 55 ({frames})")

    # The camera must genuinely sit still through the hold.
    cam = props.camera_object
    at_1 = at_frame(1, [cam])[cam.name].translation.copy()
    at_11 = at_frame(11, [cam])[cam.name].translation.copy()
    at_55 = at_frame(55, [cam])[cam.name].translation.copy()
    at_60 = at_frame(60, [cam])[cam.name].translation.copy()
    check((at_1 - at_11).length < 1e-6, "camera is still through the opening hold")
    check((at_55 - at_60).length < 1e-6, "camera is still through the closing hold")
    check((at_11 - at_55).length > 1e-4, "camera still moves in between")

    # The parts keep the full range; only the camera is held.
    part_frames = key_frames(parts['top_case'])
    check(close(part_frames[0], 1.0), f"parts still start on frame 1 ({part_frames})")

    # A silly delay must not produce an inverted range.
    props.camera_delay_start = 100
    props.camera_delay_end = 100
    start, end = camera_module.camera_frame_range(props)
    check(end > start, f"absurd delays still give a valid range ({start:.0f}-{end:.0f})")
    props.camera_delay_start = 0
    props.camera_delay_end = 0


def test_camera_multipoint():
    print("\n[9] Multiple camera viewpoints, arcs and roll")
    import math as _math
    from exploded_assembly_studio import camera as camera_module
    from exploded_assembly_studio import core

    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.direction = 'CENTER'
    props.distance = 0.05
    props.frame_start = 1
    props.frame_end = 101

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()

    props.use_camera = True
    props.camera_mode = 'POSES'
    props.camera_poses.clear()

    center = Vector((0.0, 0.0, 0.0))

    def look_at(eye):
        direction = Vector(eye) - center
        rotation = direction.to_track_quat('Z', 'Y')
        m = rotation.to_matrix().to_4x4()
        m.translation = Vector(eye)
        return m

    # Four viewpoints on a circle of radius 0.5 around the product.
    eyes = [
        (0.0, -0.5, 0.15),
        (0.5, 0.0, 0.15),
        (0.0, 0.5, 0.15),
        (-0.5, 0.0, 0.15),
    ]
    for eye in eyes:
        pose = props.camera_poses.add()
        pose.matrix = core.matrix_to_flat(look_at(eye))
        pose.lens = 50.0
        pose.motion = 'LINEAR'
        pose.interpolation = 'LINEAR'
    camera_module.respace_poses(props)

    check(len(props.camera_poses) == 4, "four viewpoints stored")
    positions = [round(p.position, 3) for p in props.camera_poses]
    check(positions == [0.0, 0.333, 0.667, 1.0], f"spaced evenly {positions}")
    check(camera_module.poses_ready(props), "four viewpoints count as ready")

    bpy.ops.eas.animate(mode='ASSEMBLE')
    cam = props.camera_object
    frames = key_frames(cam)
    check(len(frames) == 4, f"one key per viewpoint ({frames})")
    check(close(frames[0], 1.0) and close(frames[-1], 101.0), f"path spans the range ({frames})")

    # Sample at the exact key frames, not the rounded ones a listing gives:
    # a third of a thousandth of a frame is enough drift to blur the check.
    cam_start, cam_end = camera_module.camera_frame_range(props)
    exact_frames = [cam_start + p.position * (cam_end - cam_start) for p in props.camera_poses]

    # Each viewpoint must be reproduced at its own frame.
    worst = 0.0
    for pose, frame in zip(props.camera_poses, exact_frames):
        actual = at_frame(frame, [cam])[cam.name]
        expected = core.flat_to_matrix(pose.matrix)
        worst = max(worst, max(abs(x - y) for ra, rb in zip(actual, expected) for x, y in zip(ra, rb)))
    check(worst < 1e-5, f"every viewpoint is hit exactly (err {worst:.2e})")

    # ---- arc ------------------------------------------------------------
    mid_frame = (exact_frames[0] + exact_frames[1]) * 0.5
    linear_mid = at_frame(mid_frame, [cam])[cam.name].translation.copy()
    linear_radius = (linear_mid - center).length

    props.camera_poses[0].motion = 'ARC'
    bpy.ops.eas.animate(mode='ASSEMBLE')
    arc_frames = key_frames(cam)
    check(len(arc_frames) > 4, f"arc bakes intermediate keys ({len(arc_frames)} keys)")

    arc_mid = at_frame(mid_frame, [cam])[cam.name].translation.copy()
    arc_radius = (arc_mid - center).length
    # The eyes sit at z=0.15 on a 0.5 ring, so the real orbit radius is 0.522.
    capture_radius = (Vector(eyes[0]) - center).length
    check(
        arc_radius > linear_radius + 1e-3,
        f"arc bulges out to the orbit radius ({arc_radius:.4f} vs chord {linear_radius:.4f})",
    )
    check(
        close(arc_radius, capture_radius, 0.01),
        f"arc keeps the capture radius ({arc_radius:.4f} vs {capture_radius:.4f})",
    )

    # The arc must still land exactly on both of its endpoints.
    ends_err = 0.0
    for index in (0, 1):
        actual = at_frame(exact_frames[index], [cam])[cam.name]
        expected = core.flat_to_matrix(props.camera_poses[index].matrix)
        ends_err = max(ends_err, max(abs(x - y) for ra, rb in zip(actual, expected)
                                     for x, y in zip(ra, rb)))
    check(ends_err < 1e-5, f"arc endpoints still exact (err {ends_err:.2e})")
    props.camera_poses[0].motion = 'LINEAR'

    # ---- roll -----------------------------------------------------------
    props.camera_poses[1].roll = _math.radians(30.0)
    bpy.ops.eas.animate(mode='ASSEMBLE')
    actual = at_frame(exact_frames[1], [cam])[cam.name]
    expected = core.flat_to_matrix(props.camera_poses[1].matrix) @ Matrix.Rotation(
        _math.radians(30.0), 4, 'Z'
    )
    err = max(abs(x - y) for ra, rb in zip(actual, expected) for x, y in zip(ra, rb))
    check(err < 1e-5, f"roll tilts the camera around its view axis (err {err:.2e})")
    props.camera_poses[1].roll = 0.0

    # ---- per viewpoint timing -------------------------------------------
    # Moving a viewpoint late in time also moves it later in the path, since
    # the camera plays the viewpoints in time order rather than list order.
    props.camera_poses[1].position = 0.8
    bpy.ops.eas.animate(mode='ASSEMBLE')
    moved = key_frames(cam)
    check(any(close(f, 81.0, 0.6) for f in moved), f"viewpoint time moves its key ({moved})")
    check(moved == sorted(moved), "the path stays in time order")
    camera_module.respace_poses(props)

    # ---- reverse keeps the path in order ---------------------------------
    props.camera_mirror_on_assemble = True
    bpy.ops.eas.animate(mode='ASSEMBLE')
    first = at_frame(1, [cam])[cam.name]
    last_pose = core.flat_to_matrix(props.camera_poses[-1].matrix)
    err = max(abs(x - y) for ra, rb in zip(first, last_pose) for x, y in zip(ra, rb))
    check(err < 1e-5, "mirrored path starts on the last viewpoint")
    props.camera_mirror_on_assemble = False

    # ---- one viewpoint is not a move -------------------------------------
    while len(props.camera_poses) > 1:
        props.camera_poses.remove(1)
    check(not camera_module.poses_ready(props), "a single viewpoint is not enough")
    result = bpy.ops.eas.animate(mode='ASSEMBLE')
    check(result == {'FINISHED'}, "explode still succeeds with one viewpoint")


def test_enclosure_phase():
    print("\n[10] Enclosure panels and the two phase build")
    from exploded_assembly_studio import core

    scene, collection, parts = build_box_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False
    props.direction = 'AXIS_SPLIT'
    props.axis = 'Z'
    props.magnitude = 'LAYERED'
    props.center_mode = 'ACTIVE'
    props.distance = 0.03
    props.frame_start = 1
    props.frame_end = 100
    props.use_sequence = True
    props.overlap = 0.8

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    shells = [obj for name, obj in parts.items() if name.startswith("Shell_")]
    select(shells, active=shells[0])
    result = bpy.ops.eas.mark_role(role='ENCLOSURE')
    check(result == {'FINISHED'}, "panels marked as enclosure")
    check(props.use_phases, "marking enclosure turns the phase split on")

    select(objects, active=parts['pcb'])
    result = bpy.ops.eas.detect_sides()
    check(result == {'FINISHED'}, "sides detected")

    expected_sides = {
        "Shell_Top": 'TOP', "Shell_Bottom": 'BOTTOM', "Shell_Front": 'FRONT',
        "Shell_Back": 'BACK', "Shell_Right": 'RIGHT', "Shell_Left": 'LEFT',
    }
    wrong = [f"{n}={parts[n].eas.side}" for n, s in expected_sides.items() if parts[n].eas.side != s]
    check(not wrong, f"every panel found its own side ({wrong})")

    # Each panel must travel along its own side and nowhere else.
    bpy.ops.eas.animate(mode='EXPLODE')
    exploded = at_frame(props.frame_end, objects)
    axis_of = {
        "Shell_Top": (2, 1), "Shell_Bottom": (2, -1), "Shell_Front": (1, -1),
        "Shell_Back": (1, 1), "Shell_Right": (0, 1), "Shell_Left": (0, -1),
    }
    bad = []
    for name, (index, sign) in axis_of.items():
        delta = exploded[name].translation - assembled[name].translation
        along = delta[index] * sign
        sideways = max(abs(delta[i]) for i in range(3) if i != index)
        if along < 1e-4 or sideways > 1e-6:
            bad.append(f"{name} {tuple(round(v, 4) for v in delta)}")
    check(not bad, f"panels open straight out along their own side ({bad})")

    # Shell distance factor.
    props.enclosure_distance_factor = 3.0
    bpy.ops.eas.animate(mode='EXPLODE')
    far = at_frame(props.frame_end, objects)
    travel = (far["Shell_Top"].translation - assembled["Shell_Top"].translation).length
    check(close(travel, props.distance * 3.0, 1e-5), f"shell distance factor applied ({travel:.4f})")
    props.enclosure_distance_factor = 1.5

    # Manual override: bring the front panel down from above instead.
    parts["Shell_Front"].eas.side = 'TOP'
    bpy.ops.eas.animate(mode='EXPLODE')
    overridden = at_frame(props.frame_end, objects)
    delta = overridden["Shell_Front"].translation - assembled["Shell_Front"].translation
    check(delta.z > 1e-4 and abs(delta.y) < 1e-6, f"manual side override respected ({tuple(round(v,4) for v in delta)})")
    parts["Shell_Front"].eas.side = 'AUTO'

    # ---- phase timing ----------------------------------------------------
    props.parts_share = 0.6
    props.phase_gap_frames = 10
    bpy.ops.eas.animate(mode='ASSEMBLE')

    part_objects = [o for o in objects if o.eas.role == 'PART']
    shell_objects = [o for o in objects if o.eas.role == 'ENCLOSURE']
    last_part = max(key_frames(o)[-1] for o in part_objects if key_frames(o))
    first_shell = min(key_frames(o)[0] for o in shell_objects if key_frames(o))
    check(
        first_shell >= last_part - 1e-6,
        f"on assemble the shell only starts after the parts land ({last_part:.1f} -> {first_shell:.1f})",
    )
    check(
        first_shell - last_part > 5.0,
        f"the phase gap leaves a real pause ({first_shell - last_part:.1f} frames)",
    )

    # Explode runs it the other way: the shell opens first.
    bpy.ops.eas.animate(mode='EXPLODE')
    last_shell = max(key_frames(o)[-1] for o in shell_objects if key_frames(o))
    first_part = min(key_frames(o)[0] for o in part_objects if key_frames(o))
    check(
        first_part >= last_shell - 1e-6,
        f"on explode the shell opens before the parts leave ({last_shell:.1f} -> {first_part:.1f})",
    )

    # And the round trip still lands exactly home.
    bpy.ops.eas.animate(mode='ASSEMBLE')
    home = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"enclosure build returns every part home (error {worst:.3e})")

    # Turning the feature off drops the side based direction. The front panel
    # straddles the split plane, so under plain Axis +/- it stops moving at all
    # instead of opening forwards.
    bpy.ops.eas.animate(mode='EXPLODE')
    with_phase = at_frame(props.frame_end, objects)
    forward = with_phase["Shell_Front"].translation.y - assembled["Shell_Front"].translation.y
    check(forward < -1e-4, f"with the phase on, the front panel opens forwards ({forward:+.4f})")

    props.use_phases = False
    bpy.ops.eas.animate(mode='EXPLODE')
    plain = at_frame(props.frame_end, objects)
    delta = plain["Shell_Front"].translation - assembled["Shell_Front"].translation
    check(abs(delta.y) < 1e-6, f"with the phase off, the side direction is gone ({delta.y:+.4f})")
    top_delta = plain["Shell_Top"].translation - assembled["Shell_Top"].translation
    check(top_delta.z > 1e-4, "and the global direction drives the panels again")


def test_enclosure_camera_rules():
    print("\n[11] Enclosure kept out of frame and out of the camera's path")
    from exploded_assembly_studio import camera as camera_module
    from exploded_assembly_studio import core

    scene, collection, parts = build_box_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.direction = 'AXIS_SPLIT'
    props.center_mode = 'ACTIVE'
    props.distance = 0.02
    props.frame_start = 1
    props.frame_end = 120
    props.use_sequence = True

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    shells = [obj for name, obj in parts.items() if name.startswith("Shell_")]
    select(shells, active=shells[0])
    bpy.ops.eas.mark_role(role='ENCLOSURE')
    select(objects, active=parts['pcb'])
    bpy.ops.eas.detect_sides()

    # A camera dead in front of the product, looking at it from -Y.
    props.use_camera = True
    props.camera_mode = 'POSES'
    props.camera_poses.clear()
    eye = Vector((0.0, -0.6, 0.05))
    pose_matrix = (eye - Vector((0, 0, 0))).to_track_quat('Z', 'Y').to_matrix().to_4x4()
    pose_matrix.translation = eye
    for _ in range(2):
        pose = props.camera_poses.add()
        pose.matrix = core.matrix_to_flat(pose_matrix)
        pose.lens = 50.0
    camera_module.respace_poses(props)

    props.enclosure_offscreen = True
    props.enclosure_avoid_camera = True
    props.enclosure_camera_margin = 1.15
    props.phase_gap_frames = 12

    bpy.ops.eas.animate(mode='ASSEMBLE')

    # ---- the front panel must not come in past the lens -------------------
    front_side = None
    center = Vector((0.0, 0.0, 0.0))
    parts_list, _ = core.build_parts(bpy.context)
    center = core.assembly_center(bpy.context, parts_list)
    core.compute_explosion(bpy.context, parts_list)
    info = camera_module.camera_info(bpy.context, center, 0.1)
    check(info is not None, "camera info built from the captured viewpoints")
    changes = core.apply_enclosure_camera_rules(
        bpy.context, parts_list, center, info, camera_module
    )
    sides = {obj.name: side for obj, side, _ in changes}
    front_side = sides.get("Shell_Front")
    check(
        front_side is not None and front_side != 'FRONT',
        f"the front panel no longer enters from the camera's side (now {front_side})",
    )
    # The back panel cannot keep its own side either, for the opposite reason:
    # travelling straight away from the camera it only ever gets smaller, so it
    # never actually leaves the frame. The two rules together rule out both
    # axes that face the lens and leave a sideways entry.
    back_centre = Vector((0.0, 0.045, 0.0))
    straight_away = camera_module.offscreen_distance(
        info, back_centre, 0.035, Vector((0.0, 1.0, 0.0)), 1.15
    )
    check(straight_away is None, "moving straight away from the camera never clears the frame")
    check(
        sides.get("Shell_Back") not in (None, 'BACK', 'FRONT'),
        f"so the back panel enters sideways instead ({sides.get('Shell_Back')})",
    )
    sideways = camera_module.offscreen_distance(
        info, back_centre, 0.035, Vector((0.0, 0.0, 1.0)), 1.15
    )
    check(sideways is not None and sideways > 0.0, f"a sideways side does clear it ({sideways:.3f})")

    # ---- every panel must start completely outside the frame --------------
    fov_x, fov_y = info.fov_x, info.fov_y
    planes = camera_module._frustum_planes(fov_x, fov_y)
    inverse = pose_matrix.inverted()

    def outside_frame(part):
        """True when the part's bounding sphere clears every frustum plane."""
        world = part.parent @ part.basis_exploded
        centre = core.object_center(part.obj, world, True)
        radius = core.part_radius(part, world)
        local = inverse @ centre
        return any(normal.dot(local) < -radius for normal in planes)

    hidden = []
    for part in parts_list:
        if part.obj.eas.role != 'ENCLOSURE':
            continue
        if not outside_frame(part):
            hidden.append(part.obj.name)
    check(not hidden, f"every parked panel is fully out of frame ({hidden})")

    # A part, by contrast, is meant to stay in shot.
    board = next(p for p in parts_list if p.obj.name == "PCB")
    check(not outside_frame(board), "the board itself stays in frame")

    # ---- the shell still never starts before the parts land ---------------
    bpy.ops.eas.animate(mode='ASSEMBLE')
    part_objects = [o for o in objects if o.eas.role == 'PART']
    shell_objects = [o for o in objects if o.eas.role == 'ENCLOSURE']
    last_part = max(key_frames(o)[-1] for o in part_objects if key_frames(o))
    first_shell = min(key_frames(o)[0] for o in shell_objects if key_frames(o))
    check(first_shell >= last_part - 1e-6,
          f"shell starts only after the last part lands ({last_part:.1f} -> {first_shell:.1f})")
    check(close(first_shell - last_part, 12.0, 0.6),
          f"the delay is exactly the {props.phase_gap_frames} frames asked for "
          f"({first_shell - last_part:.1f})")

    # Changing the delay must move the shell, not squeeze the parts.
    props.phase_gap_frames = 30
    bpy.ops.eas.animate(mode='ASSEMBLE')
    last_part_2 = max(key_frames(o)[-1] for o in part_objects if key_frames(o))
    first_shell_2 = min(key_frames(o)[0] for o in shell_objects if key_frames(o))
    check(close(first_shell_2 - last_part_2, 30.0, 0.6),
          f"a longer delay is honoured ({first_shell_2 - last_part_2:.1f} frames)")

    # ---- and it all still returns home ------------------------------------
    home = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"off camera shells still land home (error {worst:.3e})")

    # ---- turning the rules off restores the plain sides -------------------
    props.enclosure_offscreen = False
    props.enclosure_avoid_camera = False
    parts_list, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts_list)
    front = next(p for p in parts_list if p.obj.name == "Shell_Front")
    check(front.offset.y < -1e-4,
          f"with the rules off the front panel opens forwards again ({front.offset.y:+.4f})")


def test_rebuild():
    print("\n[12] Rebuild after changing a setting")
    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False
    props.direction = 'CENTER'
    props.magnitude = 'UNIFORM'
    props.distance = 0.05
    props.frame_start = 1
    props.frame_end = 60

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    check(props.last_build_mode == 'NONE', "nothing built yet")
    try:
        bpy.ops.eas.rebuild()
        refused = False
    except RuntimeError:
        refused = True
    check(refused, "rebuild refuses before anything has been built")

    bpy.ops.eas.animate(mode='ASSEMBLE')
    check(props.last_build_mode == 'ASSEMBLE', "the assemble build is remembered")

    def travel():
        end = at_frame(props.frame_start, objects)   # assemble starts exploded
        return (end['Top_Case'].translation - assembled['Top_Case'].translation).length

    before = travel()
    check(close(before, 0.05, 1e-4), f"first build used distance 0.05 ({before:.4f})")

    # Change a setting, then rebuild: the new value must take effect, and the
    # animation must stay an assemble rather than flipping to an explode.
    props.distance = 0.12
    result = bpy.ops.eas.rebuild()
    check(result == {'FINISHED'}, "rebuild ran")
    after = travel()
    check(close(after, 0.12, 1e-4), f"rebuild picked up the new distance ({after:.4f})")

    start_state = at_frame(props.frame_start, objects)
    end_state = at_frame(props.frame_end, objects)
    check(
        start_state['Top_Case'].translation.z > end_state['Top_Case'].translation.z,
        "rebuild still built an assemble, not an explode",
    )
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], end_state[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"rebuilt assemble still lands home ({worst:.3e})")

    # Rebuilding from anywhere in the timeline must give the same result: the
    # parts are measured from the saved state, not from where they sit now.
    for frame in (1, 23, 47, 60):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        bpy.ops.eas.rebuild()
        end_state = at_frame(props.frame_end, objects)
        worst = max(
            max(abs(x - y) for ra, rb in zip(assembled[n], end_state[n]) for x, y in zip(ra, rb))
            for n in assembled
        )
        if worst > TOLERANCE:
            break
    check(worst <= TOLERANCE, f"rebuilding from any frame is safe (worst {worst:.3e})")

    # Repeated rebuilds must not pile up keyframes.
    counts = []
    for _ in range(3):
        bpy.ops.eas.rebuild()
        counts.append(len(key_frames(parts['top_case'])))
    check(len(set(counts)) == 1 and counts[0] == 2,
          f"repeated rebuilds keep exactly two keys per part ({counts})")

    # Switching mode updates what rebuild will do.
    bpy.ops.eas.animate(mode='EXPLODE')
    check(props.last_build_mode == 'EXPLODE', "building an explode updates the memory")
    bpy.ops.eas.rebuild()
    start_state = at_frame(props.frame_start, objects)
    check(
        matrices_equal(start_state['Top_Case'], assembled['Top_Case']),
        "rebuild now repeats the explode instead",
    )

    # Clearing forgets it again.
    bpy.ops.eas.clear_animation()
    check(props.last_build_mode == 'NONE', "clearing the animation forgets the last build")


def test_snapshots():
    print("\n[13] Snapshots as restore points")
    from exploded_assembly_studio import core, snapshots

    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False
    props.direction = 'CENTER'
    props.magnitude = 'UNIFORM'
    props.distance = 0.05
    props.frame_start = 1
    props.frame_end = 60

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()

    # Set up a distinctive state worth coming back to.
    parts['top_case'].eas.role = 'ENCLOSURE'
    parts['top_case'].eas.side = 'TOP'
    shell = bpy.data.collections.new("SNAP_SHELL")
    scene.collection.children.link(shell)
    shell.objects.link(parts['top_case'])
    props.enclosure_collection = shell
    # Deliberately off, with a collection set: assigning the pointer switches
    # this on, so the restore has to put the pointers back before the values it
    # saved, or the snapshot comes back with a setting it never held.
    props.use_phases = False
    parts['connector'].eas.distance_multiplier = 2.5
    parts['pcb'].eas.exclude = True
    props.camera_mode = 'POSES'
    props.camera_poses.clear()
    for index in range(3):
        pose = props.camera_poses.add()
        pose.matrix = core.matrix_to_flat(Matrix.Translation((0.1 * index, -0.5, 0.2)))
        pose.lens = 35.0 + index * 10.0
        pose.motion = 'ARC' if index == 0 else 'LINEAR'
    props.camera_delay_start = 14
    props.phase_gap_frames = 17
    bpy.ops.eas.animate(mode='ASSEMBLE')

    before = world_matrices(objects)

    result = bpy.ops.eas.snapshot_add(name="Good State")
    check(result == {'FINISHED'}, "snapshot taken")
    check(len(props.snapshots) == 1, "one snapshot stored")
    check(props.snapshots[0].name == "Good State", "snapshot kept its name")
    check("object" in props.snapshots[0].note, f"snapshot summarised ({props.snapshots[0].note})")

    payload = snapshots.from_json(props.snapshots[0].data)
    check(payload is not None, "snapshot payload is valid JSON")
    check(len(payload['objects']) >= len(objects), "every part is in the payload")
    check(len(payload['camera_poses']) == 3, "camera viewpoints are in the payload")

    # ---- now wreck everything ---------------------------------------------
    props.distance = 0.99
    props.direction = 'WORLD_AXIS'
    props.magnitude = 'LAYERED'
    props.frame_end = 250
    props.camera_delay_start = 0
    props.phase_gap_frames = 0
    props.camera_poses.clear()
    props.enclosure_collection = None
    props.use_phases = True
    parts['top_case'].eas.role = 'PART'
    parts['top_case'].eas.side = 'AUTO'
    parts['connector'].eas.distance_multiplier = 1.0
    parts['pcb'].eas.exclude = False
    for obj in objects:
        obj.location = (5.0, 5.0, 5.0)
    bpy.context.view_layer.update()

    # ---- and go back ------------------------------------------------------
    result = bpy.ops.eas.snapshot_restore()
    check(result == {'FINISHED'}, "restore ran")

    check(close(props.distance, 0.05, 1e-6), f"scene setting came back ({props.distance})")
    check(props.direction == 'CENTER', "enum setting came back")
    check(props.magnitude == 'UNIFORM', "spacing setting came back")
    check(props.frame_end == 60, f"frame range came back ({props.frame_end})")
    check(props.camera_delay_start == 14, "camera hold came back")
    check(props.phase_gap_frames == 17, "phase delay came back")
    check(props.collection == collection, "pointer setting came back")
    # Collections were once looked up in bpy.data.objects, so a restore quietly
    # cleared this one and the enclosure stopped being an enclosure.
    check(props.enclosure_collection == shell,
          f"the enclosure collection came back ({props.enclosure_collection})")
    check(not props.use_phases,
          "and a pointer's side effect did not overwrite what the snapshot held")

    # And the guard against it coming back: a pointer added later must resolve
    # on its own, without anyone remembering to extend a list.
    unresolved = [
        prop.identifier
        for prop in props.bl_rna.properties
        if prop.type == 'POINTER'
        and not prop.is_readonly
        and prop.identifier not in snapshots.SKIPPED_SETTINGS
        and snapshots.pointer_source(props, prop.identifier) is None
    ]
    check(not unresolved, f"every pointer setting knows where it lives ({unresolved})")

    check(parts['top_case'].eas.role == 'ENCLOSURE', "per object role came back")
    check(parts['top_case'].eas.side == 'TOP', "per object side came back")
    check(close(parts['connector'].eas.distance_multiplier, 2.5, 1e-6),
          "per object multiplier came back")
    check(parts['pcb'].eas.exclude, "per object exclusion came back")

    check(len(props.camera_poses) == 3, "camera viewpoints came back")
    lenses = [round(p.lens, 1) for p in props.camera_poses]
    check(lenses == [35.0, 45.0, 55.0], f"viewpoint focal lengths came back ({lenses})")
    check(props.camera_poses[0].motion == 'ARC', "viewpoint motion came back")

    after = world_matrices(objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(before[n], after[n]) for x, y in zip(ra, rb))
        for n in before
    )
    check(worst <= TOLERANCE, f"the parts are back where they were (error {worst:.3e})")

    check(
        all(not obj.animation_data or not obj.animation_data.action for obj in objects),
        "generated animation was cleared by the restore",
    )
    check(props.last_build_mode == 'ASSEMBLE', "restore remembers what had been built")

    # With settings restored, Rebuild reproduces the animation.
    result = bpy.ops.eas.rebuild()
    check(result == {'FINISHED'}, "rebuild after restore works")
    # `before` was taken at frame 1 of an assemble, so it is the exploded pose;
    # that is the frame to compare the rebuilt animation against.
    start_state = at_frame(props.frame_start, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(before[n], start_state[n]) for x, y in zip(ra, rb))
        for n in before
    )
    check(worst <= TOLERANCE, f"and reproduces the same animation ({worst:.3e})")

    # ---- several snapshots, and update -------------------------------------
    props.distance = 0.2
    bpy.ops.eas.snapshot_add(name="Wide")
    check(len(props.snapshots) == 2, "a second snapshot is stored separately")
    props.distance = 0.05
    bpy.ops.eas.snapshot_restore(index=1)
    check(close(props.distance, 0.2, 1e-6), "restoring by index picks the right one")

    props.distance = 0.33
    bpy.ops.eas.snapshot_update()
    props.distance = 0.01
    bpy.ops.eas.snapshot_restore(index=1)
    check(close(props.distance, 0.33, 1e-6), "update overwrites the selected snapshot")

    bpy.ops.eas.snapshot_restore(index=0)
    check(close(props.distance, 0.05, 1e-6), "the first snapshot is untouched by the update")

    # ---- a deleted object must not break the restore -----------------------
    doomed = parts['Screw_1']
    name = doomed.name
    bpy.data.objects.remove(doomed, do_unlink=True)
    result = bpy.ops.eas.snapshot_restore(index=0)
    check(result == {'FINISHED'}, f"restore survives {name} having been deleted")

    bpy.ops.eas.snapshot_remove()
    check(len(props.snapshots) == 1, "snapshot removed")


def test_parts_offscreen():
    print("\n[14] Parts waiting out of frame, and the ring problem")
    from exploded_assembly_studio import camera as camera_module
    from exploded_assembly_studio import core

    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.distance = 0.04
    props.frame_start = 1
    props.frame_end = 100

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    # A camera looking at the board from the front, slightly above.
    props.use_camera = True
    props.camera_mode = 'POSES'
    props.camera_poses.clear()
    eye = Vector((0.0, -0.45, 0.12))
    pose_matrix = eye.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    pose_matrix.translation = eye
    for _ in range(2):
        pose = props.camera_poses.add()
        pose.matrix = core.matrix_to_flat(pose_matrix)
        pose.lens = 50.0
    camera_module.respace_poses(props)

    # ---- the reported symptom: From Center lays parts out in a ring --------
    props.direction = 'CENTER'
    props.magnitude = 'UNIFORM'
    props.parts_offscreen = False
    bpy.ops.eas.animate(mode='ASSEMBLE')
    ring = at_frame(props.frame_start, objects)

    heights = [
        ring[f'Component_{i}'].translation.z - assembled[f'Component_{i}'].translation.z
        for i in range(1, 5)
    ]
    spread = [
        Vector((ring[f'Component_{i}'].translation - assembled[f'Component_{i}'].translation).xy).length
        for i in range(1, 5)
    ]
    check(
        max(abs(h) for h in heights) < max(spread),
        "From Center moves parts sideways more than up - the ring the user saw",
    )

    # ---- straight up instead ---------------------------------------------
    props.direction = 'WORLD_AXIS'
    props.axis = 'Z'
    bpy.ops.eas.animate(mode='ASSEMBLE')
    up = at_frame(props.frame_start, objects)
    sideways = max(
        Vector((up[o.name].translation - assembled[o.name].translation).xy).length
        for o in objects
    )
    check(sideways < 1e-6, f"World Axis Z lifts parts straight up, no ring ({sideways:.2e})")

    # ---- but are they out of shot? ---------------------------------------
    info = camera_module.camera_info(bpy.context, Vector((0, 0, 0)), 0.1)
    planes = camera_module._frustum_planes(info.fov_x, info.fov_y)
    inverse = pose_matrix.inverted()

    def visible(matrix, obj):
        corners = [matrix @ Vector(c) for c in obj.bound_box]
        centre = sum(corners, Vector()) / len(corners)
        radius = max((c - centre).length for c in corners)
        local = inverse @ centre
        return not any(normal.dot(local) < -radius for normal in planes)

    seen = [o.name for o in objects if o.eas.role == 'PART' and visible(up[o.name], o)]
    check(bool(seen), f"at 0.04 they are still in shot, as reported ({len(seen)} visible)")

    # ---- turn the new option on -------------------------------------------
    props.parts_offscreen = True
    bpy.ops.eas.animate(mode='ASSEMBLE')
    hidden_state = at_frame(props.frame_start, objects)

    excluded = {parts['pcb'].name}
    seen = [
        o.name for o in objects
        if o.name not in excluded and visible(hidden_state[o.name], o)
    ]
    check(not seen, f"with Start Off Camera every part waits out of frame ({seen})")

    lifted = min(
        hidden_state[o.name].translation.z - assembled[o.name].translation.z
        for o in objects if o.name not in excluded
    )
    check(lifted > props.distance, f"they were pushed well past the set distance ({lifted:.3f})")

    # They must still land exactly home.
    home = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"and still land home exactly ({worst:.3e})")

    # ---- preview must agree with the animation ----------------------------
    bpy.ops.eas.clear_animation()
    bpy.ops.eas.preview(state='EXPLODED')
    preview = world_matrices(objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(hidden_state[n], preview[n]) for x, y in zip(ra, rb))
        for n in hidden_state
    )
    check(worst <= TOLERANCE, f"Preview Exploded matches the animation's first frame ({worst:.3e})")

    bpy.ops.eas.preview(state='ASSEMBLED')
    restored = world_matrices(objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], restored[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"Preview Assembled puts the product back ({worst:.3e})")

    # ---- the preset should do all of this in one click --------------------
    select(objects, active=parts['pcb'])
    result = bpy.ops.eas.apply_preset(preset='DROP_IN')
    check(result == {'FINISHED'}, "Drop In preset applied")
    check(props.direction == 'WORLD_AXIS' and props.axis == 'Z',
          "preset explodes straight up rather than radially")
    check(props.parts_offscreen, "preset starts the parts off camera")
    check(props.camera_delay_start > 0, "preset holds the camera at the start")

    bpy.ops.eas.animate(mode='ASSEMBLE')
    preset_state = at_frame(props.frame_start, objects)
    seen = [
        o.name for o in objects
        if o.name not in excluded and visible(preset_state[o.name], o)
    ]
    check(not seen, f"the preset alone gives an empty opening frame ({seen})")

    props.parts_offscreen = False


def test_pre_post_roll():
    print("\n[15] Camera keeps moving before and after the parts")
    from exploded_assembly_studio import camera as camera_module
    from exploded_assembly_studio import core

    scene, collection, parts = build_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.direction = 'WORLD_AXIS'
    props.axis = 'Z'
    props.distance = 0.05
    props.frame_start = 1
    props.frame_end = 120
    props.use_sequence = False

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    # An orbiting camera so there is a move to observe either side.
    props.use_camera = True
    props.camera_mode = 'ORBIT'
    props.camera_orbit = 3.14159
    props.camera_delay_start = 0
    props.camera_delay_end = 0

    # ---- without any roll, everything spans the shot -----------------------
    props.component_custom_range = False
    start, end = core.parts_frame_range(props)
    check(close(start, 1.0) and close(end, 120.0), f"parts span the whole shot ({start}-{end})")

    # ---- carve a window out of the shot ------------------------------------
    props.component_custom_range = True
    seeded = (props.component_frame_start, props.component_frame_end)
    check(seeded == (1, 120), f"turning it on seeds from the shot {seeded}")
    props.component_frame_start = 31
    props.component_frame_end = 100
    start, end = core.parts_frame_range(props)
    check(close(start, 31.0) and close(end, 100.0), f"parts now move 31-100 ({start}-{end})")

    cam_start, cam_end = camera_module.camera_frame_range(props)
    check(close(cam_start, 1.0) and close(cam_end, 120.0),
          f"the camera still spans the whole shot ({cam_start}-{cam_end})")

    bpy.ops.eas.animate(mode='ASSEMBLE')
    check(scene.frame_start == 1 and scene.frame_end == 120, "scene range covers the whole shot")

    frames = key_frames(parts['top_case'])
    check(close(frames[0], 31.0, 0.6) and close(frames[-1], 100.0, 0.6),
          f"part keys land inside the action window ({frames})")

    # The parts must be genuinely still during both rolls.
    early_a = at_frame(1, objects)
    early_b = at_frame(30, objects)
    late_a = at_frame(100, objects)
    late_b = at_frame(120, objects)
    still_start = max(
        (early_a[o.name].translation - early_b[o.name].translation).length for o in objects
    )
    still_end = max(
        (late_a[o.name].translation - late_b[o.name].translation).length for o in objects
    )
    check(still_start < 1e-9, f"parts hold through the pre roll ({still_start:.2e})")
    check(still_end < 1e-9, f"parts hold through the post roll ({still_end:.2e})")

    # ...and the camera must be moving through exactly those windows.
    cam = props.camera_object
    cam_1 = at_frame(1, [cam])[cam.name].translation.copy()
    cam_30 = at_frame(30, [cam])[cam.name].translation.copy()
    cam_100 = at_frame(100, [cam])[cam.name].translation.copy()
    cam_120 = at_frame(120, [cam])[cam.name].translation.copy()
    check((cam_1 - cam_30).length > 1e-3,
          f"the camera moves during the pre roll ({(cam_1 - cam_30).length:.3f})")
    check((cam_100 - cam_120).length > 1e-3,
          f"the camera moves during the post roll ({(cam_100 - cam_120).length:.3f})")

    # The product is finished and holding for the whole post roll.
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], late_b[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"the product is complete through the post roll ({worst:.3e})")

    # ---- the two delays are independent ------------------------------------
    props.camera_delay_start = 10
    props.camera_delay_end = 5
    cam_start, cam_end = camera_module.camera_frame_range(props)
    start, end = core.parts_frame_range(props)
    check(close(cam_start, 11.0) and close(cam_end, 115.0),
          f"camera delays still apply on top ({cam_start}-{cam_end})")
    check(close(start, 31.0) and close(end, 100.0),
          "and they do not move the parts window")

    # ---- inverted input must not invert the window -------------------------
    props.component_frame_start = 100
    props.component_frame_end = 40
    start, end = core.parts_frame_range(props)
    check(end > start, f"inverted frames are ordered, not inverted ({start:.0f}-{end:.0f})")

    props.component_custom_range = False
    props.camera_delay_start = 0
    props.camera_delay_end = 0


def test_enclosure_custom_range():
    print("\n[16] Enclosure timed independently of the parts")
    from exploded_assembly_studio import core

    scene, collection, parts = build_box_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False
    props.direction = 'AXIS_SPLIT'
    props.center_mode = 'ACTIVE'
    props.distance = 0.03
    props.frame_start = 1
    props.frame_end = 200
    props.use_sequence = True
    props.overlap = 0.7

    objects = list(collection.all_objects)
    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    shells = [obj for name, obj in parts.items() if name.startswith("Shell_")]
    select(shells, active=shells[0])
    bpy.ops.eas.mark_role(role='ENCLOSURE')
    select(objects, active=parts['pcb'])
    bpy.ops.eas.detect_sides()

    part_objects = [o for o in objects if o.eas.role == 'PART']
    shell_objects = [o for o in objects if o.eas.role == 'ENCLOSURE']

    def windows():
        p = [key_frames(o) for o in part_objects if key_frames(o)]
        s = [key_frames(o) for o in shell_objects if key_frames(o)]
        return (min(f[0] for f in p), max(f[-1] for f in p),
                min(f[0] for f in s), max(f[-1] for f in s))

    # ---- the parts window is driven by pre/post action ---------------------
    props.component_custom_range = True
    props.component_frame_start = 21
    props.component_frame_end = 170
    check(not props.enclosure_custom_range, "custom range is off by default")

    bpy.ops.eas.animate(mode='ASSEMBLE')
    p_start, p_end, s_start, s_end = windows()
    check(close(p_start, 21.0, 0.6), f"parts start after the pre action ({p_start:.0f})")
    check(s_end <= 170.0 + 0.6, f"shell still ends inside the post action limit ({s_end:.0f})")

    # ---- switching on seeds the fields from what was already happening -----
    props.enclosure_custom_range = True
    seeded = (props.enclosure_frame_start, props.enclosure_frame_end)
    check(
        seeded[0] > p_start and seeded[1] <= 170,
        f"turning it on seeds sensible frames from the automatic split {seeded}",
    )

    # ---- now drive the two windows completely independently ---------------
    props.enclosure_frame_start = 150
    props.enclosure_frame_end = 195
    bpy.ops.eas.animate(mode='ASSEMBLE')
    p_start, p_end, s_start, s_end = windows()

    check(close(s_start, 150.0, 0.6), f"shell starts exactly on frame 150 ({s_start:.1f})")
    check(close(s_end, 195.0, 0.6), f"shell ends exactly on frame 195 ({s_end:.1f})")
    check(close(p_start, 21.0, 0.6), f"parts keep their own start ({p_start:.1f})")
    check(close(p_end, 170.0, 0.6), f"parts keep their own end ({p_end:.1f})")
    check(s_end > core.parts_frame_range(props)[1], "the shell can now run past the parts window")

    # Moving one window must not move the other.
    props.enclosure_frame_start = 60
    props.enclosure_frame_end = 90
    bpy.ops.eas.animate(mode='ASSEMBLE')
    p_start2, p_end2, s_start2, s_end2 = windows()
    check(close(s_start2, 60.0, 0.6) and close(s_end2, 90.0, 0.6),
          f"shell follows its new frames ({s_start2:.0f}-{s_end2:.0f})")
    check(close(p_start2, p_start, 0.6) and close(p_end2, p_end, 0.6),
          "and the parts window did not move")

    # An overlapping range is allowed but reported.
    check(s_start2 < p_end2, "this range deliberately overlaps the parts")

    # Inverted input must not produce an inverted window.
    props.enclosure_frame_start = 120
    props.enclosure_frame_end = 80
    low, high = core.enclosure_window(props)
    check(low < high, f"inverted frames are ordered, not inverted ({low:.0f}-{high:.0f})")

    # ---- and the round trip still lands home -------------------------------
    props.enclosure_frame_start = 150
    props.enclosure_frame_end = 195
    bpy.ops.eas.animate(mode='ASSEMBLE')
    home = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"independent windows still land home ({worst:.3e})")

    # Nothing moves before its own window opens.
    early = at_frame(140, objects)
    shell_moved = max(
        (early[o.name].translation - at_frame(1, objects)[o.name].translation).length
        for o in shell_objects
    )
    check(shell_moved < 1e-9, f"the shell is still parked at frame 140 ({shell_moved:.2e})")

    # ---- turning it off restores the automatic split ----------------------
    props.enclosure_custom_range = False
    bpy.ops.eas.animate(mode='ASSEMBLE')
    _, p_end3, s_start3, _ = windows()
    check(s_start3 >= p_end3 - 1e-6,
          f"the automatic split is back, shell after parts ({p_end3:.0f} -> {s_start3:.0f})")

    props.component_custom_range = False


def test_enclosure_collection():
    print("\n[17] Enclosure picked by collection")
    from exploded_assembly_studio import core

    scene, collection, parts = build_box_scene()
    props = scene.eas
    props.source = 'COLLECTION'
    props.collection = collection
    props.use_camera = False
    props.direction = 'AXIS_SPLIT'
    props.center_mode = 'ACTIVE'
    props.distance = 0.03
    props.frame_start = 1
    props.frame_end = 100

    # Move the shell panels into their own sub-collection, the way a real
    # project would already have them grouped.
    shell_collection = bpy.data.collections.new("SHELL")
    collection.children.link(shell_collection)
    shells = [obj for name, obj in parts.items() if name.startswith("Shell_")]
    for obj in shells:
        collection.objects.unlink(obj)
        shell_collection.objects.link(obj)

    objects = list(collection.all_objects)
    check(len(objects) == len(parts), "sub-collection objects are still in the source")

    select(objects, active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)

    # The master switch. Every code path that treats a panel as a shell is
    # gated behind use_phases, so picking a collection while it was off looked
    # like it had worked and the panels animated as ordinary parts.
    props.use_phases = False
    props.enclosure_collection = shell_collection
    check(props.use_phases, "picking the enclosure collection turns the phase on")
    props.enclosure_collection = None
    props.use_phases = False

    # Nothing tagged yet.
    props.use_phases = True
    check(
        not any(core.is_enclosure_member(props, o) for o in objects),
        "no panels before the collection is set",
    )

    props.enclosure_collection = shell_collection
    members = [o.name for o in objects if core.is_enclosure_member(props, o)]
    check(sorted(members) == sorted(o.name for o in shells),
          f"every object in the collection counts as a panel ({len(members)})")
    check(not core.is_enclosure_member(props, parts['pcb']), "the board is not a panel")
    check(
        all(o.eas.role == 'PART' for o in shells),
        "and it did so without touching the per object role",
    )

    # Detect Sides must work off the collection, not just tagged roles.
    select(objects, active=parts['pcb'])
    result = bpy.ops.eas.detect_sides()
    check(result == {'FINISHED'}, "detect sides works from the collection")
    expected = {
        "Shell_Top": 'TOP', "Shell_Bottom": 'BOTTOM', "Shell_Front": 'FRONT',
        "Shell_Back": 'BACK', "Shell_Right": 'RIGHT', "Shell_Left": 'LEFT',
    }
    wrong = [f"{n}={parts[n].eas.side}" for n, s in expected.items() if parts[n].eas.side != s]
    check(not wrong, f"sides detected for collection members ({wrong})")

    # They must animate as a shell: their own side, their own phase.
    props.enclosure_custom_range = True
    props.enclosure_frame_start = 70
    props.enclosure_frame_end = 100
    props.component_custom_range = True
    props.component_frame_start = 1
    props.component_frame_end = 60
    bpy.ops.eas.animate(mode='ASSEMBLE')

    shell_frames = [key_frames(o) for o in shells if key_frames(o)]
    check(shell_frames and min(f[0] for f in shell_frames) >= 69.4,
          f"panels move in the enclosure window ({min(f[0] for f in shell_frames):.0f})")

    exploded = at_frame(props.frame_start, objects)
    delta = exploded["Shell_Left"].translation - assembled["Shell_Left"].translation
    check(delta.x < -1e-4 and abs(delta.z) < 1e-6,
          f"a collection panel opens along its own side ({tuple(round(v, 3) for v in delta)})")

    home = at_frame(props.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], home[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"collection driven shell lands home ({worst:.3e})")

    # A hand tagged object outside the collection still counts.
    parts['connector'].eas.role = 'ENCLOSURE'
    check(core.is_enclosure_member(props, parts['connector']),
          "hand tagged objects still count alongside the collection")
    parts['connector'].eas.role = 'PART'

    # Clearing the collection gives the panels back.
    props.enclosure_collection = None
    check(
        not any(core.is_enclosure_member(props, o) for o in shells),
        "clearing the collection releases the panels",
    )

    props.component_custom_range = False
    props.enclosure_custom_range = False


def test_source_diagnostics():
    print("\n[18] Saying why nothing was found")
    from exploded_assembly_studio import core

    def layer_for(name, layer=None):
        layer = layer or bpy.context.view_layer.layer_collection
        if layer.collection.name == name:
            return layer
        for child in layer.children:
            found = layer_for(name, child)
            if found:
                return found
        return None

    def fresh():
        scene, collection, parts = build_box_scene()
        shell = bpy.data.collections.new("SHELL")
        collection.children.link(shell)
        for name, obj in list(parts.items()):
            if name.startswith("Shell_"):
                collection.objects.unlink(obj)
                shell.objects.link(obj)
        props = scene.eas
        props.source = 'COLLECTION'
        props.collection = collection
        props.enclosure_collection = shell
        props.use_phases = True
        select(list(collection.all_objects), active=parts['pcb'])
        return scene, collection, shell, parts

    def detect_error():
        try:
            bpy.ops.eas.detect_sides()
            return ""
        except RuntimeError as error:
            return str(error)

    # A working setup, as the control.
    scene, collection, shell, parts = fresh()
    check(detect_error() == "", "detect sides works on a sound setup")

    # The panels are fine but the source collection is unreachable.
    scene, collection, shell, parts = fresh()
    layer_for(collection.name).exclude = True
    message = detect_error()
    check(collection.name in message,
          f"the message names the source collection ({message[:60]})")
    check("invisible because" in message, "and says they are invisible")
    check("Use Hidden Objects" in message, "and points at the one click workaround")

    # The source is fine but the panels are excluded.
    scene, collection, shell, parts = fresh()
    layer_for("SHELL").exclude = True
    message = detect_error()
    check("enclosure collection" in message,
          f"an unreachable shell is reported as such ({message[:60]})")
    check("hidden or excluded" in message, "with the reason given")

    # A broken Source with a good enclosure collection is no longer fatal: the
    # enclosure collection is a source in its own right.
    scene, collection, shell, parts = fresh()
    scene.eas.collection = None
    check(detect_error() == "",
          "an unset Source is survivable while the enclosure collection stands")

    # The Source diagnostics themselves, with nothing else supplying objects.
    scene, collection, shell, parts = fresh()
    empty = bpy.data.collections.new("NOTHING_HERE")
    scene.collection.children.link(empty)
    scene.eas.collection = empty
    scene.eas.enclosure_collection = None
    message = detect_error()
    check("NOTHING_HERE" in message, f"an empty source names itself ({message[:60]})")

    # No collection chosen at all.
    scene, collection, shell, parts = fresh()
    scene.eas.collection = None
    scene.eas.enclosure_collection = None
    message = detect_error()
    check("Pick a collection" in message, f"an unset source says so ({message[:60]})")

    # Selected-objects mode with an empty selection.
    scene, collection, shell, parts = fresh()
    scene.eas.source = 'SELECTED'
    scene.eas.enclosure_collection = None
    bpy.ops.object.select_all(action='DESELECT')
    message = detect_error()
    check("Select the assembly parts" in message, f"an empty selection says so ({message[:60]})")

    # Panels present but nothing tagged as enclosure. Nothing is broken here,
    # so this is a warning rather than an error, which bpy.ops does not raise.
    scene, collection, shell, parts = fresh()
    scene.eas.enclosure_collection = None
    for obj in collection.all_objects:
        obj.eas.role = 'PART'
    raised = detect_error()
    result = bpy.ops.eas.detect_sides()
    check(raised == "" and result == {'CANCELLED'},
          "nothing tagged is a warning and a clean cancel, not an error")

    # That warning is the one the user sees most, so it has to carry its own
    # diagnosis: which collection, how much of it is in range, how many tags.
    message = core.enclosure_report(bpy.context)
    check("no enclosure collection is set" in message,
          f"the warning says the collection is unset ({message[:70]})")
    check("0 object(s) are marked Enclosure" in message,
          "and counts the hand marked panels")

    scene.eas.enclosure_collection = shell
    message = core.enclosure_report(bpy.context)
    check("'SHELL'" in message and "6 object(s)" in message,
          f"a set collection is named with its size ({message[:70]})")
    check("6 of them in range" in message, "and how many of them are reachable")

    # An enclosure collection sitting beside the Source collection rather than
    # inside it used to be collected by nobody: named, tagged, listed in the
    # panel, and never animated. Choosing it is enough.
    scene, collection, shell, parts = fresh()
    outside_collection = bpy.data.collections.new("OUTSIDE")
    scene.collection.children.link(outside_collection)
    stray = add_box("Stray_Panel", (0.01, 0.01, 0.01), (0, 0, 0.2), outside_collection)
    scene.eas.enclosure_collection = outside_collection
    collected = {o.name for o in core.collect_objects(bpy.context)}
    check(stray.name in collected,
          f"an enclosure collection beside Source is collected anyway ({len(collected)})")
    hidden, outside, parented = core.missing_from_source(bpy.context, outside_collection)
    check(not hidden and not outside and not parented,
          f"so nothing is reported unreachable ({hidden} {outside} {parented})")
    check(core.is_enclosure_member(scene.eas, stray), "and it counts as a panel")
    check(detect_error() == "", "and Detect Sides works on it")
    check(stray.eas.side != 'AUTO', f"with a side detected ({stray.eas.side})")

    select(list(collection.all_objects) + [stray], active=parts['pcb'])
    bpy.ops.eas.set_assembly_position()
    bpy.ops.eas.animate(mode='ASSEMBLE')
    check(bool(key_frames(stray)),
          "and it is actually animated, which was the whole complaint")

    scene.eas.enclosure_collection = shell
    layer_for("SHELL").exclude = True
    hidden, outside, parented = core.missing_from_source(bpy.context, shell)
    check(len(hidden) == 6 and not outside and not parented,
          f"an excluded panel is reported as hidden ({len(hidden)} hidden, {len(outside)} outside)")

    # A panel parented to a part is dropped on purpose, and used to be reported
    # as hidden - which sent the fix looking in the outliner for nothing.
    scene, collection, shell, parts = fresh()
    scene.eas.skip_child_parts = True
    for obj in shell.all_objects:
        obj.parent = parts['pcb']
        obj.matrix_parent_inverse = parts['pcb'].matrix_world.inverted()
    select(list(collection.all_objects), active=parts['pcb'])
    hidden, outside, parented = core.missing_from_source(bpy.context, shell)
    check(len(parented) == 6 and not hidden and not outside,
          f"a parented panel is reported as parented ({len(parented)} parented, "
          f"{len(hidden)} hidden)")

    message = detect_error()
    check("Skip Parented Children" in message,
          f"and detect sides names the switch to turn off ({message[:70]})")

    scene.eas.skip_child_parts = False
    hidden, outside, parented = core.missing_from_source(bpy.context, shell)
    check(not parented and not hidden and not outside,
          "turning the switch off makes them reachable again")
    check(detect_error() == "", "and detect sides then finds them")

    # Marking is only half the job: an object outside the Source set is never
    # animated, and "Marked 3 object(s)" reads as success. Mark Enclosure asks
    # core.unreachable before saying so.
    scene, collection, shell, parts = fresh()
    stray = add_box("Loose_Panel", (0.01, 0.01, 0.01), (0, 0, 0.3), scene.collection)
    select([stray], active=stray)
    result = bpy.ops.eas.mark_role(role='ENCLOSURE')
    check(result == {'FINISHED'} and stray.eas.role == 'ENCLOSURE',
          "an object outside Source can still be marked")
    check(core.unreachable(bpy.context, [stray]) == [stray.name],
          f"but it is reported unreachable ({core.unreachable(bpy.context, [stray])})")

    select(list(collection.all_objects), active=parts['pcb'])
    inside = [parts['pcb'], parts['Shell_Top']]
    check(core.unreachable(bpy.context, inside) == [],
          "while objects in the Source set are reachable")


def test_hidden_sources():
    print("\n[19] Naming the switch that hides a collection")
    from exploded_assembly_studio import core

    def layer_for(name, layer=None):
        layer = layer or bpy.context.view_layer.layer_collection
        if layer.collection.name == name:
            return layer
        for child in layer.children:
            found = layer_for(name, child)
            if found:
                return found
        return None

    def fresh():
        scene, collection, parts = build_scene()
        props = scene.eas
        props.source = 'COLLECTION'
        props.collection = collection
        props.visible_only = True
        props.use_camera = False
        props.direction = 'WORLD_AXIS'
        props.axis = 'Z'
        props.distance = 0.05
        select(list(collection.all_objects), active=parts['pcb'])
        return scene, collection, parts

    # Each of the three outliner controls must be named distinctly, because
    # each one is clicked in a different place.
    cases = [
        ("checkbox", lambda scene, coll: setattr(layer_for(coll.name), "exclude", True)),
        ("eye icon", lambda scene, coll: setattr(layer_for(coll.name), "hide_viewport", True)),
        ("monitor icon", lambda scene, coll: setattr(coll, "hide_viewport", True)),
    ]
    for expected, apply in cases:
        scene, collection, parts = fresh()
        apply(scene, collection)
        message = core.source_report(bpy.context)
        check(expected in message, f"'{expected}' named in the message ({message[:70]})")
        check(collection.name in message, f"and the collection named too ({expected})")

    # Individually hidden objects are a fourth, different situation.
    scene, collection, parts = fresh()
    for obj in collection.all_objects:
        obj.hide_set(True)
    message = core.source_report(bpy.context)
    check("one by one" in message, f"per object hiding is named ({message[:70]})")

    # ---- and the one click escape hatch ------------------------------------
    scene, collection, parts = fresh()
    layer_for(collection.name).exclude = True
    check(not core.collect_objects(bpy.context), "nothing collected while excluded")

    result = bpy.ops.eas.use_hidden_objects()
    check(result == {'FINISHED'}, "Use Hidden Objects ran")
    check(not scene.eas.visible_only, "it turned Visible Only off")
    recovered = core.collect_objects(bpy.context)
    check(len(recovered) == len(collection.all_objects),
          f"and every hidden part is back in range ({len(recovered)})")

    # The whole workflow has to work on objects that are still hidden: only
    # transforms and keyframes are written, and neither needs visibility.
    objects = list(collection.all_objects)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.eas.set_assembly_position()
    assembled = world_matrices(objects)
    result = bpy.ops.eas.animate(mode='ASSEMBLE')
    check(result == {'FINISHED'}, "an excluded assembly still animates")

    end = at_frame(scene.eas.frame_end, objects)
    worst = max(
        max(abs(x - y) for ra, rb in zip(assembled[n], end[n]) for x, y in zip(ra, rb))
        for n in assembled
    )
    check(worst <= TOLERANCE, f"and still lands home exactly ({worst:.3e})")

    start = at_frame(scene.eas.frame_start, objects)
    lifted = start['Top_Case'].translation.z - assembled['Top_Case'].translation.z
    check(lifted > 1e-4, f"having really moved on the way ({lifted:+.4f})")

    # Once nothing is hidden, the button has no reason to be offered.
    scene, collection, parts = fresh()
    check(bool(core.collect_objects(bpy.context)), "a visible collection needs no workaround")


def test_grouping():
    print("\n[20] Multi piece parts moving as one")
    from exploded_assembly_studio import core

    def fresh(mode, separator="_"):
        """A board with two components, each built from three loose pieces."""
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        collection = bpy.data.collections.new("ASSEMBLY")
        scene.collection.children.link(collection)

        pcb = add_box("PCB", (0.10, 0.06, 0.0016), (0, 0, 0), collection)
        pieces = {}
        for index, x in enumerate((-0.03, 0.03)):
            label = f"U{index + 1}"
            home = bpy.data.collections.new(label)
            collection.children.link(home)
            for piece, dx, dz in (("body", 0.0, 0.004),
                                  ("pins", 0.004, 0.001),
                                  ("dot", -0.004, 0.006)):
                name = f"{label}_{piece}"
                pieces[name] = add_box(
                    name, (0.006, 0.006, 0.002), (x + dx, 0.0, dz), home,
                )

        props = scene.eas
        props.source = 'COLLECTION'
        props.collection = collection
        props.use_camera = False
        props.direction = 'WORLD_AXIS'
        props.axis = 'Z'
        props.distance = 0.05
        props.magnitude = 'UNIFORM'
        props.use_sequence = True
        props.overlap = 0.0
        props.group_mode = mode
        props.group_separator = separator
        props.frame_start = 1
        props.frame_end = 60

        objects = list(collection.all_objects)
        select(objects, active=pcb)
        bpy.ops.eas.set_assembly_position()
        return scene, collection, pcb, pieces, objects

    def rigid_error(objects, frame, reference):
        """How far the pieces of a group drift apart, relative to each other."""
        state = at_frame(frame, objects)
        worst = 0.0
        for name in reference:
            for other in reference:
                if name == other:
                    continue
                now = (state[name].translation - state[other].translation).length
                then = (reference[name] - reference[other]).length
                worst = max(worst, abs(now - then))
        return worst

    # ---- off: today's behaviour, every piece on its own ---------------------
    scene, collection, pcb, pieces, objects = fresh('NONE')
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    keys = {part.group for part in parts}
    check(len(keys) == len(parts), f"off, every object is its own part ({len(keys)})")

    ordered = core.order_parts(bpy.context, parts)
    timing = core.build_timing(scene.eas, ordered)
    slots = {tuple(round(v, 3) for v in window) for window in timing.values()}
    check(len(slots) == len(parts),
          f"and every object gets its own slot in the stagger ({len(slots)})")

    # ---- collection: the pieces of U1 share a sub-collection ---------------
    scene, collection, pcb, pieces, objects = fresh('COLLECTION')
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    keys = {part.group for part in parts}
    check(len(keys) == 3, f"grouped by collection there are three parts ({len(keys)})")

    by_name = {part.obj.name: part for part in parts}
    u1 = [by_name[name] for name in pieces if name.startswith("U1_")]
    check(len({tuple(round(v, 6) for v in p.offset) for p in u1}) == 1,
          f"the pieces of U1 share one offset ({[tuple(round(v, 4) for v in p.offset) for p in u1]})")
    check(len({tuple(round(v, 6) for v in p.center) for p in u1}) == 1,
          "and one centre, which is what makes rotation rigid too")

    ordered = core.order_parts(bpy.context, parts)
    timing = core.build_timing(scene.eas, ordered)
    slots = {tuple(round(v, 3) for v in window) for window in timing.values()}
    check(len(slots) == 3, f"three parts take three slots, not seven ({len(slots)})")
    u1_windows = {tuple(round(v, 3) for v in timing[name]) for name in pieces if name.startswith("U1_")}
    check(len(u1_windows) == 1, f"and U1's pieces move over one window ({u1_windows})")

    # The real test: the pieces must not drift apart during the animation.
    reference = {name: obj.matrix_world.translation.copy()
                 for name, obj in pieces.items() if name.startswith("U1_")}
    bpy.ops.eas.animate(mode='ASSEMBLE')
    worst = max(rigid_error(objects, frame, reference) for frame in (1, 15, 30, 45, 60))
    check(worst <= TOLERANCE, f"U1 stays rigid across the whole assemble ({worst:.3e})")

    home = at_frame(scene.eas.frame_end, objects)
    landed = max(
        (home[name].translation - reference[name]).length for name in reference
    )
    check(landed <= TOLERANCE, f"and lands exactly home ({landed:.3e})")

    start = at_frame(scene.eas.frame_start, objects)
    travelled = (start["U1_body"].translation - reference["U1_body"]).length
    check(travelled > 1e-4, f"having really travelled ({travelled:.4f})")

    # ---- name prefix, for imports that have no sub-collections -------------
    scene, collection, pcb, pieces, objects = fresh('PREFIX')
    for obj in list(collection.all_objects):
        for child in list(collection.children):
            if child.all_objects.get(obj.name) is not None:
                child.objects.unlink(obj)
                collection.objects.link(obj)
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    keys = {part.group for part in parts}
    check(len(keys) == 3, f"prefix grouping finds the same three parts ({len(keys)})")

    by_name = {part.obj.name: part for part in parts}
    u2 = [by_name[name] for name in pieces if name.startswith("U2_")]
    check(len({tuple(round(v, 6) for v in p.offset) for p in u2}) == 1,
          "U2's pieces share one offset")
    check(by_name["PCB"].group != u2[0].group, "and the board is not swept in with them")

    # A separator that appears in nothing leaves every object alone.
    scene.eas.group_separator = "@"
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    check(len({part.group for part in parts}) == len(parts),
          "a separator that matches nothing groups nothing")

    # ---- overlap, for imports whose names carry nothing --------------------
    def overlapping():
        """Two components in three interpenetrating pieces each, named blindly.

        Modelled on a real ECAD import: ComponentBody.3088, .3089, .3090 with
        no prefix to go on, the pieces sitting inside one another, and the whole
        lot standing on a board that dwarfs them.
        """
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        collection = bpy.data.collections.new("ASSEMBLY")
        scene.collection.children.link(collection)

        pcb = add_box("PCB", (0.10, 0.06, 0.0016), (0, 0, 0), collection)
        pieces = {}
        counter = 3088
        for x in (-0.03, 0.03):
            for dx, dz, size in ((0.0, 0.004, (0.008, 0.008, 0.004)),
                                 (0.002, 0.004, (0.007, 0.007, 0.003)),
                                 (-0.002, 0.005, (0.006, 0.006, 0.003))):
                name = f"ComponentBody.{counter}"
                counter += 1
                pieces[name] = add_box(name, size, (x + dx, 0.0, dz), collection)

        props = scene.eas
        props.source = 'COLLECTION'
        props.collection = collection
        props.use_camera = False
        props.direction = 'WORLD_AXIS'
        props.axis = 'Z'
        props.distance = 0.05
        props.magnitude = 'UNIFORM'
        props.group_mode = 'OVERLAP'
        props.group_overlap = 0.2
        select(list(collection.all_objects), active=pcb)
        bpy.ops.eas.set_assembly_position()
        return scene, collection, pcb, pieces

    scene, collection, pcb, pieces = overlapping()
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    by_name = {part.obj.name: part for part in parts}
    keys = {part.group for part in parts}
    check(len(keys) == 3, f"overlap finds two components and a board ({len(keys)})")

    left = [by_name[f"ComponentBody.{n}"] for n in (3088, 3089, 3090)]
    right = [by_name[f"ComponentBody.{n}"] for n in (3091, 3092, 3093)]
    check(len({part.group for part in left}) == 1,
          "the three pieces stacked together are one part")
    check(left[0].group != right[0].group,
          "and the component on the other side of the board is a different one")

    # The trap: a component standing on a board it barely touches must not be
    # swallowed by it, or the whole assembly becomes one immovable part.
    check(by_name["PCB"].group != left[0].group,
          "the board is not swept in with what stands on it")

    check(len({tuple(round(v, 6) for v in p.offset) for p in left}) == 1,
          "the grouped pieces share one offset")

    # An enclosure wraps the product, so its box holds every part by definition.
    # Without a role boundary the case and everything inside it became one part.
    shell = bpy.data.collections.new("SHELL")
    collection.children.link(shell)
    lid = add_box("Shell_Top", (0.12, 0.08, 0.03), (0, 0, 0.004), shell)
    base = add_box("Shell_Bottom", (0.12, 0.08, 0.03), (0, 0, -0.004), shell)
    scene.eas.enclosure_collection = shell
    select(list(collection.all_objects), active=pcb)
    bpy.ops.eas.set_assembly_position()

    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    by_name = {part.obj.name: part for part in parts}
    sizes = {}
    for part in parts:
        sizes[part.group] = sizes.get(part.group, 0) + 1
    check(by_name["Shell_Top"].group != by_name["ComponentBody.3088"].group,
          "a shell panel does not swallow the components it wraps")
    check(by_name["Shell_Top"].group != by_name["PCB"].group,
          "nor the board it wraps")
    check(max(sizes.values()) <= 3,
          f"so no part is bigger than a real component ({sorted(sizes.values())})")
    check(len({by_name[n].group for n in ("ComponentBody.3088", "ComponentBody.3089",
                                          "ComponentBody.3090")}) == 1,
          "and the component pieces are still found")

    # A lid and a base overlap at the seam and open in opposite directions, so
    # they must not become one panel either.
    check(by_name["Shell_Top"].group == by_name["Shell_Bottom"].group,
          "untagged panels that interpenetrate do group")
    result = bpy.ops.eas.detect_sides()
    check(result == {'FINISHED'}, "detect sides runs on the shell")
    check((lid.eas.side, base.eas.side) == ('TOP', 'BOTTOM'),
          f"and gives them opposite sides ({lid.eas.side}, {base.eas.side})")

    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    by_name = {part.obj.name: part for part in parts}
    check(by_name["Shell_Top"].group != by_name["Shell_Bottom"].group,
          "once the sides differ they are two parts again")
    lifted = by_name["Shell_Top"].offset.z
    dropped = by_name["Shell_Bottom"].offset.z
    check(lifted > 0.0 > dropped,
          f"and they open opposite ways ({lifted:+.3f}, {dropped:+.3f})")

    # Size Match is the general form of the same guard, for a big ordinary part.
    scene.eas.enclosure_collection = None
    scene.eas.group_size_match = 0.0
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    by_name = {part.obj.name: part for part in parts}
    swallowed = by_name["Shell_Top"].group == by_name["ComponentBody.3088"].group
    check(swallowed, "with no role and no size guard, a big box does swallow them")

    scene.eas.group_size_match = 0.05
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    by_name = {part.obj.name: part for part in parts}
    check(by_name["Shell_Top"].group != by_name["ComponentBody.3088"].group,
          "Size Match stops a part far bigger than its neighbour joining it")
    check(len({by_name[n].group for n in ("ComponentBody.3088", "ComponentBody.3089",
                                          "ComponentBody.3090")}) == 1,
          "while pieces of comparable size still group")

    scene.eas.group_size_match = 0.0
    for obj in (lid, base):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(shell)
    select(list(collection.all_objects), active=pcb)

    # Chaining is transitive, so the threshold has to be able to break it.
    scene.eas.group_overlap = 0.95
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    check(len({part.group for part in parts}) == len(parts),
          "a strict threshold stops grouping entirely")

    scene.eas.group_overlap = 0.001
    sizes = core.group_sizes(scene.eas, core.collect_objects(bpy.context))
    check(max(sizes.values()) >= 3, f"a loose threshold groups more ({sorted(sizes.values())})")

    # ---- a per object multiplier cannot tear a group apart -----------------
    scene, collection, pcb, pieces, objects = fresh('COLLECTION')
    pieces["U1_pins"].eas.distance_multiplier = 4.0
    parts, _ = core.build_parts(bpy.context)
    core.compute_explosion(bpy.context, parts)
    by_name = {part.obj.name: part for part in parts}
    u1 = [by_name[name] for name in pieces if name.startswith("U1_")]
    check(len({tuple(round(v, 6) for v in p.offset) for p in u1}) == 1,
          f"a stray multiplier does not split the group "
          f"({[round(p.offset.length, 4) for p in u1]})")


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
    test_camera_delay()
    test_camera_multipoint()
    test_enclosure_phase()
    test_enclosure_camera_rules()
    test_rebuild()
    test_snapshots()
    test_parts_offscreen()
    test_pre_post_roll()
    test_enclosure_custom_range()
    test_enclosure_collection()
    test_source_diagnostics()
    test_hidden_sources()
    test_grouping()

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
