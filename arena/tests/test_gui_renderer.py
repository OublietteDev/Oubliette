"""Tests for hex grid rendering utilities."""

import math

import pytest

from arena.gui.renderer import hex_vertices


class TestHexVertices:
    """Tests for flat-top hexagon vertex calculation."""

    def test_vertex_count(self):
        """hex_vertices returns exactly 6 vertices."""
        vertices = hex_vertices(0, 0, 40)
        assert len(vertices) == 6

    def test_vertices_at_correct_distance(self):
        """All vertices should be exactly 'size' distance from center."""
        cx, cy = 100.0, 200.0
        size = 40.0
        vertices = hex_vertices(cx, cy, size)
        for vx, vy in vertices:
            dist = math.sqrt((vx - cx) ** 2 + (vy - cy) ** 2)
            assert abs(dist - size) < 1e-10

    def test_flat_top_first_vertex_is_rightmost(self):
        """First vertex (angle=0) should be directly to the right of center."""
        cx, cy = 50.0, 50.0
        size = 30.0
        vertices = hex_vertices(cx, cy, size)
        vx, vy = vertices[0]
        # At angle 0, vertex is at (cx + size, cy)
        assert abs(vx - (cx + size)) < 1e-10
        assert abs(vy - cy) < 1e-10

    def test_top_edge_is_flat(self):
        """For flat-top hex, vertices at 60 and 300 degrees should share a y-value.

        Vertices 1 (60 deg) and 5 (300 deg) form one horizontal edge,
        and vertices 2 (120 deg) and 4 (240 deg) form the other.
        """
        vertices = hex_vertices(0, 0, 40)
        # Vertices 1 and 5 should have same y (upper-right and lower-right)
        assert abs(vertices[1][1] - (-vertices[5][1])) < 1e-10
        # Vertices 2 and 4 should have same y magnitude (upper-left and lower-left)
        assert abs(vertices[2][1] - (-vertices[4][1])) < 1e-10

    def test_vertex_symmetry_horizontal(self):
        """Hex should be symmetric about the horizontal axis through center."""
        cx, cy = 0, 0
        vertices = hex_vertices(cx, cy, 40)
        # vertex 0 (right) at y=0 is symmetric with itself
        assert abs(vertices[0][1] - cy) < 1e-10
        # vertex 3 (left) at y=0 is symmetric with itself
        assert abs(vertices[3][1] - cy) < 1e-10
        # vertex 1 and vertex 5 should be mirror images across x-axis
        assert abs(vertices[1][0] - vertices[5][0]) < 1e-10
        assert abs(vertices[1][1] + vertices[5][1]) < 1e-10

    def test_different_sizes(self):
        """Vertices should scale linearly with size."""
        v_small = hex_vertices(0, 0, 20)
        v_large = hex_vertices(0, 0, 40)
        for (sx, sy), (lx, ly) in zip(v_small, v_large):
            assert abs(lx - sx * 2) < 1e-10
            assert abs(ly - sy * 2) < 1e-10

    def test_different_centers(self):
        """Vertices should offset correctly with center position."""
        v_origin = hex_vertices(0, 0, 30)
        v_offset = hex_vertices(100, 200, 30)
        for (ox, oy), (fx, fy) in zip(v_origin, v_offset):
            assert abs(fx - (ox + 100)) < 1e-10
            assert abs(fy - (oy + 200)) < 1e-10
