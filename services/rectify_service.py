# SPDX-License-Identifier: GPL-3.0-or-later

import bmesh
import bpy
from bmesh.types import BMesh
from bpy.types import Object


def align_uv_rectify(
    obj: Object,
    bm: BMesh,
    uv_layer_name: str,
    keep_bounds: bool = False,
    target_faces=None,
):
    """
    Rectify selected quad islands with geometry-proportional UV spacing.

    Each connected island is seeded from one quad shaped after the average
    lengths of its opposite mesh edges, propagated with Blender's native
    'follow_active_quads' (LENGTH_AVERAGE) and fitted back with a uniform scale.

    NOTE: Only processes Quads. Triangles and N-gons are explicitly excluded
    to prevent UV layout distortion during normalization.
    """
    mesh_data = obj.data
    uv_layer = bm.loops.layers.uv.get(uv_layer_name)
    if uv_layer is None:
        print(f"Error: UV layer '{uv_layer_name}' not found.")
        return False

    if target_faces is None:
        target_faces = [f for f in bm.faces if f.select]
    target_faces = [f for f in target_faces if len(f.verts) == 4]

    if not target_faces:
        return False

    # Work with indices: follow_active_quads may rebuild the edit BMesh and
    # invalidate the BMFace references held here.
    bm.faces.index_update()
    islands = [[face.index for face in island] for island in _get_face_islands(target_faces)]
    original_active = bm.faces.active
    original_active_index = original_active.index if original_active is not None else None

    for island_indices in islands:
        bm = bmesh.from_edit_mesh(mesh_data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.get(uv_layer_name)
        island = [bm.faces[index] for index in island_indices]

        orig_bounds = _get_uv_bounds(island, uv_layer) if keep_bounds else None

        if original_active_index in island_indices:
            active_face = bm.faces[original_active_index]
        else:
            active_face = bm.faces[min(island_indices)]
        bm.faces.active = active_face

        _rectify_active_face(active_face, uv_layer)
        bmesh.update_edit_mesh(mesh_data)

        try:
            with bpy.context.temp_override(
                active_object=obj,
                object=obj,
                edit_object=obj,
                selected_objects=[obj],
                selected_editable_objects=[obj],
                objects_in_mode=[obj],
                objects_in_mode_unique_data=[obj],
            ):
                bpy.ops.uv.follow_active_quads(mode="LENGTH_AVERAGE")
        except RuntimeError:
            _restore_active_face(mesh_data, original_active_index)
            return False

        bm = bmesh.from_edit_mesh(mesh_data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.get(uv_layer_name)
        island = [bm.faces[index] for index in island_indices]
        current_bounds = _get_uv_bounds(island, uv_layer)
        if current_bounds:
            _apply_uv_remap(island, uv_layer, current_bounds, orig_bounds)

    _restore_active_face(mesh_data, original_active_index)
    return True


def _restore_active_face(mesh_data, face_index):
    bm = bmesh.from_edit_mesh(mesh_data)
    if face_index is not None:
        bm.faces.ensure_lookup_table()
        bm.faces.active = bm.faces[face_index]
    bmesh.update_edit_mesh(mesh_data, loop_triangles=False)


def _get_face_islands(faces):
    remaining = set(faces)
    islands = []

    while remaining:
        start = min(remaining, key=lambda face: face.index)
        remaining.remove(start)
        island = {start}
        stack = [start]

        while stack:
            face = stack.pop()
            for edge in face.edges:
                if not edge.is_manifold or edge.seam:
                    continue
                for linked_face in edge.link_faces:
                    if linked_face in remaining:
                        remaining.remove(linked_face)
                        island.add(linked_face)
                        stack.append(linked_face)

        islands.append(island)

    return islands


def _rectify_active_face(face, uv_layer):
    """
    Make the seed quad axis-aligned without changing its UV orientation,
    with the width/height ratio of the mesh quad's opposite edges.
    """
    loops = list(face.loops)
    coords = {loop: loop[uv_layer].uv.copy() for loop in loops}
    min_x = min(uv.x for uv in coords.values())
    max_x = max(uv.x for uv in coords.values())
    min_y = min(uv.y for uv in coords.values())
    max_y = max(uv.y for uv in coords.values())

    # Pairing by height mirrors TexTools' original Rectify behavior and keeps
    # the existing top/bottom and left/right orientation of the UV patch.
    by_height = sorted(loops, key=lambda loop: coords[loop].y, reverse=True)
    upper = sorted(by_height[:2], key=lambda loop: coords[loop].x)
    lower = sorted(by_height[2:], key=lambda loop: coords[loop].x)

    def dist(a, b):
        return (a.vert.co - b.vert.co).length

    width = (dist(upper[0], upper[1]) + dist(lower[0], lower[1])) * 0.5
    height = (dist(upper[0], lower[0]) + dist(upper[1], lower[1])) * 0.5
    if width <= 1e-12:
        width = 1.0
    if height <= 1e-12:
        height = 1.0

    size = max(max_x - min_x, max_y - min_y)
    if size <= 1e-12:
        size = 1.0
    scale = size / max(width, height)
    width *= scale
    height *= scale

    upper[0][uv_layer].uv = (min_x, min_y + height)
    upper[1][uv_layer].uv = (min_x + width, min_y + height)
    lower[0][uv_layer].uv = (min_x, min_y)
    lower[1][uv_layer].uv = (min_x + width, min_y)


def _get_uv_bounds(faces, uv_layer):
    min_x, max_x = float("inf"), float("-inf")
    min_y, max_y = float("inf"), float("-inf")
    has_verts = False
    for face in faces:
        for loop in face.loops:
            u, v = loop[uv_layer].uv
            if u < min_x:
                min_x = u
            if u > max_x:
                max_x = u
            if v < min_y:
                min_y = v
            if v > max_y:
                max_y = v
            has_verts = True
    return (min_x, max_x, min_y, max_y) if has_verts else None


def _apply_uv_remap(faces, uv_layer, src_bounds, dst_bounds=None):
    """Fit faces into dst_bounds (or the 0-1 square) with one uniform scale."""
    s_min_x, s_max_x, s_min_y, s_max_y = src_bounds
    width = s_max_x - s_min_x
    height = s_max_y - s_min_y
    if width <= 1e-12 or height <= 1e-12:
        return

    if dst_bounds:
        d_min_x, d_max_x, d_min_y, d_max_y = dst_bounds
        d_width = d_max_x - d_min_x
        d_height = d_max_y - d_min_y
        scales = []
        if d_width > 1e-12:
            scales.append(d_width / width)
        if d_height > 1e-12:
            scales.append(d_height / height)
        scale = min(scales) if scales else 1.0 / max(width, height)
        dst_center_x = (d_min_x + d_max_x) * 0.5
        dst_center_y = (d_min_y + d_max_y) * 0.5
    else:
        scale = 1.0 / max(width, height)
        dst_center_x = 0.5
        dst_center_y = 0.5

    src_center_x = (s_min_x + s_max_x) * 0.5
    src_center_y = (s_min_y + s_max_y) * 0.5
    for face in faces:
        for loop in face.loops:
            u, v = loop[uv_layer].uv
            loop[uv_layer].uv = (
                (u - src_center_x) * scale + dst_center_x,
                (v - src_center_y) * scale + dst_center_y,
            )
