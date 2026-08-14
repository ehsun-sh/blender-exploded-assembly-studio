# Changelog

All notable changes to Exploded Assembly Studio are documented here.
This project follows [Semantic Versioning](https://semver.org/).

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
