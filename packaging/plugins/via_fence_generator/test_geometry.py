#!/usr/bin/env python
"""
Standalone unit test for via fence geometry.
Extracted geometry functions to work without wx/pcbnew.
"""

import sys
import math
from bisect import bisect_left

# === EXTRACTED GEOMETRY FUNCTIONS (from viafence.py) ===

def getLineLength(line):
    """Returns the length of a line."""
    return math.hypot(line[0][0]-line[1][0], line[0][1]-line[1][1])

def getLineSlope(line):
    """Returns the slope of a line."""
    return math.atan2(line[0][1]-line[1][1], line[0][0]-line[1][0])

def getPathCumDist(path):
    """Return cumulative distance vector along path."""
    cumDist = [0.0]
    for vertexId in range(1, len(path)):
        cumDist.append(cumDist[-1] + getLineLength([path[vertexId], path[vertexId-1]]))
    return cumDist

class PathInterpolator:
    """Interpolates a point on a path at a given cumulative distance."""
    def __init__(self, cumDist, path):
        self.cumDist = cumDist
        self.path = path

    def __call__(self, distance):
        """Return interpolated point at given distance along path."""
        # Clamp to path bounds
        distance = max(0, min(distance, self.cumDist[-1]))
        
        # Find the segment containing this distance
        idx = bisect_left(self.cumDist, distance)
        if idx >= len(self.cumDist):
            idx = len(self.cumDist) - 1
        if idx == 0:
            idx = 1

        # Interpolate within segment
        segStart = self.cumDist[idx - 1]
        segEnd = self.cumDist[idx]
        
        if segEnd == segStart:
            return self.path[idx - 1]
        
        t = (distance - segStart) / (segEnd - segStart)
        t = max(0, min(1, t))
        
        p0 = self.path[idx - 1]
        p1 = self.path[idx]
        
        return [p0[0] + t * (p1[0] - p0[0]),
                p0[1] + t * (p1[1] - p0[1])]

def distributeAlongPath(path, viaPitch):
    """Distribute vias uniformly along path with given pitch."""
    cumDist = getPathCumDist(path)
    interp = PathInterpolator(cumDist, path)
    
    vias = []
    totalDist = cumDist[-1]
    
    # Start from middle of path
    startDist = totalDist * 0.5 - (int((totalDist * 0.5) / viaPitch)) * viaPitch
    
    dist = startDist
    while dist <= totalDist:
        vias.append(interp(dist))
        dist += viaPitch
    
    return vias

def distributeAlongPathWithShift(path, viaPitch, startShift=0):
    """Distribute vias with optional start shift (for brick pattern)."""
    cumDist = getPathCumDist(path)
    interp = PathInterpolator(cumDist, path)
    
    vias = []
    totalDist = cumDist[-1]
    
    # Start from middle of path, with optional shift
    startDist = totalDist * 0.5 - (int((totalDist * 0.5) / viaPitch)) * viaPitch + startShift
    
    dist = startDist
    while dist <= totalDist:
        vias.append(interp(dist))
        dist += viaPitch
    
    return vias

def calculate_adaptive_segments(radius, angle_rad, max_deviation=0.1):
    """
    Calculate adaptive number of segments for an arc based on sagitta formula.
    Ensures max deviation <= max_deviation (in mm, at 1000 units/mm).
    """
    if radius <= 0 or angle_rad <= 0:
        return 2
    
    # Sagitta formula: s = r * (1 - cos(angle/2))
    # We want: s <= max_deviation
    # Solve for angle: angle = 2 * acos(1 - s/r)
    
    max_angle_rad = 2 * math.acos(max(0, 1 - max_deviation / radius))
    if max_angle_rad <= 0:
        return 2
    
    num_segments = max(2, int(math.ceil(angle_rad / max_angle_rad)))
    return num_segments

# === TEST FUNCTIONS ===

def create_simple_arc(center, radius, start_angle, end_angle, num_points=50):
    """Create a simple circular arc as a list of [x, y] points."""
    points = []
    for i in range(num_points + 1):
        t = i / float(num_points)
        angle = start_angle + t * (end_angle - start_angle)
        x = center[0] + radius * math.cos(angle)
        y = center[1] + radius * math.sin(angle)
        points.append([int(x), int(y)])
    return points

def create_simple_line(p1, p2, num_points=20):
    """Create a simple line segment as a list of [x, y] points."""
    points = []
    for i in range(num_points + 1):
        t = i / float(num_points)
        x = p1[0] + t * (p2[0] - p1[0])
        y = p1[1] + t * (p2[1] - p1[1])
        points.append([int(x), int(y)])
    return points

def test_path_cumulative_dist():
    """Test cumulative distance calculation."""
    print("\n=== Test: Path Cumulative Distance ===")
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    cumDist = getPathCumDist(path)
    
    print("Horizontal line from (0,0) to (10000,0)")
    print("Path length: {:.0f} units".format(cumDist[-1]))
    print("Expected: ~10000 units")
    
    assert abs(cumDist[-1] - 10000) < 100, "Path length should be ~10000"
    print("✓ Test passed")

def test_path_interpolator_basic():
    """Test path interpolation."""
    print("\n=== Test: Path Interpolator ===")
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    cumDist = getPathCumDist(path)
    interp = PathInterpolator(cumDist, path)
    
    # Test at start, middle, end
    pt_start = interp(0)
    pt_mid = interp(cumDist[-1] / 2.0)
    pt_end = interp(cumDist[-1])
    
    print("Start: [{:.0f}, {:.0f}] (expected [0, 0])".format(pt_start[0], pt_start[1]))
    print("Mid:   [{:.0f}, {:.0f}] (expected [5000, 0])".format(pt_mid[0], pt_mid[1]))
    print("End:   [{:.0f}, {:.0f}] (expected [10000, 0])".format(pt_end[0], pt_end[1]))
    
    assert abs(pt_start[0]) < 100 and abs(pt_start[1]) < 100, "Start should be near origin"
    assert abs(pt_mid[0] - 5000) < 100, "Mid should be at 5000"
    assert abs(pt_end[0] - 10000) < 100, "End should be at 10000"
    
    print("✓ Test passed")

def test_distribute_on_line():
    """Test via distribution on a straight line."""
    print("\n=== Test: Via Distribution on Line ===")
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    via_pitch = 1000
    
    vias = distributeAlongPath(path, via_pitch)
    
    print("Line: (0,0) to (10000,0)")
    print("Via pitch: {} units".format(via_pitch))
    print("Vias placed: {}".format(len(vias)))
    print("First 5 X-coordinates: {}".format([int(v[0]) for v in vias[:5]]))
    
    assert len(vias) >= 8, "Should place at least 8 vias on 10000-unit line with 1000 pitch"
    
    # Check spacing
    for i in range(1, min(5, len(vias))):
        dist = abs(vias[i][0] - vias[i-1][0])
        assert abs(dist - via_pitch) < 50, "Via spacing should be ~{} units".format(via_pitch)
    
    print("✓ Test passed")

def test_brick_pattern_shift():
    """Test brick pattern with half-pitch shift."""
    print("\n=== Test: Brick Pattern (Half-Pitch Shift) ===")
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    via_pitch = 1000
    
    vias_row0 = distributeAlongPathWithShift(path, via_pitch, startShift=0)
    vias_row1 = distributeAlongPathWithShift(path, via_pitch, startShift=via_pitch/2.0)
    
    print("Row 0 (no shift): {} vias".format(len(vias_row0)))
    print("  X-coords: {}".format([int(v[0]) for v in vias_row0[:5]]))
    
    print("Row 1 (half-pitch shift): {} vias".format(len(vias_row1)))
    print("  X-coords: {}".format([int(v[0]) for v in vias_row1[:5]]))
    
    # Row 1 should be offset by ~500 (half pitch)
    if len(vias_row0) > 0 and len(vias_row1) > 0:
        offset = vias_row1[0][0] - vias_row0[0][0]
        expected = via_pitch / 2.0
        print("Actual offset: {:.0f}, Expected: {:.0f}".format(offset, expected))
        assert abs(offset - expected) < 100, "Row1 should be ~half-pitch ahead"
    
    print("✓ Test passed")

def test_adaptive_segments():
    """Test adaptive arc segmentation."""
    print("\n=== Test: Adaptive Arc Segmentation ===")
    
    test_cases = [
        (1000, math.pi/4, "Quarter circle, radius 1000"),
        (5000, math.pi/2, "Half circle, radius 5000"),
        (100, math.pi, "Full circle, radius 100 (tight curve)"),
        (10000, math.pi/12, "Small angle arc, radius 10000"),
    ]
    
    for radius, angle, desc in test_cases:
        segs = calculate_adaptive_segments(radius, angle, max_deviation=0.1)
        print("  {}: {} segments".format(desc, segs))
        assert segs >= 2, "Should have at least 2 segments"
    
    print("✓ Test passed")

def test_distribute_on_arc():
    """Test via distribution on a circular arc."""
    print("\n=== Test: Via Distribution on Arc ===")
    
    # Create quarter circle arc
    arc = create_simple_arc([0, 0], 3000, 0, math.pi/2, num_points=50)
    via_pitch = 1000
    
    vias = distributeAlongPath(arc, via_pitch)
    
    cumDist = getPathCumDist(arc)
    arc_length = cumDist[-1]
    
    print("Quarter circle: radius=3000, length={:.0f}".format(arc_length))
    print("Via pitch: {} units".format(via_pitch))
    print("Vias placed: {}".format(len(vias)))
    print("First 3 vias:")
    for i, v in enumerate(vias[:3]):
        print("  [{}] ({:.0f}, {:.0f})".format(i, v[0], v[1]))
    
    assert len(vias) > 0, "Should place at least 1 via on arc"
    
    print("✓ Test passed")

def test_distribute_row_count():
    """Test that distributing multiple rows maintains reasonable counts."""
    print("\n=== Test: Multi-Row Distribution Count ===")
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    via_pitch = 1000
    
    vias_row0 = distributeAlongPathWithShift(path, via_pitch, startShift=0)
    vias_row1 = distributeAlongPathWithShift(path, via_pitch, startShift=via_pitch/2.0)
    vias_row2 = distributeAlongPathWithShift(path, via_pitch, startShift=0)  # Same as row 0
    
    print("Row 0: {} vias".format(len(vias_row0)))
    print("Row 1: {} vias".format(len(vias_row1)))
    print("Row 2: {} vias".format(len(vias_row2)))
    print("Total: {} vias (should be ~{})".format(
        len(vias_row0) + len(vias_row1) + len(vias_row2),
        len(vias_row0) * 3))
    
    # All rows should have similar counts
    min_count = min(len(vias_row0), len(vias_row1), len(vias_row2))
    max_count = max(len(vias_row0), len(vias_row1), len(vias_row2))
    
    assert max_count - min_count <= 1, "All rows should have similar via counts"
    print("✓ Test passed")

if __name__ == '__main__':
    print("=" * 70)
    print("STANDALONE VIA FENCE GEOMETRY TEST SUITE")
    print("=" * 70)
    
    try:
        test_path_cumulative_dist()
        test_path_interpolator_basic()
        test_distribute_on_line()
        test_brick_pattern_shift()
        test_adaptive_segments()
        test_distribute_on_arc()
        test_distribute_row_count()
        
        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        
    except AssertionError as e:
        print("\n" + "=" * 70)
        print("✗ TEST FAILED: {}".format(e))
        print("=" * 70)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print("\n" + "=" * 70)
        print("✗ ERROR: {}".format(e))
        print("=" * 70)
        import traceback
        traceback.print_exc()
        sys.exit(1)
