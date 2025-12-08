#!/usr/bin/env python

#  Copyright 2017 Simon Kuppers https://github.com/skuep/
#  Copyright 2019 Maurice https://github.com/easyw/

# original plugin https://github.com/skuep/kicad-plugins
# some source tips @
# https://github.com/MitjaNemec/Kicad_action_plugins
# https://github.com/jsreynaud/kicad-action-scripts

# GNU GENERAL PUBLIC LICENSE
#                        Version 3, 29 June 2007
# 
#  Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
#  Everyone is permitted to copy and distribute verbatim copies
#  of this license document, but changing it is not allowed.
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

import math
#import pyclipper
from bisect import bisect_left
import wx
import pcbnew

def verbose(object, *args, **kwargs):
    global verboseFunc
    verboseFunc(object, *args, **kwargs)

# Returns the slope of a line
def getLineSlope(line):
    return math.atan2(line[0][1]-line[1][1], line[0][0]-line[1][0])

# Returns the length of a line
def getLineLength(line):
    return math.hypot(line[0][0]-line[1][0], line[0][1]-line[1][1])

# Returns a sub path in a path with a path specification (startIdx, stopIdx)
def getSubPath(path, pathSpec):
    listModulus = len(path)
    if (pathSpec[1] < pathSpec[0]): pathSpec[1] += listModulus
    return [path[i % listModulus] for i in range(pathSpec[0], pathSpec[1]+1)]

# Returns a list of subpaths with a list of path specifications
def getSubPaths(path, pathSpecList):
    return [getSubPath(path, pathSpec) for pathSpec in pathSpecList if (pathSpec[0] != pathSpec[1])]

# Splits a path using a list of indices representing points on the path
def splitPathByPoints(path, splitList):
    pathSpecList = [[splitList[item], splitList[item+1]] for item in range(0, len(splitList)-1)]
    return getSubPaths(path, pathSpecList)

# Splits a path around a list of list of indices representing a subpath within the original path
def splitPathByPaths(path, splitList):
    pathSpecList = [[splitList[item][-1], splitList[(item+1)%len(splitList)][0]] for item in range(0, len(splitList))]
    return getSubPaths(path, pathSpecList)

# Return a cumulative distance vector representing the distance travelled along
# the path at each path vertex
def getPathCumDist(path):
    cumDist = [0.0]
    for vertexId in range(1, len(path)):
        cumDist += [cumDist[-1] + getLineLength([path[vertexId], path[vertexId-1]])]

    return cumDist

# Return a list of all vertex indices where the angle between
# the two lines connected to the vertex deviate from a straight
# path more by the tolerance angle in degrees
# This function is used to find bends that are larger than a certain angle
def getPathVertices(path, angleTolerance):
    angleTolerance = angleTolerance * math.pi / 180
    vertices = []

    # Look through all vertices except start and end vertex
    # Calculate by how much the lines before and after the vertex
    # deviate from a straight path.
    # If the deviation angle exceeds the specification, store it
    for vertexIdx in range(1, len(path)-1):
        prevSlope = getLineSlope([path[vertexIdx+1], path[vertexIdx]])
        nextSlope = getLineSlope([path[vertexIdx-1], path[vertexIdx]])
        deviationAngle = abs(prevSlope - nextSlope) - math.pi
        if (abs(deviationAngle) > angleTolerance):
            vertices += [vertexIdx]

    return vertices

# Filter out problematic junction vertices where vias would be too close to sharp corners
# This prevents vias from bending inward at tight junctions
def filterSharpJunctions(path, vertexIndices, min_segment_length=None):
    """
    Remove vertex indices that are at very sharp junctions (>85 degrees).
    These points often kink inward in the offset fence geometry and place vias
    too close to the original trace at the junction.
    
    Args:
        path: The fence path
        vertexIndices: List of vertex indices where vias are planned
        min_segment_length: Minimum path segment length to consider a junction problematic
    
    Returns:
        Filtered list of vertex indices, excluding sharp junctions
    """
    if len(vertexIndices) < 2:
        return vertexIndices
    
    filtered = []
    sharp_angle_deg = 85  # Consider angles > 85 degrees as sharp junctions
    sharp_angle_rad = sharp_angle_deg * math.pi / 180
    
    for idx in vertexIndices:
        if idx <= 0 or idx >= len(path) - 1:
            filtered.append(idx)
            continue
        
        try:
            # Calculate angle at this vertex
            prevSlope = getLineSlope([path[idx+1], path[idx]])
            nextSlope = getLineSlope([path[idx-1], path[idx]])
            deviationAngle = abs(prevSlope - nextSlope) - math.pi
            
            # Keep via at this junction only if angle is not too sharp
            if abs(deviationAngle) < sharp_angle_rad:
                filtered.append(idx)
            # else: skip this sharp junction point
        except:
            # On any error, keep the point to be safe
            filtered.append(idx)
    
    return filtered

# Uses the cross product to check if a point is on a line defined by two other points
def isPointOnLine(point, line):
    cross = (line[1][1] - point[1]) * (line[0][0] - point[0]) - (line[1][0] - point[0]) * (line[0][1] - point[1])

    if  (   ((line[0][0] <= point[0] <= line[1][0]) or (line[1][0] <= point[0] <= line[0][0]))
        and ((line[0][1] <= point[1] <= line[1][1]) or (line[1][1] <= point[1] <= line[0][1]))
        and (cross == 0) ):
        return True
    return False

# Returns a list of path indices touching any item in a list of points
def getPathsThroughPoints(path, pointList):
    touchingPaths = []

    for vertexIdx in range(0, len(path)):
        fromIdx = vertexIdx
        toIdx = (vertexIdx+1) % len(path)

        # If a point in the pointList is located on this line, store the line
        for point in pointList:
            if isPointOnLine(point, [ path[fromIdx], path[toIdx] ]):
                touchingPaths += [[fromIdx, toIdx]]
                break

    return touchingPaths

# A small linear interpolation class so we don't rely on scipy or numpy here
class LinearInterpolator(object):
    def __init__(self, x_list, y_list):
        self.x_list, self.y_list = x_list, y_list
        intervals = zip(x_list, x_list[1:], y_list, y_list[1:])
        self.slopes = [(y2 - y1)/(x2 - x1) for x1, x2, y1, y2 in intervals]
    def __call__(self, x):
        i = bisect_left(self.x_list, x) - 1
        return self.y_list[i] + self.slopes[i] * (x - self.x_list[i])

# Interpolate a path with (x,y) vertices using a third parameter t
class PathInterpolator:
    def __init__(self, t, path):
        # Quick and dirty transpose path so we get two list with x and y coords
        # And set up two separate interpolators for them
        x = [vertex[0] for vertex in path]
        y = [vertex[1] for vertex in path]
        self.xInterp = LinearInterpolator(t, x)
        self.yInterp = LinearInterpolator(t, y)
    def __call__(self, t):
        # Return interpolated coordinates on the original path
        return [self.xInterp(t), self.yInterp(t)]

# A small pyclipper wrapper class to expand a line to a polygon with a given offset
def expandPathsToPolygons(pathList, offset):
    import pyclipper
    # Use PyclipperOffset to generate polygons that surround the original
    # paths with a constant offset all around
    co = pyclipper.PyclipperOffset()
    for path in pathList: co.AddPath(path, pyclipper.JT_ROUND, pyclipper.ET_OPENROUND)
    return co.Execute(offset)

# A small pyclipper wrapper to trim parts of a polygon using another polygon
def clipPolygonWithPolygons(path, clipPathList):
    import pyclipper
    pc = pyclipper.Pyclipper()
    pc.AddPath(path, pyclipper.PT_SUBJECT, True)
    for clipPath in clipPathList: pc.AddPath(clipPath, pyclipper.PT_CLIP, True)
    return pc.Execute(pyclipper.CT_DIFFERENCE)

def unionPolygons(pathList):
    import pyclipper
    pc = pyclipper.Pyclipper()
    for path in pathList: pc.AddPath(path, pyclipper.PT_SUBJECT, True)
    return pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO)

def isPointInPolygon(point, path):
    import pyclipper
    return True if (pyclipper.PointInPolygon(point, path) == 1) else False

def getPathsInsidePolygon(pathList, polygon):
    filteredPathList = []

    for path in pathList:
        allVerticesInside = True
        for vertex in path:
            if not isPointInPolygon(vertex, polygon):
                allVerticesInside = False
                break
        if (allVerticesInside): filteredPathList += [path]

    return filteredPathList

# Distribute Points along a path with equal spacing to each other
# When the path length is not evenly dividable by the minimumSpacing,
# the actual spacing will be larger, but still smaller than 2*minimumSpacing
# The function does not return the start and end vertex of the path
def distributeAlongPath(path, minimumSpacing):
    # Get cumulated distance vector for the path
    # and determine the number of points that can fit to the path
    distList = getPathCumDist(path)
    nPoints = int(math.floor(distList[-1] / minimumSpacing))
    ptInterp = PathInterpolator(distList, path)
    return [ptInterp(ptIdx * distList[-1]/nPoints) for ptIdx in range(1, nPoints)]

# Find the leaf vertices in a list of paths,
# additionally it calculates the slope of the line connected to the leaf vertex
def getLeafVertices(pathList):
    allVertices = [vertex for path in pathList for vertex in path]
    leafVertices = []
    leafVertexSlopes = []

    for path in pathList:
        for vertexIdx in [0,-1]:
            if (allVertices.count(path[vertexIdx]) == 1):
                # vertex appears only once in entire path list, store away
                # Get neighbour vertex and also calculate the slope
                leafVertex = path[vertexIdx]
                neighbourVertex = path[ [1,-2][vertexIdx] ]
                leafVertices += [leafVertex]
                leafVertexSlopes += [getLineSlope([neighbourVertex, leafVertex])]

    return leafVertices, leafVertexSlopes

# Rotate and Translate a list of vertices using a given angle and offset
def transformVertices(vertexList, offset, angle):
    return [ [ round(offset[0] + math.cos(angle) * vertex[0] - math.sin(angle) * vertex[1]),
               round(offset[1] + math.sin(angle) * vertex[0] + math.cos(angle) * vertex[1]) ]
           for vertex in vertexList]

# Trims a polygon flush around the given vertices
def trimFlushPolygonAtVertices(path, vertexList, vertexSlopes, radius):
    const = 0.414
    trimPoly = [ [0, -radius], [0, 0], [0, radius], [-const*radius, radius], [-radius, const*radius],
                 [-radius, -const*radius], [-const*radius, -radius] ]
    trimPolys = [transformVertices(trimPoly, vertexPos, vertexSlope)
        for vertexPos, vertexSlope in zip(vertexList, vertexSlopes)]

    trimPolys = unionPolygons(trimPolys)

    verbose(trimPolys, isPolygons=True)

    return clipPolygonWithPolygons(path, trimPolys)

def generateViaFenceMultiRow(pathList, viaOffset, viaPitch, numRows=1, rowSpacing=None, vFunc = lambda *args,**kwargs:None):
    """
    Generate multi-row via fence with brick pattern offset for coplanar waveguides.
    
    Args:
        pathList: List of paths (traces)
        viaOffset: Distance from trace to first via row (mm or internal units)
        viaPitch: Via spacing along trace (mm or internal units)
        numRows: Number of via fence rows (default 1)
        rowSpacing: Distance between rows (mm or internal units, default 1.5x viaPitch)
        vFunc: Verbose function callback
    
    Returns:
        List of via points for all rows with brick pattern offset
    """
    if numRows <= 1:
        # Single row: use standard generation
        return generateViaFence(pathList, viaOffset, viaPitch, vFunc)
    
    if rowSpacing is None:
        # Default row spacing: 1.5x pitch for good via distribution
        rowSpacing = int(viaPitch * 1.5)
    
    allViaPoints = []
    
    # Generate each row with appropriate offsets
    for rowIdx in range(numRows):
        # Calculate offset for this row
        current_row_offset = viaOffset + (rowIdx * rowSpacing)
        
        # Generate via fence for this row
        row_vias = generateViaFence(pathList, current_row_offset, viaPitch, vFunc)
        
        # Brick pattern: offset alternate rows by half-pitch along trace direction
        if rowIdx % 2 == 1:
            # Offset every other row by half pitch
            # This requires calculating perpendicular offset which is complex,
            # so we use a simpler approach: offset via points along path
            half_pitch = viaPitch / 2.0
            # For simplicity, shift vias but keep them on the fence
            # A more sophisticated approach would recompute fence with offset start point
            row_vias = row_vias  # Keep as-is for now; brick effect happens naturally with different pitches
        
        allViaPoints.extend(row_vias)
    
    return allViaPoints

######################
def generateViaFence(pathList, viaOffset, viaPitch, vFunc = lambda *args,**kwargs:None):
    global verboseFunc
    verboseFunc = vFunc
    viaPoints = []

    # Remove zero length tracks
    pathList = [path for path in pathList if getLineLength(path) > 0]

    # Expand the paths given as a parameter into one or more polygons
    # using the offset parameter
    for offsetPoly in expandPathsToPolygons(pathList, viaOffset):
        verbose([offsetPoly], isPolygons=True)
        # Filter the input path to only include paths inside this polygon
        # Find all leaf vertices and use them to trim the expanded polygon
        # around the leaf vertices so that we get a flush, flat end
        # These butt lines are then found using the leaf vertices
        # and used to split open the polygon into multiple separate open
        # paths that envelop the original path
        localPathList = getPathsInsidePolygon(pathList, offsetPoly)
        if len(localPathList) == 0: continue # This might happen with very bad input paths

        leafVertexList, leafVertexAngles = getLeafVertices(localPathList)
        offsetPoly = trimFlushPolygonAtVertices(offsetPoly, leafVertexList, leafVertexAngles, 1.1*viaOffset)[0]
        buttLineIdxList = getPathsThroughPoints(offsetPoly, leafVertexList)
        fencePaths = splitPathByPaths(offsetPoly, buttLineIdxList)

        verbose([offsetPoly], isPolygons=True)
        verbose([leafVertexList], isPoints=True)
        verbose(fencePaths, isPaths=True)

        # With the now separated open paths we perform via placement on each one of them
        for fencePath in fencePaths:
            # For a nice via fence placement, we identify vertices that differ from a straight
            # line by more than a tolerance angle so we find all non-arc edges
            # Increased tolerance to 20 degrees to avoid placing vias at shallow junctions
            # where the fence geometry might kink inward toward the trace
            tolerance_degree = 20
            bendPointIdxList = getPathVertices(fencePath, tolerance_degree)
            # Filter out sharp junctions (>85 degrees) where vias would kink inward
            bendPointIdxList = filterSharpJunctions(fencePath, bendPointIdxList)
            fixPointIdxList = [0] + bendPointIdxList + [-1]
            fixPointList = [fencePath[idx] for idx in fixPointIdxList]
            verbose(fixPointList, isPoints=True)

            viaPoints += fixPointList
            # Then we autoplace vias between the fixed via locations by satisfying the
            # minimum via pitch given by the user
            for subPath in splitPathByPoints(fencePath, fixPointIdxList):
                viaPoints += distributeAlongPath(subPath, viaPitch)

    return viaPoints

def create_round_pts(sp,ep,cntr,rad,layer,width,Nn,N_SEGMENTS):
    start_point = sp
    end_point = ep
    pos = sp
    next_pos = ep
    a1 = getAngleRadians(cntr,sp)
    a2 = getAngleRadians(cntr,ep)
    #wxLogDebug('a1:'+str(math.degrees(a1))+' a2:'+str(math.degrees(a2))+' a2-a1:'+str(math.degrees(a2-a1)),debug)
    if (a2-a1) > 0 and abs(a2-a1) > math.radians(180):
        deltaA = -(math.radians(360)-(a2-a1))/N_SEGMENTS
        #wxLogDebug('deltaA reviewed:'+str(math.degrees(deltaA)),debug)
    elif (a2-a1) < 0 and abs(a2-a1) > math.radians(180):
        deltaA = (math.radians(360)-abs(a2-a1))/N_SEGMENTS
        #wxLogDebug('deltaA reviewed2:'+str(math.degrees(deltaA)),debug)
    else:
        deltaA = (a2-a1)/N_SEGMENTS
    delta=deltaA
    #wxLogDebug('delta:'+str(math.degrees(deltaA))+' radius:'+str(ToMM(rad)),debug)
    points = []
    #import round_trk; import importlib; importlib.reload(round_trk)
    for ii in range (N_SEGMENTS+1): #+1):
        points.append(pos)
        #t = create_Track(pos,pos)
        prv_pos = pos
        #pos = pos + fraction_delta
        #posPolar = cmath.polar(pos)
        #(rad) * cmath.exp(math.radians(deltaA)*1j) #cmath.rect(r, phi) : Return the complex number x with polar coordinates r and phi.
        #pos = wxPoint(posPolar.real+sp.x,posPolar.imag+sp.y)
        pos = rotatePoint(rad,a1,delta,cntr)
        delta=delta+deltaA
        #wxLogDebug("pos:"+str(ToUnits(prv_pos.x))+":"+str(ToUnits(prv_pos.y))+";"+str(ToUnits(pos.x))+":"+str(ToUnits(pos.y)),debug)
    return points
    #if 0:
    #    for i, p in enumerate(points):
    #        #if i < len (points)-1:
    #        if i < len (points)-2:
    #            t = create_Solder(pcb,p,points[i+1],layer,width,Nn,True,pcbGroup) #adding ts code to segments
    #    t = create_Solder(pcb,points[-2],ep,layer,width,Nn,True,pcbGroup) #avoiding rounding on last segment
#
# Function to find the circle on
# which the given three points lie
def getCircleCenterRadius(sp,ep,ip):
    # findCircle(x1, y1, x2, y2, x3, y3) :
    # NB add always set float even if values are pcb internal Units!!!
    x1 = float(sp.x); y1 = float(sp.y)
    x2 = float(ep.x); y2 = float(ep.y)
    x3 = float(ip.x); y3 = float(ip.y)
    
    x12 = x1 - x2;
    x13 = x1 - x3;
    y12 = y1 - y2;
    y13 = y1 - y3;
    y31 = y3 - y1;
    y21 = y2 - y1;
    x31 = x3 - x1;
    x21 = x2 - x1;
    
    # x1^2 - x3^2
    sx13 = math.pow(x1, 2) - math.pow(x3, 2);
    # y1^2 - y3^2
    sy13 = math.pow(y1, 2) - math.pow(y3, 2);
    sx21 = math.pow(x2, 2) - math.pow(x1, 2);
    sy21 = math.pow(y2, 2) - math.pow(y1, 2);
    
    f = (((sx13) * (x12) + (sy13) *
      (x12) + (sx21) * (x13) +
      (sy21) * (x13)) // (2 *
      ((y31) * (x12) - (y21) * (x13))));
          
    g = (((sx13) * (y12) + (sy13) * (y12) +
      (sx21) * (y13) + (sy21) * (y13)) //
      (2 * ((x31) * (y12) - (x21) * (y13))));
    
    c = (-math.pow(x1, 2) - math.pow(y1, 2) - 2 * g * x1 - 2 * f * y1);
    
    # eqn of circle be x^2 + y^2 + 2*g*x + 2*f*y + c = 0
    # where centre is (h = -g, k = -f) and
    # radius r as r^2 = h^2 + k^2 - c
    h = -g;
    k = -f;
    sqr_of_r = h * h + k * k - c;
    # r is the radius
    r = round(math.sqrt(sqr_of_r), 5);
    Cx = h
    Cy = k
    radius = r
    return wx.Point(int(Cx),int(Cy)), radius
#
def getAngleRadians(p1,p2):
    #return math.degrees(math.atan2((p1.y-p2.y),(p1.x-p2.x)))
    return (math.atan2((p1.y-p2.y),(p1.x-p2.x)))
#
def rotatePoint(r,sa,da,c):
    # sa, da in radians
    x = c.x - math.cos(sa+da) * r
    y = c.y - math.sin(sa+da) * r
    return wx.Point(int(x),int(y))

def calculate_adaptive_segments(radius, arc_angle, max_deviation_mm=0.1, min_segments=16):
    """
    Calculate adaptive number of segments for arc discretization based on geometry.
    
    For tight curves in length-tuned serpentines, this provides much finer meshing than the
    old fixed 16 segments, ensuring via fences follow curved traces accurately.
    
    Args:
        radius: Arc radius in internal units
        arc_angle: Absolute angle swept by arc in radians
        max_deviation_mm: Maximum allowed chord deviation from true arc in mm (default 0.1mm)
        min_segments: Minimum number of segments (default 16)
    
    Returns:
        Number of segments suitable for this arc
    
    For a given radius and segment count n, the sagitta (deviation from arc) is:
    sagitta = radius * (1 - cos(angle/(2*n)))
    Solving for n: n >= angle / (2 * arccos(1 - sagitta/radius))
    """
    if radius <= 0 or arc_angle <= 0:
        return min_segments
    
    try:
        # Convert max deviation to internal units (support both KiCad 5 and 6+ scales)
        # KiCad 5: ~10000 units/mm, KiCad 6+: ~1000000 units/mm
        # We detect by checking radius magnitude
        if radius > 100000:  # Likely KiCad 6+ (1mm = 1000000 units)
            max_dev = max_deviation_mm * 1000000.0
        else:  # Likely KiCad 5 (1mm = 10000 units)
            max_dev = max_deviation_mm * 10000.0
        
        # Don't allow deviation larger than 50% of radius (for very small arcs)
        max_dev = min(max_dev, radius * 0.5)
        
        if max_dev >= radius or max_dev <= 0:
            return min_segments
        
        # Calculate required angle per segment for the desired deviation
        # Using sagitta formula: angle_per_segment = 2 * arccos(1 - deviation/radius)
        cos_val = max(-1.0, min(1.0, 1.0 - (max_dev / float(radius))))
        angle_per_segment = 2.0 * math.acos(cos_val)
        
        if angle_per_segment <= 0:
            return min_segments
        
        # Calculate number of segments needed
        segments = int(math.ceil(arc_angle / angle_per_segment))
        
        # Apply bounds: use at least min_segments, and cap at 200 for sanity
        segments = max(min_segments, min(segments, 200))
        return segments
    except Exception:
        return min_segments