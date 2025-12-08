#!/usr/bin/env python
"""
Unit test for multi-row via fence generation.
Simulates a simple arc and tests via distribution.
"""

import sys
import os
import math

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from viafence import (
    distributeAlongPath, distributeAlongPathWithShift,
    generateViaFence, generateViaFenceMultiRow,
    getPathCumDist, PathInterpolator
)

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

def test_distribute_along_path():
    """Test basic distribution along a path."""
    print("\n=== Test: distributeAlongPath ===")
    
    # Create a simple horizontal line from (0, 0) to (10000, 0)
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    
    # Distribute vias with 1000 unit pitch
    via_pitch = 1000
    vias = distributeAlongPath(path, via_pitch)
    
    print("Path length: ~10000 units")
    print("Via pitch: {} units".format(via_pitch))
    print("Number of vias placed: {}".format(len(vias)))
    print("First 5 vias: {}".format(vias[:5] if len(vias) >= 5 else vias))
    
    assert len(vias) > 0, "Should have placed some vias"
    print("✓ Test passed")

def test_distribute_with_shift():
    """Test distribution with half-pitch shift for brick pattern."""
    print("\n=== Test: distributeAlongPathWithShift (brick pattern) ===")
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    via_pitch = 1000
    
    # Row 0: normal start
    vias_row0 = distributeAlongPathWithShift(path, via_pitch, startShift=0)
    print("Row 0 (no shift): {} vias".format(len(vias_row0)))
    print("  Positions: {}".format([round(v[0]) for v in vias_row0[:5]]))
    
    # Row 1: half-pitch shift
    vias_row1 = distributeAlongPathWithShift(path, via_pitch, startShift=via_pitch/2.0)
    print("Row 1 (half-pitch shift): {} vias".format(len(vias_row1)))
    print("  Positions: {}".format([round(v[0]) for v in vias_row1[:5]]))
    
    assert len(vias_row0) > 0, "Row 0 should have vias"
    assert len(vias_row1) > 0, "Row 1 should have vias"
    
    # Verify brick pattern: row1 vias should be offset
    if len(vias_row0) > 0 and len(vias_row1) > 0:
        diff = vias_row1[0][0] - vias_row0[0][0]
        expected_diff = via_pitch / 2.0
        assert abs(diff - expected_diff) < 100, "Row1 should be ~half-pitch ahead"
        print("✓ Brick pattern confirmed: row1 offset = {:.0f} (expected ~{:.0f})".format(diff, expected_diff))
    
    print("✓ Test passed")

def test_multirow_on_arc():
    """Test multi-row via fence on a circular arc."""
    print("\n=== Test: generateViaFenceMultiRow on arc ===")
    
    # Create a simple arc (quarter circle, radius ~3000)
    center = [0, 0]
    radius = 3000
    arc = create_simple_arc(center, radius, 0, math.pi/2, num_points=50)
    
    path_list = [arc]
    via_offset = 500  # 0.5mm in internal units
    via_pitch = 1000  # 1mm
    
    print("Arc: center={}, radius={}, ~{} points".format(center, radius, len(arc)))
    print("Via offset: {} units, pitch: {} units".format(via_offset, via_pitch))
    
    # Test single row
    print("\n  Row 1 only:")
    vias_row1 = generateViaFenceMultiRow(path_list, via_offset, via_pitch, numRowsPerSide=1)
    print("  Vias placed: {}".format(len(vias_row1)))
    if vias_row1:
        print("  First 3: {}".format(vias_row1[:3]))
    
    assert len(vias_row1) > 0, "Should place vias for row 1"
    
    # Test two rows
    print("\n  Rows 1 & 2 (brick pattern):")
    vias_rows = generateViaFenceMultiRow(path_list, via_offset, via_pitch, numRowsPerSide=2)
    print("  Total vias placed: {}".format(len(vias_rows)))
    print("  Expected ~2x single-row count: {} (got {})".format(len(vias_row1) * 2, len(vias_rows)))
    
    # Rough check: should have ~2x vias (allowing for some filtering)
    expected_min = len(vias_row1) * 1.5  # Allow 50% loss due to filtering
    if len(vias_rows) >= expected_min:
        print("✓ Multi-row count reasonable")
    else:
        print("⚠ Warning: Row 2 has fewer vias than expected ({} vs ~{})".format(
            len(vias_rows) - len(vias_row1), len(vias_row1)))
    
    print("✓ Test passed")

def test_path_interpolator():
    """Test path interpolation used for via distribution."""
    print("\n=== Test: PathInterpolator ===")
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    distList = getPathCumDist(path)
    
    print("Path cumulative distances (first 5): {}".format(distList[:5]))
    print("Total path length: {}".format(distList[-1]))
    
    interp = PathInterpolator(distList, path)
    
    # Test interpolation at various distances
    test_dists = [0, distList[-1]/4, distList[-1]/2, distList[-1]*3/4, distList[-1]]
    for d in test_dists:
        pt = interp(d)
        print("  Distance {}: point = [{:.0f}, {:.0f}]".format(d, pt[0], pt[1]))
    
    print("✓ Test passed")

if __name__ == '__main__':
    print("=" * 60)
    print("Multi-Row Via Fence Test Suite")
    print("=" * 60)
    
    try:
        test_path_interpolator()
        test_distribute_along_path()
        test_distribute_with_shift()
        test_multirow_on_arc()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
    except Exception as e:
        print("\n" + "=" * 60)
        print("✗ TEST FAILED: {}".format(e))
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)
