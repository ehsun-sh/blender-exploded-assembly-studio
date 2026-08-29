# Changelog

All notable changes to Exploded Assembly Studio are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [1.3.0]

### Added

- **Camera hold.** `Hold Start` and `Hold End` keep the camera still for a number of frames at each
  end of the shot, so the beginning of the assembly is not competing with a camera move. The parts
  keep the full frame range; only the camera waits.
- **Multiple camera viewpoints.** The From Viewport mode now takes any number of viewpoints instead
  of just a start and an end, managed in a list: add from the current view, update, reorder, remove,
  look through, or space evenly. Each viewpoint carries its own time, focal length and roll.
- **Per segment motion.** The move between two viewpoints can be `Linear` or `Arc`. An arc curves
  around the subject rather than cutting the chord, which a plain keyframe pair cannot do — it is
  baked as sampled keys, with the segment's easing folded into where each sample lands in time so
  the timing curve survives. Interpolation and easing are set per segment.
- **Roll** per viewpoint, tilting the camera around its own view axis.
- **Enclosure panels as a separate phase.** Objects can be marked as `Part` or `Enclosure`. Enclosure
  panels open along their own side — top, bottom, front, back, left, right — instead of following the
  global explode direction, and they move in their own phase: on Assemble the inner parts land first
  and the shell closes over them, on Explode the shell opens before the parts come out.
  `Detect Sides` works each panel's side out from where it sits, and any panel can be overridden by
  hand to enter from a different side. `Parts Share`, `Phase Gap` and `Shell Distance` control the
  split.

### Changed

- A scene saved with the old two-pose camera is migrated into the viewpoint list on first use, so
  existing files keep working.

## [1.2.0]

### Fixed

- **The camera played backwards when building an Assemble animation.** The captured start framing
  ended up on the last frame and the end framing on the first. Assemble is the natural choice for a
  product that builds itself — components landing on the board, shells closing over it — so this hit
  the main workflow. The start framing is now the first frame of whatever you build, in every camera
  mode. The same applied to Orbit mode, where Start Angle was silently swapped with the end of the
  orbit.

### Added

- **Mirror On Assemble** camera option, off by default. Turning it on restores the previous
  behaviour, which is useful if you render an Explode pass and an Assemble pass and stitch them
  together, since the camera then continues where the first pass ended.

## [1.1.0]

### Added

- **Frame Object camera mode.** Pick a reference object — normally the PCB — and the camera derives
  its distance from that object's bounding sphere, the focal length, the sensor size and the render
  aspect ratio. The computed distance and subject size are shown live in the panel, in the scene's
  own units.
- **From Viewport camera mode.** Capture the first and last camera framing straight from the 3D
  viewport, either from an ordinary user view or from inside the camera preview with
  *Lock Camera to View* enabled. Focal length is captured with each pose and can be animated across
  the shot. Poses are keyed on quaternion channels so the camera turns the short way between
  orientations.
- *Look through pose* buttons that send the viewport back to a captured framing for checking.
- *Use Active Object* button and a *Clear Captured Poses* action for the new camera modes.
- The **PCB Product** preset now also sets the camera to frame the active object, so the board
  defines both the explosion split plane and the framing.
- `examples/demo_scene.py`, a mock PCB product for trying the add-on without a model of your own.

### Fixed

- Camera framing measured the subject in the wrong place when built as part of an explode. Keyframes
  are written straight to object transforms, which leaves `matrix_world` stale until the depsgraph
  updates, and the parent-matrix derivation then resolved incorrectly. All framing is now measured
  before any keyframes are written, while the scene is still at the assembled pose and in sync.

### Changed

- Camera framing is resolved once by the calling operator rather than inside the rig builder, so
  there is a single, well-defined point where the scene has to be in a consistent state.

## [1.0.0]

Initial release, covering version 1.0 of the design specification plus several items pulled forward
from later milestones.

### Added

- Source selection from the current selection or from a collection.
- Assembly state saved per object as a local matrix, restored exactly on assemble.
- Explode and assemble animation generation with configurable frame range.
- Four explosion directions: From Center, Axis +/- (Split), World Axis, Local Axis.
- Three spacing modes: Uniform, Proportional, Layered — with layer clustering so parts at the same
  depth travel together instead of fanning into a staircase.
- Assembly centre from bounding box, median point, 3D cursor or the active object.
- Optional rotation during the explosion, around a world or local axis.
- Staggered sequencing with configurable order, overlap and mirrored assemble order.
- Per-part distance multiplier, manual order and exclusion.
- Orbiting camera rig with auto framing and an optional dolly.
- Three presets: PCB Product, Radial Technical, Product Showcase.
- Clear Animation, which removes the generated channels and restores the assembled model.
- Parent handling: children of a moving parent ride along rather than moving twice.
- Headless test suite.

### Notes

- The add-on never modifies meshes, materials, modifiers or origins — only transforms and keyframes.
- All operators are undo-compatible.
- Works across Blender 3.x to 5.x, including the slotted actions introduced in 4.4.
