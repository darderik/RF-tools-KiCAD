#!/usr/bin/env python
"""
Advanced test: simulates actual via fence generation pipeline.
Includes filtering logic similar to viafence_action.py
"""

import sys
import math
from bisect import bisect_left

# === EXTRACTED GEOMETRY FUNCTIONS ===

def getLineLength(line):
    return math.hypot(line[0][0]-line[1][0], line[0][1]-line[1][1])

def getLineSlope(line):
    return math.atan2(line[0][1]-line[1][1], line[0][0]-line[1][0])

def getPathCumDist(path):
    cumDist = [0.0]
    for vertexId in range(1, len(path)):
        cumDist.append(cumDist[-1] + getLineLength([path[vertexId], path[vertexId-1]]))
    return cumDist

class PathInterpolator:
    def __init__(self, cumDist, path):
        self.cumDist = cumDist
        self.path = path

    def __call__(self, distance):
        distance = max(0, min(distance, self.cumDist[-1]))
        idx = bisect_left(self.cumDist, distance)
        if idx >= len(self.cumDist):
            idx = len(self.cumDist) - 1
        if idx == 0:
            idx = 1

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

def distributeAlongPathWithShift(path, viaPitch, startShift=0):
    cumDist = getPathCumDist(path)
    interp = PathInterpolator(cumDist, path)
    
    vias = []
    totalDist = cumDist[-1]
    
    startDist = totalDist * 0.5 - (int((totalDist * 0.5) / viaPitch)) * viaPitch + startShift
    
    dist = startDist
    while dist <= totalDist:
        vias.append(interp(dist))
        dist += viaPitch
    
    return vias

def point_distance(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def dedupe_points(points, tol):
    """Remove duplicate points within tolerance."""
    unique = []
    for v in points:
        keep = True
        for u in unique:
            if point_distance(v, u) <= tol:
                keep = False
                break
        if keep:
            unique.append(v)
    return unique

# === SIMULATION FUNCTIONS ===

def create_simple_line(p1, p2, num_points=20):
    """Create a simple line segment."""
    points = []
    for i in range(num_points + 1):
        t = i / float(num_points)
        x = p1[0] + t * (p2[0] - p1[0])
        y = p1[1] + t * (p2[1] - p1[1])
        points.append([int(x), int(y)])
    return points

def create_simple_serpentine(width=10000, height=5000, num_lines=3, segments_per_line=30):
    """Create a simple serpentine (back-and-forth) trace for length tuning."""
    points_all = []
    x, y = 0, 0
    direction = 1  # 1 for right, -1 for left
    
    for line_idx in range(num_lines):
        # Horizontal segments
        x_end = x + direction * width
        seg = create_simple_line([x, y], [x_end, y], num_points=segments_per_line)
        if line_idx > 0:
            seg = seg[1:]  # Skip duplicate starting point
        points_all.extend(seg)
        x = x_end
        
        # Vertical connecting segment
        y_end = y + height
        seg = create_simple_line([x, y], [x, y_end], num_points=int(segments_per_line * height / width))
        seg = seg[1:]  # Skip duplicate
        points_all.extend(seg)
        y = y_end
        
        # Reverse direction for next line
        direction *= -1
    
    return points_all

def simulate_via_generation(path, via_offset, via_pitch, num_rows=1):
    """Simulate multi-row via generation without actual KiCad."""
    print("\n--- Via Generation Simulation ---")
    print("Path length: {:.0f} units".format(getPathCumDist(path)[-1]))
    print("Via offset: {} units, pitch: {} units, rows: {}".format(via_offset, via_pitch, num_rows))
    
    all_vias = []
    
    for row_idx in range(num_rows):
        # Each row offset by viaOffset
        current_offset = via_offset * (row_idx + 1)
        # Odd rows shift by half-pitch
        start_shift = 0 if (row_idx % 2 == 0) else via_pitch / 2.0
        
        # Generate vias for this row using the same path
        row_vias = distributeAlongPathWithShift(path, via_pitch, startShift=start_shift)
        
        print("\nRow {}: offset={}, shift={:.0f}, initial_vias={}".format(
            row_idx, current_offset, start_shift, len(row_vias)))
        print("  First 3 positions: {}".format([
            "[{:.0f}, {:.0f}]".format(v[0], v[1]) for v in row_vias[:3]]))
        
        # Track which vias are associated with which row (for debug)
        for via in row_vias:
            via_with_row = [via[0], via[1], row_idx]  # [x, y, row]
            all_vias.append(via_with_row)
    
    print("\nBefore deduplication: {} total vias".format(len(all_vias)))
    
    # De-duplicate (this might merge vias from different rows!)
    unique_vias = []
    seen = set()
    for v in all_vias:
        key = (int(v[0]), int(v[1]))
        if key not in seen:
            unique_vias.append(v)
            seen.add(key)
    
    print("After deduplication: {} vias".format(len(unique_vias)))
    
    # Show which vias survived
    vias_by_row = {i: 0 for i in range(num_rows)}
    for v in unique_vias:
        row = v[2]
        vias_by_row[row] += 1
    
    print("\nVias surviving per row:")
    for row in range(num_rows):
        print("  Row {}: {} vias".format(row, vias_by_row[row]))
    
    return [v[:2] for v in unique_vias]  # Return just [x, y]

def test_multirow_simple_line():
    """Test multi-row on simple line."""
    print("\n" + "="*70)
    print("TEST: Multi-Row on Simple Line")
    print("="*70)
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    via_offset = 500  # 0.5mm
    via_pitch = 1000  # 1mm
    
    # Test 1 row
    print("\n>>> TEST 1: Single row")
    vias_1 = simulate_via_generation(path, via_offset, via_pitch, num_rows=1)
    count_1 = len(vias_1)
    
    # Test 2 rows
    print("\n>>> TEST 2: Two rows (brick pattern)")
    vias_2 = simulate_via_generation(path, via_offset, via_pitch, num_rows=2)
    count_2 = len(vias_2)
    
    print("\n>>> ANALYSIS:")
    print("Single row: {} vias".format(count_1))
    print("Two rows: {} vias (expected ~{})".format(count_2, count_1 * 2))
    
    if count_2 >= count_1 * 1.5:
        print("✓ PASS: Second row vias mostly preserved")
    else:
        print("⚠ FAIL: Second row vias lost during deduplication!")
        print("   This suggests rows are overlapping or vias are too close")

def test_multirow_serpentine():
    """Test multi-row on serpentine trace (realistic length-tuning case)."""
    print("\n" + "="*70)
    print("TEST: Multi-Row on Serpentine Trace")
    print("="*70)
    
    # Create serpentine with 3 horizontal segments
    path = create_simple_serpentine(width=5000, height=1000, num_lines=3, segments_per_line=50)
    
    via_offset = 500
    via_pitch = 1000
    
    print("\n>>> TEST 1: Single row")
    vias_1 = simulate_via_generation(path, via_offset, via_pitch, num_rows=1)
    count_1 = len(vias_1)
    
    print("\n>>> TEST 2: Two rows")
    vias_2 = simulate_via_generation(path, via_offset, via_pitch, num_rows=2)
    count_2 = len(vias_2)
    
    print("\n>>> ANALYSIS:")
    print("Single row: {} vias".format(count_1))
    print("Two rows: {} vias (expected ~{})".format(count_2, count_1 * 2))
    
    if count_2 >= count_1 * 1.5:
        print("✓ PASS: Second row vias mostly preserved on serpentine")
    else:
        print("⚠ FAIL: Second row vias lost on serpentine!")

def test_offset_analysis():
    """Analyze whether the offset is being applied correctly."""
    print("\n" + "="*70)
    print("TEST: Offset Distance Analysis")
    print("="*70)
    
    path = create_simple_line([0, 0], [10000, 0], num_points=100)
    via_offset = 500
    via_pitch = 1000
    
    print("\nGenerating vias for rows 0 and 1...")
    print("Via offset: {} units (lateral distance from path)".format(via_offset))
    print("NOTE: This offset should move vias perpendicular to the path,")
    print("      NOT affect their longitudinal distribution!")
    
    # Row 0: offset by 500
    row0_vias = distributeAlongPathWithShift(path, via_pitch, startShift=0)
    
    # Row 1: offset by 1000, with half-pitch shift
    row1_vias = distributeAlongPathWithShift(path, via_pitch, startShift=500)
    
    print("\nRow 0 (offset=500, shift=0):")
    print("  Count: {}, First X-coords: {}".format(len(row0_vias), 
          [int(v[0]) for v in row0_vias[:5]]))
    
    print("\nRow 1 (offset=1000, shift=500):")
    print("  Count: {}, First X-coords: {}".format(len(row1_vias),
          [int(v[0]) for v in row1_vias[:5]]))
    
    print("\n⚠ NOTE: The generateViaFence() function receives 'viaOffset' as a parameter")
    print("  but this is used to EXPAND THE PATH, not to position individual vias!")
    print("  Individual vias are positioned along the offset path, not at offset position.")
    print("\n  The multi-row should:")
    print("  1. Row 0: Expand path by 500 units → place vias along expanded path")
    print("  2. Row 1: Expand path by 1000 units → place vias along expanded path")
    print("     (with half-pitch longitudinal shift for brick pattern)")

if __name__ == '__main__':
    print("=" * 70)
    print("ADVANCED VIA FENCE GENERATION TEST SUITE")
    print("=" * 70)
    
    try:
        test_offset_analysis()
        test_multirow_simple_line()
        test_multirow_serpentine()
        
        print("\n" + "="*70)
        print("✓ TESTS COMPLETED")
        print("="*70)
        
    except Exception as e:
        print("\n" + "="*70)
        print("✗ ERROR: {}".format(e))
        print("="*70)
        import traceback
        traceback.print_exc()
        sys.exit(1)
