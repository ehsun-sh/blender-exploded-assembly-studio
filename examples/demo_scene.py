"""Build a mock PCB product to try Exploded Assembly Studio on.

    blender --python examples/demo_scene.py

Creates a PRODUCT_ASSEMBLY collection holding a bottom shell, a board, four
components, a connector, a top shell and four screws, all sitting where they
belong in the finished product. The parts are left selected with the PCB
active, so you can go straight to:

    N panel -> Exploded -> Presets -> PCB Product
             -> Set Assembly Position
             -> ASSEMBLE

Dimensions are in metres, so the board is a realistic 100 x 60 mm.
"""

import bpy

COLLECTION_NAME = "PRODUCT_ASSEMBLY"

# name, (size x, y, z), (location x, y, z)
PARTS = [
    ("Bottom_Case", (0.120, 0.080, 0.020), (0.000, 0.000, -0.012)),
    ("PCB", (0.100, 0.060, 0.0016), (0.000, 0.000, 0.000)),
    ("Component_1", (0.012, 0.010, 0.004), (-0.030, 0.015, 0.0028)),
    ("Component_2", (0.012, 0.010, 0.004), (0.020, 0.020, 0.0028)),
    ("Component_3", (0.012, 0.010, 0.004), (0.030, -0.015, 0.0028)),
    ("Component_4", (0.012, 0.010, 0.004), (-0.020, -0.020, 0.0028)),
    ("Connector", (0.020, 0.012, 0.006), (0.040, 0.000, 0.0038)),
    ("Top_Case", (0.120, 0.080, 0.018), (0.000, 0.000, 0.014)),
    ("Screw_1", (0.004, 0.004, 0.006), (-0.050, 0.030, 0.024)),
    ("Screw_2", (0.004, 0.004, 0.006), (0.050, 0.030, 0.024)),
    ("Screw_3", (0.004, 0.004, 0.006), (0.050, -0.030, 0.024)),
    ("Screw_4", (0.004, 0.004, 0.006), (-0.050, -0.030, 0.024)),
]


def clear_default_cube():
    cube = bpy.data.objects.get("Cube")
    if cube is not None and cube.type == 'MESH':
        bpy.data.objects.remove(cube, do_unlink=True)


def get_collection(scene):
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
        scene.collection.children.link(collection)
    return collection


def add_box(name, size, location, collection):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    for other in list(obj.users_collection):
        other.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def main():
    scene = bpy.context.scene
    clear_default_cube()
    collection = get_collection(scene)

    created = {}
    for name, size, location in PARTS:
        created[name] = add_box(name, size, location, collection)

    # Scale the viewport clipping to a 12 cm product so it is actually visible.
    for area in getattr(bpy.context.screen, "areas", []):
        if area.type == 'VIEW_3D':
            space = area.spaces.active
            space.clip_start = 0.001
            space.clip_end = 100.0

    bpy.ops.object.select_all(action='DESELECT')
    for obj in created.values():
        obj.select_set(True)
    # The PCB is active: it defines both the split plane and the camera framing.
    bpy.context.view_layer.objects.active = created["PCB"]

    props = getattr(scene, "eas", None)
    if props is not None:
        props.source = 'COLLECTION'
        props.collection = collection
        print("Exploded Assembly Studio found: source set to the demo collection.")
    else:
        print("Enable the Exploded Assembly Studio add-on, then use the Exploded tab.")

    print(f"Built {len(created)} parts in '{COLLECTION_NAME}'. PCB is the active object.")


if __name__ == "__main__":
    main()
