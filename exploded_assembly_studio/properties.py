"""Property definitions for Exploded Assembly Studio.

Scene level settings live on ``Scene.eas`` and per object data on ``Object.eas``.
Nothing here touches mesh, material or origin data (see spec section 19).
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Object, PropertyGroup, Scene

IDENTITY_16 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)

SOURCE_ITEMS = [
    ('SELECTED', "Selected Objects", "Use the objects currently selected in the viewport", 'RESTRICT_SELECT_OFF', 0),
    ('COLLECTION', "Collection", "Use every object inside the chosen collection", 'OUTLINER_COLLECTION', 1),
]

DIRECTION_ITEMS = [
    ('CENTER', "From Center", "Every part moves away from the assembly center (radial)", 'FULLSCREEN_ENTER', 0),
    ('AXIS_SPLIT', "Axis +/- (Split)", "Parts above the center move along +Axis, parts below along -Axis. "
                                       "Best for stacked products: PCB stays, components go up, bottom shell goes down", 'ARROW_LEFTRIGHT', 1),
    ('WORLD_AXIS', "World Axis", "Every part moves along the same world axis", 'EMPTY_ARROWS', 2),
    ('LOCAL_AXIS', "Local Axis", "Every part moves along its own local axis", 'ORIENTATION_LOCAL', 3),
]

AXIS_ITEMS = [
    ('X', "X", "World X axis"),
    ('Y', "Y", "World Y axis"),
    ('Z', "Z", "World Z axis"),
]

MAGNITUDE_ITEMS = [
    ('UNIFORM', "Uniform", "Every part travels the same distance"),
    ('PROPORTIONAL', "Proportional", "Parts further from the center travel further"),
    ('LAYERED', "Layered", "Distance multiplied by the part's layer index, so stacked parts fan out evenly"),
]

CENTER_ITEMS = [
    ('BOUNDS', "Bounding Box", "Center of the combined bounding box of all parts"),
    ('MEDIAN', "Median Point", "Average of the part origins"),
    ('CURSOR', "3D Cursor", "Use the 3D cursor position"),
    ('ACTIVE', "Active Object", "Use the active object's center"),
]

ORDER_ITEMS = [
    ('DISTANCE', "Distance From Center", "Outermost parts move first"),
    ('AXIS', "Axis Position", "Sorted by position along the explode axis"),
    ('NAME', "Name", "Alphabetical order"),
    ('COLLECTION', "Collection Order", "Order the objects appear in the collection / selection"),
    ('MANUAL', "Manual", "Use the per object Sequence Order value"),
]

INTERPOLATION_ITEMS = [
    ('BEZIER', "Bezier", "Smooth default easing"),
    ('LINEAR', "Linear", "Constant speed"),
    ('SINE', "Sine", "Gentle sinusoidal easing"),
    ('QUAD', "Quadratic", "Quadratic easing"),
    ('CUBIC', "Cubic", "Cubic easing"),
    ('EXPO', "Exponential", "Strong easing"),
    ('BACK', "Back", "Overshoots slightly, good for product ads"),
    ('ELASTIC', "Elastic", "Springy settle"),
]

EASING_ITEMS = [
    ('AUTO', "Automatic", "Let Blender choose"),
    ('EASE_IN', "Ease In", "Slow start"),
    ('EASE_OUT', "Ease Out", "Slow end"),
    ('EASE_IN_OUT', "Ease In Out", "Slow start and end"),
]

ROLE_ITEMS = [
    ('PART', "Part", "An inner component. Parts move first when assembling", 'MESH_DATA', 0),
    ('ENCLOSURE', "Enclosure", "A shell panel. Enclosure panels close over the product after the "
                               "parts have landed", 'MESH_CUBE', 1),
]

#: Enclosure sides and the world direction each one opens towards.
SIDE_ITEMS = [
    ('AUTO', "Auto", "Work the side out from where the panel sits in the product"),
    ('TOP', "Top", "Opens upwards, +Z"),
    ('BOTTOM', "Bottom", "Opens downwards, -Z"),
    ('FRONT', "Front", "Opens towards the front, -Y"),
    ('BACK', "Back", "Opens towards the back, +Y"),
    ('RIGHT', "Right", "Opens to the right, +X"),
    ('LEFT', "Left", "Opens to the left, -X"),
]

MOTION_ITEMS = [
    ('LINEAR', "Linear", "Travel straight to the next viewpoint"),
    ('ARC', "Arc", "Curve around the subject on the way to the next viewpoint"),
]


def _seed_component_range(self, context):
    """A custom component range starts from the shot it is carved out of."""
    if not self.component_custom_range:
        return
    low, high = min(self.frame_start, self.frame_end), max(self.frame_start, self.frame_end)
    self.component_frame_start = low
    self.component_frame_end = high


def _seed_enclosure_range(self, context):
    """Start a custom enclosure range from whatever the automatic split gave.

    Switching to explicit frames should continue what was already happening
    rather than jumping to arbitrary numbers.
    """
    if not self.enclosure_custom_range:
        return
    from . import core
    start, end = core.derived_enclosure_window(self)
    self.enclosure_frame_start = int(round(start))
    self.enclosure_frame_end = int(round(end))


def _enclosure_collection_set(self, context):
    """Picking a collection turns the phase on, the way marking by hand does.

    Every code path that treats a panel as a shell is gated behind use_phases,
    so choosing the collection and nothing else looked like it had worked while
    the panels quietly animated as ordinary parts. Marking by hand has always
    switched it on; the collection is the same statement of intent.
    """
    if self.enclosure_collection is not None:
        self.use_phases = True


def _subject_poll(self, obj):
    """Only offer objects that can actually be framed."""
    if obj.eas.is_rig:
        return False
    return obj.type not in {'CAMERA', 'LIGHT', 'SPEAKER', 'LIGHT_PROBE'}


class EAS_CameraPose(PropertyGroup):
    """One captured camera viewpoint on the camera path.

    ``motion``, ``roll``, ``interpolation`` and ``easing`` describe the segment
    that *leaves* this pose, so the last pose's segment settings are unused.
    """

    matrix: FloatVectorProperty(
        name="Matrix",
        description="Captured camera world matrix, row major",
        size=16,
        default=IDENTITY_16,
    )
    lens: FloatProperty(
        name="Focal Length",
        description="Focal length captured with this viewpoint",
        default=50.0,
        min=1.0,
    )
    position: FloatProperty(
        name="Time",
        description="Where this viewpoint sits in the camera move. 0 is the first frame, 1 the last",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    motion: EnumProperty(
        name="Motion",
        description="How the camera travels from this viewpoint to the next one",
        items=MOTION_ITEMS,
        default='LINEAR',
    )
    roll: FloatProperty(
        name="Roll",
        description="Tilt the camera around its own view axis at this viewpoint",
        default=0.0,
        subtype='ANGLE',
        soft_min=-3.14159,
        soft_max=3.14159,
    )
    interpolation: EnumProperty(
        name="Interpolation",
        description="Timing curve of the segment leaving this viewpoint",
        items=INTERPOLATION_ITEMS,
        default='SINE',
    )
    easing: EnumProperty(
        name="Easing",
        description="Easing of the segment leaving this viewpoint",
        items=EASING_ITEMS,
        default='EASE_IN_OUT',
    )


class EAS_Snapshot(PropertyGroup):
    """A restore point: every setting, plus where the parts were sitting.

    The payload is JSON in a string property, which keeps snapshots taken by an
    older version readable when settings are added or renamed later.
    """

    name: StringProperty(name="Name", default="Snapshot")
    note: StringProperty(name="Note", default="")
    data: StringProperty(name="Data", default="")


class EAS_ObjectProperties(PropertyGroup):
    """Per object assembly data. Stored in the .blend so it survives reloads."""

    role: EnumProperty(
        name="Role",
        description="Whether this object is an inner part or a shell panel",
        items=ROLE_ITEMS,
        default='PART',
    )
    side: EnumProperty(
        name="Side",
        description="Which way this enclosure panel opens. Set it by hand to override the automatic "
                    "guess, for instance to bring a front panel down from above instead",
        items=SIDE_ITEMS,
        default='AUTO',
    )

    has_state: BoolProperty(
        name="Has Assembly State",
        description="True when this object's assembled transform has been recorded",
        default=False,
    )
    assembly_matrix: FloatVectorProperty(
        name="Assembly Matrix",
        description="Recorded local (basis) matrix of the assembled state, row major",
        size=16,
        default=IDENTITY_16,
    )
    distance_multiplier: FloatProperty(
        name="Distance Multiplier",
        description="Scales this part's explode distance",
        default=1.0,
        soft_min=0.0,
        soft_max=5.0,
    )
    order: IntProperty(
        name="Sequence Order",
        description="Position in the staggered animation when Order Mode is Manual. Lower moves first",
        default=0,
        min=0,
    )
    exclude: BoolProperty(
        name="Exclude From Explosion",
        description="Keep this object pinned in place (it still gets an assembly state)",
        default=False,
    )
    is_rig: BoolProperty(
        name="Is Camera Rig",
        description="Marks objects generated by the add-on camera rig",
        default=False,
    )


class EAS_SceneProperties(PropertyGroup):
    """All add-on settings for one scene."""

    # ------------------------------------------------------------------ source
    source: EnumProperty(
        name="Source",
        description="Where the parts come from",
        items=SOURCE_ITEMS,
        default='SELECTED',
    )
    collection: PointerProperty(
        name="Collection",
        description="Collection holding the assembly",
        type=bpy.types.Collection,
    )
    visible_only: BoolProperty(
        name="Visible Only",
        description="Skip objects hidden in the current view layer",
        default=True,
    )
    skip_child_parts: BoolProperty(
        name="Skip Parented Children",
        description="If a part's parent is also part of the assembly, only the parent is animated so the "
                    "child follows it instead of moving twice",
        default=True,
    )

    # --------------------------------------------------------------- explosion
    direction: EnumProperty(
        name="Direction",
        description="How the explode vector is built for each part",
        items=DIRECTION_ITEMS,
        default='CENTER',
    )
    axis: EnumProperty(
        name="Axis",
        description="Axis used by the axis based direction modes",
        items=AXIS_ITEMS,
        default='Z',
    )
    distance: FloatProperty(
        name="Distance",
        description="Explode distance in scene units",
        default=2.0,
        soft_min=0.0,
        soft_max=50.0,
        unit='LENGTH',
    )
    magnitude: EnumProperty(
        name="Spacing",
        description="How the distance is distributed over the parts",
        items=MAGNITUDE_ITEMS,
        default='UNIFORM',
    )
    center_mode: EnumProperty(
        name="Center",
        description="Reference point of the assembly",
        items=CENTER_ITEMS,
        default='BOUNDS',
    )
    parts_offscreen: BoolProperty(
        name="Start Off Camera",
        description="Push every part far enough along its own explode direction to start completely "
                    "outside the camera frame, so an assemble animation begins on an empty shot and "
                    "the parts fly in. The explode Distance becomes a minimum",
        default=False,
    )
    use_bounds_center: BoolProperty(
        name="Use Geometry Center",
        description="Measure each part from its bounding box center instead of its origin. Turn off for "
                    "CAD models whose origins carry meaning",
        default=True,
    )
    layer_tolerance: FloatProperty(
        name="Layer Tolerance",
        description="Fraction of the assembly size within which parts count as the same layer. Parts on the "
                    "same layer travel the same distance, and in Axis +/- mode parts inside this band around "
                    "the center stay put - that is what keeps the PCB still while everything else separates",
        default=0.02,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )

    # ---------------------------------------------------------------- rotation
    use_rotation: BoolProperty(
        name="Rotate While Exploding",
        description="Add a spin to each part as it travels",
        default=False,
    )
    rotation_angle: FloatProperty(
        name="Rotation",
        description="Extra rotation applied at the exploded state",
        default=0.0,
        subtype='ANGLE',
        soft_min=-6.28319,
        soft_max=6.28319,
    )
    rotation_axis: EnumProperty(
        name="Rotation Axis",
        description="Axis the extra rotation spins around",
        items=AXIS_ITEMS,
        default='Z',
    )
    rotation_local: BoolProperty(
        name="Local Spin Axis",
        description="Spin around the part's own axis instead of the world axis",
        default=False,
    )

    # --------------------------------------------------------------- sequence
    use_sequence: BoolProperty(
        name="Staggered Sequence",
        description="Parts move one after another instead of all together",
        default=False,
    )
    order_mode: EnumProperty(
        name="Order",
        description="How the move order is decided",
        items=ORDER_ITEMS,
        default='DISTANCE',
    )
    reverse_order: BoolProperty(
        name="Reverse Order",
        description="Flip the computed order",
        default=False,
    )
    reverse_on_assemble: BoolProperty(
        name="Mirror Order On Assemble",
        description="Assemble plays the sequence backwards, so parts come back in the opposite order they left",
        default=True,
    )
    overlap: FloatProperty(
        name="Overlap",
        description="0 = strictly one part after another, 1 = all parts at the same time",
        default=0.6,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )

    # ------------------------------------------------------- enclosure phase
    use_phases: BoolProperty(
        name="Enclosure Closes Last",
        description="Split the animation in two: the inner parts land on the board first, then the "
                    "enclosure panels close over them. Explode runs it the other way round, opening "
                    "the shell before the parts come out",
        default=False,
    )
    parts_share: FloatProperty(
        name="Parts Share",
        description="How much of the frame range the parts phase gets. The enclosure phase gets the rest",
        default=0.6,
        min=0.05,
        max=0.95,
        subtype='FACTOR',
    )
    phase_gap_frames: IntProperty(
        name="Phase Delay",
        description="Frames to wait after the last part has landed before the enclosure starts "
                    "closing. The shell never begins before every part has finished",
        default=10,
        min=0,
        soft_max=200,
    )
    enclosure_collection: PointerProperty(
        name="Enclosure Collection",
        description="Every object in this collection counts as an enclosure panel, without having "
                    "to mark them one by one. Objects marked Enclosure by hand still count too",
        type=bpy.types.Collection,
        update=_enclosure_collection_set,
    )
    enclosure_custom_range: BoolProperty(
        name="Custom Frame Range",
        description="Give the enclosure its own start and end frame instead of deriving them from "
                    "Parts Share and Phase Delay. The parts keep their own window, so the two are "
                    "timed completely independently",
        default=False,
        update=_seed_enclosure_range,
    )
    enclosure_frame_start: IntProperty(
        name="Enclosure Start",
        description="Frame the enclosure panels start moving on",
        default=40,
    )
    enclosure_frame_end: IntProperty(
        name="Enclosure End",
        description="Frame the enclosure panels finish on",
        default=60,
    )
    enclosure_offscreen: BoolProperty(
        name="Start Off Camera",
        description="Park each enclosure panel far enough away that it is completely outside the "
                    "camera frame until its own phase begins, so it does not block the view of the "
                    "board while the parts are landing",
        default=True,
    )
    enclosure_avoid_camera: BoolProperty(
        name="Never Enter Past Camera",
        description="Stop a panel travelling in from the side the camera is on, so it never sweeps "
                    "across the lens. A front panel in a front view comes down from above instead",
        default=True,
    )
    enclosure_camera_margin: FloatProperty(
        name="Off Camera Margin",
        description="Extra clearance beyond the edge of frame when parking anything off camera, "
                    "for both enclosure panels and parts",
        default=1.15,
        min=1.0,
        soft_max=3.0,
    )
    enclosure_distance_factor: FloatProperty(
        name="Enclosure Distance",
        description="Extra travel for enclosure panels, so the shell clears the parts inside it",
        default=1.5,
        min=0.0,
        soft_max=5.0,
    )

    # -------------------------------------------------------------- animation
    frame_start: IntProperty(
        name="Start Frame",
        description="First frame of the generated animation",
        default=1,
    )
    frame_end: IntProperty(
        name="End Frame",
        description="Last frame of the generated animation",
        default=60,
    )
    component_custom_range: BoolProperty(
        name="Custom Range",
        description="Give the components their own start and end frame instead of using the whole "
                    "shot. Frames outside their range are time the camera still moves through, so "
                    "a shot can open before anything assembles and carry on afterwards",
        default=False,
        update=_seed_component_range,
    )
    component_frame_start: IntProperty(
        name="Start Frame",
        description="Frame the components start moving on",
        default=1,
    )
    component_frame_end: IntProperty(
        name="End Frame",
        description="Frame the components finish on",
        default=60,
    )
    interpolation: EnumProperty(
        name="Interpolation",
        description="F-Curve interpolation of the generated keyframes",
        items=INTERPOLATION_ITEMS,
        default='BEZIER',
    )
    easing: EnumProperty(
        name="Easing",
        description="Easing direction, ignored by Bezier and Linear",
        items=EASING_ITEMS,
        default='EASE_IN_OUT',
    )
    replace_animation: BoolProperty(
        name="Replace Existing",
        description="Remove existing transform keyframes on the parts before writing new ones",
        default=True,
    )
    set_scene_range: BoolProperty(
        name="Set Scene Frame Range",
        description="Also set the scene start/end frame to match",
        default=True,
    )
    auto_store_state: BoolProperty(
        name="Auto Save Assembly State",
        description="Record the assembled transform automatically for parts that do not have one yet",
        default=True,
    )

    # ----------------------------------------------------------------- camera
    use_camera: BoolProperty(
        name="Animate Camera",
        description="Build and animate a camera rig together with the parts",
        default=False,
    )
    camera_object: PointerProperty(name="Camera", type=Object)
    camera_pivot: PointerProperty(name="Camera Pivot", type=Object)
    camera_target: PointerProperty(name="Camera Target", type=Object)

    camera_mode: EnumProperty(
        name="Camera Mode",
        description="How the camera move is defined",
        items=[
            ('ORBIT', "Orbit", "Automatic circular orbit that frames the whole exploded assembly"),
            ('SUBJECT', "Frame Object", "Pick one object, usually the PCB, and let the camera work out a "
                                        "good distance from its size and orbit around it"),
            ('POSES', "From Viewport", "Frame the shot in the viewport and capture it as the start and "
                                       "end pose of the camera move"),
        ],
        default='ORBIT',
    )

    camera_subject: PointerProperty(
        name="Subject",
        description="Object the camera frames and orbits around. Its size decides the camera distance",
        type=Object,
        poll=_subject_poll,
    )

    # Poses captured from the viewport, stored as world matrices.
    camera_pose_start: FloatVectorProperty(
        name="Start Pose", size=16, default=IDENTITY_16,
        description="Captured camera matrix for the first frame",
    )
    camera_pose_end: FloatVectorProperty(
        name="End Pose", size=16, default=IDENTITY_16,
        description="Captured camera matrix for the last frame",
    )
    #: The camera path. Two poses behave exactly like the old start/end pair.
    camera_poses: CollectionProperty(type=EAS_CameraPose)
    camera_pose_index: IntProperty(name="Active Viewpoint", default=0, min=0)

    camera_delay_start: IntProperty(
        name="Hold Start",
        description="Frames to hold on the first viewpoint before the camera starts moving, so the "
                    "beginning of the assembly is not competing with a camera move",
        default=0,
        min=0,
        soft_max=120,
    )
    camera_delay_end: IntProperty(
        name="Hold End",
        description="Frames to hold on the last viewpoint after the camera has arrived",
        default=0,
        min=0,
        soft_max=120,
    )
    camera_arc_samples: IntProperty(
        name="Arc Quality",
        description="Frames between sampled keys on an arc segment. Lower is smoother and heavier",
        default=3,
        min=1,
        max=20,
    )

    camera_pose_start_set: BoolProperty(name="Start Pose Captured", default=False)
    camera_pose_end_set: BoolProperty(name="End Pose Captured", default=False)
    camera_pose_start_lens: FloatProperty(name="Start Focal Length", default=50.0, min=1.0)
    camera_pose_end_lens: FloatProperty(name="End Focal Length", default=50.0, min=1.0)
    camera_animate_focal: BoolProperty(
        name="Animate Focal Length",
        description="Blend the focal length between the two captured views as well as the position",
        default=True,
    )

    camera_focal: FloatProperty(
        name="Focal Length",
        description="Camera focal length in millimeters",
        default=50.0,
        min=1.0,
        soft_max=300.0,
    )
    camera_auto_distance: BoolProperty(
        name="Auto Frame",
        description="Compute the camera distance so the exploded assembly fits in frame",
        default=True,
    )
    camera_distance: FloatProperty(
        name="Distance",
        description="Manual camera distance from the assembly center",
        default=6.0,
        min=0.001,
        unit='LENGTH',
    )
    camera_margin: FloatProperty(
        name="Framing Margin",
        description="Extra room around the assembly when auto framing",
        default=1.25,
        min=1.0,
        soft_max=3.0,
    )
    camera_height: FloatProperty(
        name="Height",
        description="Camera height above the assembly center, as a factor of the assembly radius",
        default=0.55,
        soft_min=-3.0,
        soft_max=3.0,
    )
    camera_start_angle: FloatProperty(
        name="Start Angle",
        description="Orbit angle at the first frame",
        default=-0.523599,
        subtype='ANGLE',
    )
    camera_orbit: FloatProperty(
        name="Orbit",
        description="How far the camera travels around the assembly during the animation",
        default=2.0943951,
        subtype='ANGLE',
    )
    camera_use_dolly: BoolProperty(
        name="Dolly",
        description="Push the camera in or pull it out during the animation",
        default=True,
    )
    camera_zoom_start: FloatProperty(
        name="Distance Start",
        description="Distance multiplier at the first frame",
        default=1.35,
        min=0.05,
        soft_max=4.0,
    )
    camera_zoom_end: FloatProperty(
        name="Distance End",
        description="Distance multiplier at the last frame",
        default=1.0,
        min=0.05,
        soft_max=4.0,
    )
    camera_height_end: FloatProperty(
        name="Height End",
        description="Height factor at the last frame",
        default=0.35,
        soft_min=-3.0,
        soft_max=3.0,
    )
    camera_interpolation: EnumProperty(
        name="Interpolation",
        description="Interpolation of the camera keyframes",
        items=INTERPOLATION_ITEMS,
        default='SINE',
    )
    camera_easing: EnumProperty(
        name="Easing",
        description="Easing of the camera keyframes",
        items=EASING_ITEMS,
        default='EASE_IN_OUT',
    )
    camera_set_active: BoolProperty(
        name="Make Scene Camera",
        description="Set the generated camera as the active scene camera",
        default=True,
    )
    camera_mirror_on_assemble: BoolProperty(
        name="Mirror Camera On Assemble",
        description="Play the camera move backwards when building an Assemble animation, so it "
                    "continues where an Explode pass ended. Leave this off and the start framing is "
                    "always the first frame, whichever animation you build",
        default=False,
    )

    # -------------------------------------------------------------- snapshots
    snapshots: CollectionProperty(type=EAS_Snapshot)
    snapshot_index: IntProperty(name="Active Snapshot", default=0, min=0)

    # ------------------------------------------------------------------- misc
    last_build_mode: EnumProperty(
        name="Last Build",
        description="Which animation was built last, so Rebuild knows what to make again",
        items=[
            ('NONE', "Nothing Built", "No animation has been built yet"),
            ('EXPLODE', "Explode", "The last build was an explode animation"),
            ('ASSEMBLE', "Assemble", "The last build was an assemble animation"),
        ],
        default='NONE',
    )
    last_report: StringProperty(name="Last Report", default="")


CLASSES = (
    EAS_CameraPose,
    EAS_Snapshot,
    EAS_ObjectProperties,
    EAS_SceneProperties,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    Scene.eas = PointerProperty(type=EAS_SceneProperties)
    Object.eas = PointerProperty(type=EAS_ObjectProperties)


def unregister():
    del Object.eas
    del Scene.eas
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
