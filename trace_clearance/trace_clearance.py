#!/usr/bin/env python

# Copyright 2019 Maurice https://github.com/easyw/
# Copyright 2020 Matt Huszagh https://github.com/matthuszagh

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

import os
import pcbnew
import wx
# import numpy as np
from . import TraceClearanceDlg
import math
import configparser

class TraceClearance_Dlg(TraceClearanceDlg.TraceClearanceDlg):
    """
    """

    def SetSizeHints(self, sz1, sz2):
        if wx.__version__ < '4.0':
            self.SetSizeHintsSz(sz1, sz2)
        else:
            super(TraceClearance_Dlg, self).SetSizeHints(sz1, sz2)

    def __init__(self, parent):
        """
        """
        TraceClearanceDlg.TraceClearanceDlg.__init__(self, parent)
        #self.SetMinSize(self.GetSize())
        self.SetMinSize(wx.Size(100,100))
        self.local_config_file = os.path.join(os.path.dirname(__file__), 'tc_config.ini')
        config = configparser.ConfigParser()
        config.read(self.local_config_file)
        width = int(config.get('win_size','width'))
        height = int(config.get('win_size','height'))
        self.m_clearance.SetValue(config.get('params','clearance'))
        #wx.LogMessage(str(width)+';'+str(height))
        #self.GetSizer().Fit(self)
        self.SetSize((width,height))

class TraceClearance(pcbnew.ActionPlugin):
    """
    """

    def defaults(self):
        """
        """
        self.name = "Trace Clearance Generator\n version 1.8"
        self.category = "Modify PCB"
        self.description = (
            "Generate a copper pour keepout for a selected trace."
        )
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(
            os.path.dirname(__file__), "./trace_clearance.png"
        )
        
    def Run(self):
        """
        """
        _pcbnew_frame = [x for x in list(wx.GetTopLevelWindows()) if x.GetName() == 'PcbFrame'][0]
        # _pcbnew_frame = [
        #     x
        #     for x in list(wx.GetTopLevelWindows())
        #     if x.GetTitle().lower().startswith("pcbnew")
        # ][0]
        wx_params = TraceClearance_Dlg(_pcbnew_frame)
        #wx_params.m_clearance.SetValue("0.2")
        wx_params.m_bitmap.SetBitmap(
            wx.Bitmap(
                os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    "trace_clearance_dialog_small.png",
                )
            )
        )
        modal_res = wx_params.ShowModal()
        mm_value = self.InputValid(wx_params.m_clearance.GetValue())
        if mm_value is None:
            wx_params.Destroy()
            return
        clearance = pcbnew.FromMM(mm_value)
        if clearance is not None:
            pcb = pcbnew.GetBoard()
            wx_params.local_config_file = os.path.join(os.path.dirname(__file__), 'tc_config.ini')
            config = configparser.ConfigParser()
            config.read(wx_params.local_config_file)
            config['win_size']['width'] = str(wx_params.GetSize()[0])
            config['win_size']['height'] = str(wx_params.GetSize()[1])
            config['params']['clearance'] = wx_params.m_clearance.Value
            with open(wx_params.local_config_file, 'w') as configfile:
                config.write(configfile)
            if modal_res == wx.ID_OK:
                tracks = selected_tracks(pcb)
                if len(tracks) > 0:
                    set_keepouts(pcb, tracks, clearance)
                else:
                    self.Warn("At least one track must be selected.")
            elif modal_res == wx.ID_CANCEL:
                wx_params.Destroy()

    def Warn(self, message, caption="Warning!"):
        """
        """
        dlg = wx.MessageDialog(None, message, caption, wx.OK | wx.ICON_WARNING)
        dlg.ShowModal()
        dlg.Destroy()

    def InputValid(self, value):
        """
        """
        float_val = None
        try:
            float_val = float(value)
        except:
            self.Warn("Clearance must be a floating point number.")
            return None

        if float_val <= 0:
            self.Warn("Clearance must be positive.")
            return None

        return float_val


def selected_tracks(pcb):
    """
    TODO should we use a common import with solder expander to avoid
    redundant functionality?
    """
    tracks = []
    
    if  hasattr(pcbnew,'TRACK'):
        track_item = pcbnew.TRACK
    else:
        track_item = pcbnew.PCB_TRACK
    # Ensure trk_arc is defined if available
    trk_arc = getattr(pcbnew, 'PCB_ARC', None)
    for item in pcb.GetTracks():
        if type(item) is track_item and item.IsSelected():
            tracks.append(item)
        elif trk_arc is not None and type(item) is trk_arc and item.IsSelected():
            tracks.append(item)
            
    return tracks


def _point_to_tuple(p):
    """Return an (int x, int y) tuple from a KiCad point-like object."""
    try:
        # VECTOR2I / wxPoint style
        x = int(getattr(p, 'x'))
        y = int(getattr(p, 'y'))
        return (x, y)
    except Exception:
        pass
    try:
        # Indexable
        return (int(p[0]), int(p[1]))
    except Exception:
        pass
    # Fallback: try attributes X(), Y()
    try:
        return (int(p.X()), int(p.Y()))
    except Exception:
        raise TypeError(f"Unsupported point type: {type(p)}")


def _close_polygon(coords):
    if not coords:
        return coords
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    return coords


def _make_line_chain(coords):
    """Build a SHAPE_LINE_CHAIN from integer (x,y) coords and mark it closed."""
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in coords:
        try:
            if hasattr(pcbnew, 'VECTOR2I'):
                chain.Append(pcbnew.VECTOR2I(int(x), int(y)))
            else:
                chain.Append(int(x), int(y))
        except Exception:
            # Fallback: try tuple style
            chain.Append(int(x), int(y))
    try:
        if hasattr(chain, 'SetClosed'):
            chain.SetClosed(True)
    except Exception:
        pass
    return chain


def try_add_gnd_cutout(pcb, pts, track_layer):
    """Attempt to add a cutout polygon to all GND zones.
    Returns True if at least one cutout was added, else False.
    """
    # Convert point list to plain integer tuples, and close the polygon
    try:
        coords = [_point_to_tuple(p) for p in pts]
        coords = _close_polygon(coords)
        chain = _make_line_chain(coords)
    except Exception as e:
        try:
            wx.LogMessage(f"Cutout conversion failed: {e}")
        except Exception:
            pass
        return False

    added = False
    for i in range(pcb.GetAreaCount()):
        zone = pcb.GetArea(i)
        # Skip rule areas/keepouts
        try:
            if hasattr(zone, 'GetIsRuleArea') and zone.GetIsRuleArea():
                continue
            if hasattr(zone, 'IsKeepout') and zone.IsKeepout():
                continue
        except Exception:
            pass
        # Check net is GND (by net object or name)
        is_gnd = False
        try:
            net = zone.GetNet()
            if net and net.GetNetname().upper() == 'GND':
                is_gnd = True
        except Exception:
            pass
        if not is_gnd:
            try:
                netname = zone.GetNetname()
                if netname and netname.upper() == 'GND':
                    is_gnd = True
            except Exception:
                pass
        if not is_gnd:
            continue
        # Add a hole/cutout to the zone outline
        outline = None
        try:
            outline = zone.Outline()
        except Exception:
            outline = None
        if outline is None:
            continue
        try:
            has_add_hole = hasattr(outline, 'AddHole')
            has_new_hole = hasattr(outline, 'NewHole') and hasattr(outline, 'Append')
            if has_add_hole:
                # KiCad expects a SHAPE_LINE_CHAIN for AddHole
                outline.AddHole(chain)
                added = True
            elif has_new_hole:
                outline.NewHole()
                for x, y in coords:
                    outline.Append(int(x), int(y))
                if hasattr(outline, 'CloseLastContour'):
                    outline.CloseLastContour()
                added = True
            else:
                try:
                    wx.LogMessage("Zone outline does not support holes via Python API.")
                except Exception:
                    pass
                continue
            # Mark zone dirty and try local rebuild
            try:
                if hasattr(zone, 'MarkDirty'):
                    zone.MarkDirty()
                elif hasattr(zone, 'SetDirty'):
                    zone.SetDirty(True)
            except Exception:
                pass
            try:
                if hasattr(zone, 'BuildFilledSolidAreasPolygons'):
                    zone.BuildFilledSolidAreasPolygons(pcb)
            except Exception:
                pass
        except Exception as e:
            try:
                wx.LogMessage(f"Cutout insertion failed: {e}")
            except Exception:
                pass
            continue
    return added


def set_keepouts(pcb, tracks, clearance):
    """
    Only add GND zone cutouts. No global keepout fallback.
    """
    did_cutouts = False
    for track in tracks:
        track_start = track.GetStart()
        track_end = track.GetEnd()
        if track_start.x == track_end.x and track_start.y == track_end.y:
            continue
        track_width = track.GetWidth()
        track_midpoint = track.GetMid() if type(track) is pcbnew.PCB_ARC else None

        if track_midpoint and is_midpoint_linear(track_start, track_start, track_midpoint):
            track_midpoint = None

        pts = poly_points(track_start, track_end, track_midpoint, track_width, clearance)

        if try_add_gnd_cutout(pcb, pts, track.GetLayer()):
            did_cutouts = True
        else:
            try:
                wx.LogMessage("No suitable GND zone or cutout not supported; skipping.")
            except Exception:
                pass

    if did_cutouts:
        try:
            filler = pcbnew.ZONE_FILLER(pcb)
            filler.Fill(pcb.Zones())
        except Exception:
            pass
        try:
            pcb.OnModify()
        except Exception:
            pass

    pcbnew.Refresh()


def is_midpoint_linear(start, end, test):
    """
    Check if the 'test' midpoint is on the line segment defined by 'start' and 'end'.
    """
    # Check if the area of the triangle formed by the points is close to zero
    # which indicates collinearity.
    area = start.x * (end.y - test.y) + end.x * (test.y - start.y) + test.x * (start.y - end.y)
    if not math.isclose(area, 0, abs_tol=1e-6):
        return False
    # Check if 'test' is between 'start' and 'end'
    if min(start.x, end.x) <= test.x <= max(start.x, end.x) and min(start.y, end.y) <= test.y <= max(start.y, end.y):
        return True
    return False


def poly_points(track_start, track_end, track_midpoint, track_width, clearance):
    """
    """
    delta = track_width / 2 + clearance
    dx = track_end.x - track_start.x
    dy = track_end.y - track_start.y
    theta = math.atan2(dy, dx)
    len = math.sqrt(math.pow(dx, 2) + math.pow(dy, 2))
    dx_norm = dx / len
    dy_norm = dy / len

    delta_x = delta * -dy_norm
    delta_y = delta * dx_norm
    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        pt_delta = pcbnew.wxPoint(delta_x, delta_y)
    elif hasattr(pcbnew, 'wxPoint()'): #kv7
        pt_delta = pcbnew.VECTOR2I(pcbnew.wxPoint(delta_x, delta_y))
    else:#kv8
        pt_delta = pcbnew.VECTOR2I(pcbnew.VECTOR2I(int(delta_x), int(delta_y)))
    pts = []
    if track_midpoint is not None: # arc
        center, ccw = arc_center(track_start, track_midpoint, track_end)
        if ccw: # make it clockwise by swapping what is the 'start' and 'end'
            track_start, track_end = track_end, track_start
        radius = math.sqrt((center.x - track_start.x)**2 + (center.y - track_start.y)**2)
        # Calculate start and end angles
        start_angle = math.atan2(track_start.y - center.y, track_start.x - center.x)
        end_angle = math.atan2(track_end.y - center.y, track_end.x - center.x)
        if end_angle < start_angle:
            end_angle += 2 * math.pi

        # Generate points for outer and inner arcs
        outer_arc_points = arc_points(center, radius + delta, start_angle, end_angle, 20)
        if delta < radius:
            inner_arc_points = arc_points(center, radius - delta, start_angle, end_angle, 20)
        else:
            inner_arc_points = []

        # Tangent angles at start and end of the arc
        start_tangent_angle = start_angle + math.pi / 2
        end_tangent_angle = end_angle + math.pi / 2
        start_semicircle = semicircle_points(track_start, delta, start_tangent_angle, True)
        end_semicircle = semicircle_points(track_end, delta, end_tangent_angle, False)

        # Combine points in correct order
        pts.extend(start_semicircle)
        pts.extend(outer_arc_points)
        pts.extend(end_semicircle)
        pts.extend(inner_arc_points[::-1])  # Reverse inner arc for correct order

    else: # straight track
        pts.append(track_start + pt_delta)
        for pt in semicircle_points(track_start, delta, theta, True):
            pts.append(pt)
        pts.append(track_start - pt_delta)
        pts.append(track_end - pt_delta)
        for pt in semicircle_points(track_end, delta, theta, False):
            pts.append(pt)
        pts.append(track_end + pt_delta)

    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        return pcbnew.wxPoint_Vector(pts)
    else: #kv7
        return pcbnew.VECTOR_VECTOR2I(pts)


def arc_center(p1, p2, p3):
    """
    Calculate the center of the circle passing through an arc defined by p1, p2, p3

    Returns the center and whether or not the arc traverses counterclockwise
    """
    # Midpoints of p1p2 and p2p3
    mid1 = ((p1.x + p2.x) / 2, (p1.y + p2.y) / 2)
    mid2 = ((p2.x + p3.x) / 2, (p2.y + p3.y) / 2)

    slope1 = (p2.y - p1.y) / (p2.x - p1.x) if p2.x != p1.x else float('inf')
    slope2 = (p3.y - p2.y) / (p3.x - p2.x) if p3.x != p2.x else float('inf')

    # Perpendicular slopes
    perp_slope1 = -1 / slope1 if slope1 != 0 else float('inf')
    perp_slope2 = -1 / slope2 if slope2 != 0 else float('inf')

    # Solve for intersection
    c1 = mid1[1] - perp_slope1 * mid1[0]
    c2 = mid2[1] - perp_slope2 * mid2[0]

    # Intersection point (center of the circle)
    center_x = (c2 - c1) / (perp_slope1 - perp_slope2)
    center_y = perp_slope1 * center_x + c1

    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        center = pcbnew.wxPoint(center_x, center_y)
    elif  hasattr(pcbnew,'wxPoint()'): #kv7
        center = pcbnew.VECTOR2I(pcbnew.wxPoint(center_x, center_y))
    else: #kv8
        center = pcbnew.VECTOR2I(pcbnew.VECTOR2I(int(center_x), int(center_y)))

    v1 = (p1.x - center.x, p1.y - center.y)
    v2 = (p3.x - center.x, p3.y - center.y)
    ccw = (v1[0] * v2[1] - v1[1] * v2[0]) < 0
    return center, ccw


def arc_points(center, radius, start_angle, end_angle, num_points):
    """
    generates num_points along an arc
    """
    pts = []
    for i in range(num_points):
        angle = start_angle + i * (end_angle - start_angle) / (num_points - 1)
        x = center[0] + radius * math.cos(angle)
        y = center[1] + radius * math.sin(angle)
        if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
            pts.append(pcbnew.wxPoint(x, y))
        elif  hasattr(pcbnew,'wxPoint()'): #kv7
            pts.append(pcbnew.VECTOR2I(pcbnew.wxPoint(x, y)))
        else:
            pts.append(pcbnew.VECTOR2I(int(x), int(y)))
    return pts


def semicircle_points(circle_center, radius, angle_norm, is_start=True):
    """
    """
    num_points = 20

    # angles = np.linspace(
    #     angle_norm + np.pi / 2, angle_norm + 3 * np.pi / 2, num_points + 2
    # )
    angle_offset = 0 if is_start else math.pi
    start    = angle_offset + angle_norm + math.pi / 2
    stop     = angle_offset + angle_norm + 3 * math.pi / 2
    num_vals = num_points
    delta = (stop-start)/(num_vals-1)
    evenly_spaced = [start + i * delta for i in range(num_vals)]
    # print(evenly_spaced)
    angles = evenly_spaced
    # wx.LogMessage(str(angles))
    angles = angles[1:-1]
    # wx.LogMessage(str(angles)+'1')
    pts = []
    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        for ang in angles:
            pts.append(
                circle_center
                + pcbnew.wxPoint(radius * math.cos(ang), radius * math.sin(ang))
            )
        return pcbnew.wxPoint_Vector(pts)
    elif hasattr(pcbnew, 'wxPoint()'): #kv7 
        for ang in angles:
            pts.append(
                circle_center
                + pcbnew.VECTOR2I(pcbnew.wxPoint(radius * math.cos(ang), radius * math.sin(ang)))
            )
        # Return a plain Python list of points for iteration within poly construction
        return pts
    else: # kv8
        for ang in angles:
            pts.append(
                circle_center
                + pcbnew.VECTOR2I(int(radius * math.cos(ang)), int(radius * math.sin(ang)))
            )
        return pcbnew.VECTOR_VECTOR2I(pts)
