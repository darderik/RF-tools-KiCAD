#!/usr/bin/env python

# Taper for pcbnew using filled zones
# easyw
#
# Based 
# on Teardrops for PCBNEW by Niluje 2019 thewireddoesntexist.org
# on kicad Toolbox vy aschaller 

import os
import sys
import configparser
from math import cos, acos, sin, asin, tan, atan2, sqrt, pi, degrees, radians, copysign
from pcbnew import ToMM, FromMM, wxPoint, GetBoard, ZONE_SETTINGS, VECTOR2I
from pcbnew import ZONE_FILLER
import pcbnew
import wx

if hasattr(pcbnew,'ZONE_CONTAINER'):
    from pcbnew import ZONE_CONTAINER
else:
    from pcbnew import ZONE
SMOOTHING_FILLET = ZONE_SETTINGS.SMOOTHING_FILLET


def wxLogDebug(msg,show):
    """printing messages only if show is omitted or True"""
    if show:
        wx.LogMessage(msg)
#

##global __version__
__version__ = "1.4"

ToUnits = ToMM
FromUnits = FromMM

MAGIC_TAPER_ZONE_ID = 0x4484

dbg = False

TAPER_CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'tp_config.ini')
DEFAULT_TAPER_SETTINGS = {
    'segments': '10',
    'length_factor': '1.0',
    'length_mm': '0.0',
    'smooth_edges': 'True',
    'fillet_radius_mm': '0.06',
}
EPSILON = 1e-12
ARC_TAPER_TAIL_FRACTION = 0.35
ARC_TAPER_TAIL_MIN_MM = 0.20

def dummy():
    pass
##
def __Clamp(value, low, high):
    return max(low, min(high, value))


def __SafeInt(value, fallback):
    try:
        return int(value)
    except Exception:
        return fallback


def __SafeFloat(value, fallback):
    try:
        return float(value)
    except Exception:
        return fallback


def __SafeBool(value, fallback):
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    value_s = str(value).strip().lower()
    if value_s in ('1', 'true', 'yes', 'on'):
        return True
    if value_s in ('0', 'false', 'no', 'off'):
        return False
    return fallback


def __GetTaperSettings():
    config = configparser.ConfigParser()
    config.read_dict({'params': DEFAULT_TAPER_SETTINGS.copy()})
    existing_files = config.read(TAPER_CONFIG_FILE)

    if not config.has_section('params'):
        config.add_section('params')

    changed = False
    for key, value in DEFAULT_TAPER_SETTINGS.items():
        if not config.has_option('params', key):
            config.set('params', key, value)
            changed = True

    if not existing_files or changed:
        try:
            with open(TAPER_CONFIG_FILE, 'w') as configfile:
                config.write(configfile)
        except Exception:
            wxLogDebug('Unable to write taper config file: ' + TAPER_CONFIG_FILE, dbg)

    params = config['params']
    segments = __Clamp(__SafeInt(params.get('segments', DEFAULT_TAPER_SETTINGS['segments']), 10), 2, 64)
    length_factor = max(0.01, __SafeFloat(params.get('length_factor', DEFAULT_TAPER_SETTINGS['length_factor']), 1.0))
    length_mm = max(0.0, __SafeFloat(params.get('length_mm', DEFAULT_TAPER_SETTINGS['length_mm']), 0.0))
    smooth_edges = __SafeBool(params.get('smooth_edges', DEFAULT_TAPER_SETTINGS['smooth_edges']), True)
    fillet_radius_mm = max(0.0, __SafeFloat(params.get('fillet_radius_mm', DEFAULT_TAPER_SETTINGS['fillet_radius_mm']), 0.06))

    return {
        'segments': segments,
        'length_factor': length_factor,
        'length_mm': length_mm,
        'smooth_edges': smooth_edges,
        'fillet_radius_mm': fillet_radius_mm,
        'fixed_length_iu': FromMM(length_mm) if length_mm > 0 else 0,
    }


def __SaveTaperSettings(settings):
    config = configparser.ConfigParser()
    config.read_dict({'params': DEFAULT_TAPER_SETTINGS.copy()})
    config.read(TAPER_CONFIG_FILE)
    if not config.has_section('params'):
        config.add_section('params')

    config.set('params', 'segments', str(__Clamp(__SafeInt(settings.get('segments', 10), 10), 2, 64)))
    config.set('params', 'length_factor', str(max(0.01, __SafeFloat(settings.get('length_factor', 1.0), 1.0))))
    config.set('params', 'length_mm', str(max(0.0, __SafeFloat(settings.get('length_mm', 0.0), 0.0))))
    config.set('params', 'smooth_edges', str(__SafeBool(settings.get('smooth_edges', True), True)))
    config.set('params', 'fillet_radius_mm', str(max(0.0, __SafeFloat(settings.get('fillet_radius_mm', 0.06), 0.06))))

    with open(TAPER_CONFIG_FILE, 'w') as configfile:
        config.write(configfile)


def __MakePoint(x, y):
    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        return wxPoint(int(x), int(y))
    elif hasattr(pcbnew, 'wxPoint()'): # kv7
        return VECTOR2I(wxPoint(int(x), int(y)))
    else: # kv8
        return VECTOR2I(int(x), int(y))


def __PointTuple(point):
    return (int(point.x), int(point.y))


def __TupleDistance(a, b):
    return sqrt((a[0]-b[0])*(a[0]-b[0]) + (a[1]-b[1])*(a[1]-b[1]))


def __IsCircularPad(pad):
    try:
        if hasattr(pcbnew, 'PAD_SHAPE_CIRCLE') and hasattr(pad, 'GetShape'):
            if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
                return True
    except Exception:
        pass

    try:
        sx = pad.GetSize().x
        sy = pad.GetSize().y
        return abs(float(sx) - float(sy)) <= max(1.0, float(FromMM(0.002)))
    except Exception:
        return False


def __ClampTrackPadPointsToTargetSide(points, pad, approach_vec):
    """Prevent taper polygon from going past target pad opposite side.

    Any point that falls behind pad center w.r.t. approach vector is projected
    onto the pad-center half-plane.
    """
    if points is None or len(points) == 0:
        return points

    vx, vy = approach_vec[0], approach_vec[1]
    vnorm = sqrt(vx*vx + vy*vy)
    if vnorm <= EPSILON:
        return points
    vx /= vnorm
    vy /= vnorm

    cx = float(pad.GetPosition().x)
    cy = float(pad.GetPosition().y)

    out = []
    for p in points:
        px = float(p.x)
        py = float(p.y)
        dx = px - cx
        dy = py - cy
        proj = dx*vx + dy*vy
        if proj < 0.0:
            dx -= proj * vx
            dy -= proj * vy
            out.append(__MakePoint(cx + dx, cy + dy))
        else:
            out.append(p)
    return out


def __ArcCenterFromThreePoints(p1, p2, p3):
    x1, y1 = float(p1.x), float(p1.y)
    x2, y2 = float(p2.x), float(p2.y)
    x3, y3 = float(p3.x), float(p3.y)

    d = 2.0 * (x1*(y2-y3) + x2*(y3-y1) + x3*(y1-y2))
    if abs(d) <= EPSILON:
        return None

    x1s = x1*x1 + y1*y1
    x2s = x2*x2 + y2*y2
    x3s = x3*x3 + y3*y3

    ux = (x1s*(y2-y3) + x2s*(y3-y1) + x3s*(y1-y2)) / d
    uy = (x1s*(x3-x2) + x2s*(x1-x3) + x3s*(x2-x1)) / d
    return (ux, uy)


def __ComputeArcTipTangent(track, start, end):
    if not (__IsArcTrack(track) and hasattr(track, 'GetMid')):
        return None

    center = __ArcCenterFromThreePoints(start, track.GetMid(), end)
    if center is None:
        return None

    sx = float(start.x)
    sy = float(start.y)
    ex = float(end.x)
    ey = float(end.y)
    rx = sx - center[0]
    ry = sy - center[1]

    t1 = (-ry, rx)
    t2 = (ry, -rx)
    hint = (ex - sx, ey - sy)

    dot1 = t1[0]*hint[0] + t1[1]*hint[1]
    dot2 = t2[0]*hint[0] + t2[1]*hint[1]
    tx, ty = t1 if dot1 >= dot2 else t2

    norm = sqrt(tx*tx + ty*ty)
    if norm <= EPSILON:
        return None
    return [tx/norm, ty/norm]


def __ResolveTargetLength(auto_target_length, length_factor, fixed_length_iu):
    if fixed_length_iu > 0:
        return fixed_length_iu
    if auto_target_length <= 0:
        return auto_target_length
    return auto_target_length * max(0.01, length_factor)


def __ComputeWeaken(vpercent, min_vpercent, radius):
    if radius <= EPSILON:
        return 0.0
    denominator = 1.0 - min_vpercent
    if abs(denominator) <= EPSILON:
        return 0.0
    return (vpercent/100.0 - min_vpercent) / denominator / radius


def __ShowTaperSettingsDialog(settings):
    dlg = wx.Dialog(None, title='Taper Settings', style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    main_sizer = wx.BoxSizer(wx.VERTICAL)

    info = wx.StaticText(
        dlg,
        label='Selection modes:\n'
              '- 1 track + 1 pad: pad taper\n'
              '- 2 tracks: point join taper\n'
              '- 3+ connected tracks: trajectory taper (max width -> min width)'
    )
    main_sizer.Add(info, 0, wx.ALL | wx.EXPAND, 8)

    grid = wx.FlexGridSizer(0, 2, 6, 8)
    grid.AddGrowableCol(1, 1)

    spn_segments = wx.SpinCtrl(dlg, min=2, max=64)
    spn_segments.SetValue(int(settings.get('segments', 10)))
    grid.Add(wx.StaticText(dlg, label='Curve segments'), 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(spn_segments, 1, wx.EXPAND)

    txt_factor = wx.TextCtrl(dlg, value=str(settings.get('length_factor', 1.0)))
    grid.Add(wx.StaticText(dlg, label='Length factor (auto)'), 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(txt_factor, 1, wx.EXPAND)

    chk_fixed = wx.CheckBox(dlg, label='Use fixed taper length (mm)')
    chk_fixed.SetValue(float(settings.get('length_mm', 0.0)) > 0.0)
    txt_len_mm = wx.TextCtrl(dlg, value=str(settings.get('length_mm', 0.0)))
    txt_len_mm.Enable(chk_fixed.GetValue())
    grid.Add(chk_fixed, 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(txt_len_mm, 1, wx.EXPAND)

    chk_smooth = wx.CheckBox(dlg, label='Smooth taper edges (fillet)')
    chk_smooth.SetValue(bool(settings.get('smooth_edges', True)))
    txt_fillet = wx.TextCtrl(dlg, value=str(settings.get('fillet_radius_mm', 0.06)))
    txt_fillet.Enable(chk_smooth.GetValue())
    grid.Add(chk_smooth, 0, wx.ALIGN_CENTER_VERTICAL)
    grid.Add(txt_fillet, 1, wx.EXPAND)

    main_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 8)

    btn_sizer = wx.StdDialogButtonSizer()
    btn_apply = wx.Button(dlg, wx.ID_OK, 'Apply')
    btn_cancel = wx.Button(dlg, wx.ID_CANCEL, 'Cancel')
    btn_remove = wx.Button(dlg, wx.ID_DELETE, 'Remove All Tapers')
    btn_sizer.AddButton(btn_apply)
    btn_sizer.AddButton(btn_cancel)
    btn_sizer.AddButton(btn_remove)
    btn_sizer.Realize()
    main_sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

    def on_toggle_fixed(event):
        txt_len_mm.Enable(chk_fixed.GetValue())
        event.Skip()

    def on_toggle_smooth(event):
        txt_fillet.Enable(chk_smooth.GetValue())
        event.Skip()

    chk_fixed.Bind(wx.EVT_CHECKBOX, on_toggle_fixed)
    chk_smooth.Bind(wx.EVT_CHECKBOX, on_toggle_smooth)
    btn_remove.Bind(wx.EVT_BUTTON, lambda event: dlg.EndModal(wx.ID_DELETE))

    dlg.SetSizer(main_sizer)
    dlg.Fit()
    dlg.SetMinSize(dlg.GetSize())

    result = dlg.ShowModal()
    if result == wx.ID_CANCEL:
        dlg.Destroy()
        return None

    if result == wx.ID_DELETE:
        dlg.Destroy()
        return {'action': 'remove'}

    out = dict(settings)
    out['segments'] = __Clamp(__SafeInt(spn_segments.GetValue(), 10), 2, 64)
    out['length_factor'] = max(0.01, __SafeFloat(txt_factor.GetValue(), 1.0))
    out['length_mm'] = max(0.0, __SafeFloat(txt_len_mm.GetValue(), 0.0)) if chk_fixed.GetValue() else 0.0
    out['smooth_edges'] = chk_smooth.GetValue()
    out['fillet_radius_mm'] = max(0.0, __SafeFloat(txt_fillet.GetValue(), 0.06))
    out['fixed_length_iu'] = FromMM(out['length_mm']) if out['length_mm'] > 0 else 0
    out['action'] = 'apply'

    dlg.Destroy()
    return out


def __ApplyZoneSmoothing(zone_obj, settings):
    if settings is None:
        return
    if not settings.get('smooth_edges', False):
        return

    radius_iu = FromMM(max(0.0, __SafeFloat(settings.get('fillet_radius_mm', 0.0), 0.0)))
    if radius_iu <= 0:
        return

    try:
        if hasattr(zone_obj, 'SetCornerSmoothingType'):
            zone_obj.SetCornerSmoothingType(SMOOTHING_FILLET)
        elif hasattr(zone_obj, 'SetSmoothingType'):
            zone_obj.SetSmoothingType(SMOOTHING_FILLET)
    except Exception:
        pass

    try:
        if hasattr(zone_obj, 'SetCornerRadius'):
            zone_obj.SetCornerRadius(int(radius_iu))
        elif hasattr(zone_obj, 'SetSmoothingRadius'):
            zone_obj.SetSmoothingRadius(int(radius_iu))
    except Exception:
        pass


def __Zone(board, points, track, settings=None):
    """Add a zone to the board"""
    if hasattr(pcbnew, 'ZONE_CONTAINER'): # kv5
        z = ZONE_CONTAINER(board)
        z.SetZoneClearance(track.GetClearance())
    else: # kv6
        z = ZONE(board)
        z.SetLocalClearance(track.GetLocalClearance(track.GetClass()))
    # Add zone properties
    z.SetLayer(track.GetLayer())
    z.SetNetCode(track.GetNetCode())
    
    z.SetMinThickness(25400)  # The minimum
    z.SetPadConnection(2)  # 2 -> solid
    z.SetIsFilled(True)
    __ApplyZoneSmoothing(z, settings)
    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        z.SetPriority(MAGIC_TAPER_ZONE_ID)  # MAGIC_TEARDROP_ZONE_ID)
    else: #kv7
        z.SetAssignedPriority(MAGIC_TAPER_ZONE_ID)  # MAGIC_TEARDROP_ZONE_ID)
    ol = z.Outline()
    ol.NewOutline()

    for p in points:
        ol.Append(p.x, p.y)

    # sys.stdout.write("+")
    return z
##
def __Bezier(p1, p2, p3, p4, n=20.0):
    n = float(n)
    pts = []
    for i in range(int(n)+1):
        t = i/n
        a = (1.0 - t)**3
        b = 3.0 * t * (1.0-t)**2
        c = 3.0 * t**2 * (1.0-t)
        d = t**3

        x = int(a * p1[0] + b * p2[0] + c * p3[0] + d * p4[0])
        y = int(a * p1[1] + b * p2[1] + c * p3[1] + d * p4[1])
        if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
            pts.append(wxPoint(x, y))
        elif hasattr(pcbnew, 'wxPoint()'): # kv7:
            pts.append(VECTOR2I(wxPoint(x, y)))
        else: #kv8
            pts.append(VECTOR2I(int(x), int(y)))
    return pts
##
def __PointDistance(a,b):
    """Distance between two points"""
    return sqrt((a[0]-b[0])*(a[0]-b[0]) + (a[1]-b[1])*(a[1]-b[1]))
##
def __ComputeCurved(vpercent, w, vec, pad, pts, segs, nsx, nsy, shiftD, shiftP):
    """Compute the curves part points"""

    # A and B are points on the track
    # C and E are points on the via
    # D is midpoint behind the via centre

    # pts = [pointA, pointB, pointC2, pointD, pointE2]
    
    # radius = via[1]/2
    radius = nsx/1.5 #/2 # pad.GetSize().x/2 (adjust this to nsy or nsx/2 get better result in some user case)
    if nsy <= 0:
        return [], []

    minVpercent = float(w*2) / float(nsy) # pad.GetSize().x) # via[1])
    weaken = __ComputeWeaken(vpercent, minVpercent, radius)
    biasBC = 0.5 * __PointDistance( pts[1], pts[2] )
    biasAE = 0.5 * __PointDistance( pts[4], pts[0] )

    vecC = pts[2] - pad.GetPosition() - shiftP # via[0]
    tangentC = [ pts[2][0] - vecC[1]*biasBC*weaken,
                 pts[2][1] + vecC[0]*biasBC*weaken ]
    vecE = pts[4] - pad.GetPosition() - shiftP # via[0]
    tangentE = [ pts[4][0] + vecE[1]*biasAE*weaken,
                 pts[4][1] - vecE[0]*biasAE*weaken ]

    tangentB = [pts[1][0] - vec[0]*biasBC, pts[1][1] - vec[1]*biasBC]
    tangentA = [pts[0][0] - vec[0]*biasAE, pts[0][1] - vec[1]*biasAE]

    curve1 = __Bezier(pts[1], tangentB, tangentC, pts[2], n=segs)
    curve2 = __Bezier(pts[4], tangentE, tangentA, pts[0], n=segs)

    #return curve1 + [pts[3]] + curve2
    return curve1, curve2

##
def __ComputeCurvedTracks(vpercent, w1, vec, w2, end2, pts, segs):
    """Compute the curves part points"""

    # A and B are points on the track
    # C and E are points on the via
    # D is midpoint behind the via centre

    # w2= track.GetWidth()
    # radius = via[1]/2
    radius = w2 #/2
    if w2 <= 0:
        return [], []

    minVpercent = float(w1*2) / float(w2) # via[1])
    weaken = __ComputeWeaken(vpercent, minVpercent, radius)

    biasBC = 0.5 * __PointDistance( pts[1], pts[2] )
    biasAE = 0.5 * __PointDistance( pts[4], pts[0] )

    vecC = pts[2] - end2 #track.GetEnd() # via[0]
    tangentC = [ pts[2][0] - vecC[1]*biasBC*weaken,
                 pts[2][1] + vecC[0]*biasBC*weaken ]
    vecE = pts[4] - end2 #track.GetEnd() # via[0]
    tangentE = [ pts[4][0] + vecE[1]*biasAE*weaken,
                 pts[4][1] - vecE[0]*biasAE*weaken ]

    tangentB = [pts[1][0] - vec[0]*biasBC, pts[1][1] - vec[1]*biasBC]
    tangentA = [pts[0][0] - vec[0]*biasAE, pts[0][1] - vec[1]*biasAE]

    curve1 = __Bezier(pts[1], tangentB, tangentC, pts[2], n=segs)
    curve2 = __Bezier(pts[4], tangentE, tangentA, pts[0], n=segs)

    #return curve1 + [pts[3]] + curve2
    return curve1, curve2
##
def __NormalizeVector(pt):
    """Make vector unit length"""
    norm = sqrt(pt.x * pt.x + pt.y * pt.y)
    if norm <= EPSILON:
        return [0.0, 0.0]
    return [t / norm for t in pt]
## 
def __ComputePoints(track, pad, segs, length_factor=1.0, fixed_length_iu=0):
    """Compute all taper points"""
    #segs=4
    hpercent=1; vpercent=100; noBulge=True
    start = track.GetStart()
    end = track.GetEnd()
    module = pad.GetParent()

    # ensure that start is at the via/pad end
    if (__PointDistance(end, pad.GetPosition()) < __PointDistance(start, pad.GetPosition())): # via[0]) < radius:
        start, end = end, start
    # if __PointDistance(end, pad.GetPosition()) < radius: # via[0]) < radius:
    #     start, end = end, start

    # get normalized track vector
    # it will be used a base vector pointing in the track direction
    vecT = __NormalizeVector(end - start)
    if abs(vecT[0]) <= EPSILON and abs(vecT[1]) <= EPSILON:
        wx.LogMessage('Track has invalid geometry... aborting')
        return False

    arc_tip_tangent = __ComputeArcTipTangent(track, start, end)
    if arc_tip_tangent is not None:
        vecT = arc_tip_tangent

    trackAngle = atan2(vecT[1],vecT[0])
    if trackAngle > pi:
        trackAngle -=2*pi
    if trackAngle < -pi:
        trackAngle +=2*pi
    trackAngle=degrees(trackAngle)    
    wxLogDebug('trackAngle='+str(trackAngle),dbg)
    #wxLogDebug('vecT='+str(vecT),dbg)
    
    sx = pad.GetSize().x
    sy = pad.GetSize().y
    
    invx=1;invy=0

    if hasattr(pcbnew.BOARD_ITEM_CONTAINER, 'GetOrientationDegrees()'):
        mDegrees=module.GetOrientationDegrees()
    else:
        mDegrees=mDegrees=pad.GetOrientationDegrees()
    if abs(mDegrees) == 90 or abs(mDegrees) == 270:
        nsx = sx
        nsy  = sy
        wxLogDebug(' m1 '+'sx='+str(ToMM(sx))+' '+'sy='+str(ToMM(sy))+' '+'nsx='+str(ToMM(nsx))+' '+'nsy='+str(ToMM(nsy)),dbg)
        wxLogDebug(' m1 '+'mod angle='+str(mDegrees),dbg)
    else:
        nsx = sy
        nsy  = sx
        wxLogDebug(' m2 '+'sx='+str(ToMM(sx))+' '+'sy='+str(ToMM(sy))+' '+'nsx='+str(ToMM(nsx))+' '+'nsy='+str(ToMM(nsy)),dbg)
        wxLogDebug(' m2 '+'mod angle='+str(mDegrees),dbg)
    if (abs(trackAngle) >= 45 and abs(trackAngle) <= 135) or (abs(trackAngle) >= 225 and abs(trackAngle) <= 315):
        nsx,nsy = nsy,nsx
        #nsy  = nsx
        invx=0;invy=1
        wxLogDebug(' t1 '+'sx='+str(ToMM(sx))+' '+'sy='+str(ToMM(sy))+' '+'nsx='+str(ToMM(nsx))+' '+'nsy='+str(ToMM(nsy)),dbg)
        wxLogDebug(' t1 '+'track angle='+str(trackAngle),dbg)
    else:
        # nsx = nsx
        # nsy  = nsy
        invx=1;invy=0
        wxLogDebug(' t2 '+'sx='+str(ToMM(sx))+' '+'sy='+str(ToMM(sy))+' '+'nsx='+str(ToMM(nsx))+' '+'nsy='+str(ToMM(nsy)),dbg)
        wxLogDebug(' t2 '+'track angle='+str(trackAngle),dbg)
    radius = nsx/2 # via[1]/2.0
    if radius <= 0 or nsy <= 0:
        wx.LogMessage('Pad has invalid geometry... aborting')
        return False

    auto_target_length = nsy*(hpercent/100.0) # via[1]*(hpercent/100.0)
    targetLength = __ResolveTargetLength(auto_target_length, length_factor, fixed_length_iu)
    if targetLength <= 0:
        wx.LogMessage('Taper length is invalid... aborting')
        return False
    wxLogDebug('targetLength='+str(ToMM(targetLength)),dbg)
    
    w = track.GetWidth()/2

    if vpercent > 100:
        vpercent = 100

    # Find point of intersection between track and edge of via
    # This normalizes teardrop lengths
    bdelta = FromMM(0.01)
    backoff=0
    np = start
    while backoff<radius:
        if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
            np = start + wxPoint( vecT[0]*backoff, vecT[1]*backoff )
        elif hasattr(pcbnew, 'wxPoint()'): # kv7:
            np = start + VECTOR2I(wxPoint( vecT[0]*backoff, vecT[1]*backoff ))
        else:#kv8
            np = start + VECTOR2I(int( vecT[0]*backoff), int(vecT[1]*backoff ))
        if __PointDistance(np, pad.GetPosition()) >= radius: # via[0]) >= radius:
            break
        backoff += bdelta
    start=np

    # vec now points from via to intersect point
    vec = __NormalizeVector(start - pad.GetPosition()) # via[0])

    # choose a teardrop length
    # targetLength = pad.GetSize().x*(hpercent/100.0) # via[1]*(hpercent/100.0)
    n = min(targetLength, track.GetLength() - backoff)

    # If source track is an arc, limit taper to the arc tail near the pad to
    # avoid distorting the whole arc geometry.
    if __IsArcTrack(track):
        available_len = max(0.0, track.GetLength() - backoff)
        arc_tail_len = max(FromMM(ARC_TAPER_TAIL_MIN_MM), available_len * ARC_TAPER_TAIL_FRACTION)
        n = min(n, arc_tail_len)

    if n <= 0:
        wx.LogMessage('Track is too short for taper length... aborting')
        return False
    consumed = 0

    # if shortened, shrink width too
    if n+consumed < targetLength:
        minVpercent = 100* float(w) / float(radius)
        vpercent = vpercent*n/targetLength + minVpercent*(1-n/targetLength)

    vpercent = __Clamp(float(vpercent), 0.0, 100.0)
    
    internal_delta_multiplier = 0.15
    idm = internal_delta_multiplier
    # find point on the track, sharp end of the teardrop
    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        pointB = start + wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
        pointA = start + wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w )
        pointF = start + wxPoint(int(vecT[0]*+idm*w), int(vecT[1]*+idm*w))
    elif hasattr(pcbnew, 'wxPoint()'): # kv7:
        pointB = start + VECTOR2I(wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w ))
        pointA = start + VECTOR2I(wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w ))
        #pointB = wxPoint(int(start.x-0.15*radius),int(start.y-0.15*radius)) + wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
        # Introduce a last point in order to cover the via centre.
        # If not, the zone won't be filled or not connected
        pointF = start + VECTOR2I(wxPoint(int(vecT[0]*+idm*w), int(vecT[1]*+idm*w)))
    else: #kv8
        pointB = start + VECTOR2I(int( vecT[0]*n +vecT[1]*w) , int(vecT[1]*n -vecT[0]*w ))
        pointA = start + VECTOR2I(int( vecT[0]*n -vecT[1]*w ), int(vecT[1]*n +vecT[0]*w ))
        #pointB = wxPoint(int(start.x-0.15*radius),int(start.y-0.15*radius)) + wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
        # Introduce a last point in order to cover the via centre.
        # If not, the zone won't be filled or not connected
        pointF = start + VECTOR2I(int(vecT[0]*+idm*w), int(vecT[1]*+idm*w))
    
    # In some cases of very short, eccentric tracks the points can end up
    # inside the teardrop. If this happens just cancel adding it
    if ( __PointDistance(pointA, pad.GetPosition()) < radius or
         __PointDistance(pointB, pad.GetPosition()) < radius ):
        return False
    # if ( __PointDistance(pointA, via[0]) < radius or
    #      __PointDistance(pointB, via[0]) < radius ):
    #     return False

    # via side points

    # angular positions of where the teardrop meets the via
    wxLogDebug('vpercent='+str(ToMM(vpercent)),dbg)
    wxLogDebug('vpercent/100='+str(ToMM(vpercent/100)),dbg)

    dC = asin(__Clamp(vpercent/100.0, -1.0, 1.0))
    dE = -dC

    if noBulge:
        # find (signed) angle between track and teardrop
        offAngle = atan2(vecT[1],vecT[0]) - atan2(vec[1],vec[0])
        if offAngle > pi:
            offAngle -=2*pi
        if offAngle < -pi:
            offAngle +=2*pi

        if offAngle+dC > pi/2:
            dC = pi/2 - offAngle

        if offAngle+dE < -pi/2:
            dE = -pi/2 - offAngle
        #wxLogDebug('offAngle='+str(degrees(offAngle)),dbg)
        
    padAngle = radians(mDegrees)
    # TBD pad angle in correlation to mod angle

    #sign = copysign(1, sin(offAngle)) * copysign (1, cos(offAngle)) 
    wxLogDebug('offAngle='+str(degrees(offAngle))+' vec[0]='+str(vec[0])+' vec[1]='+str(vec[1]),dbg)
    #wxLogDebug('padAngle='+str(degrees(padAngle))+' cos='+str(cos(padAngle))+' sin='+str(sin(padAngle)),dbg)
    vecC = [vec[0]*cos(dC)+vec[1]*sin(dC), -vec[0]*sin(dC)+vec[1]*cos(dC)]
    vecE = [vec[0]*cos(dE)+vec[1]*sin(dE), -vec[0]*sin(dE)+vec[1]*cos(dE)]

    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        pointC = pad.GetPosition() + wxPoint(int(vecC[0] * nsx/2), int(vecC[1] * nsx/2)) #radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
        pointE = pad.GetPosition() + wxPoint(int(vecE[0] * nsx/2), int(vecE[1] * nsx/2)) #radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
    elif hasattr(pcbnew, 'wxPoint()'): # kv7:
        pointC = pad.GetPosition() + VECTOR2I(wxPoint(int(vecC[0] * nsx/2), int(vecC[1] * nsx/2))) #radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
        pointE = pad.GetPosition() + VECTOR2I(wxPoint(int(vecE[0] * nsx/2), int(vecE[1] * nsx/2))) #radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
    else: #kv8    
        pointC = pad.GetPosition() + VECTOR2I(int(vecC[0] * nsx/2), int(vecC[1] * nsx/2)) #radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
        pointE = pad.GetPosition() + VECTOR2I(int(vecE[0] * nsx/2), int(vecE[1] * nsx/2)) #radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
    # pointC = via[0] + wxPoint(int(vecC[0] * radius), int(vecC[1] * radius))
    # pointE = via[0] + wxPoint(int(vecE[0] * radius), int(vecE[1] * radius))
    #pointC2 = pointC + wxPoint(int(cos(padAngle)*vec[0]*invx*nsx*0.5), int(-sin(padAngle)*vec[1]*invy*nsx*0.5))
    #pointE2 = pointE + wxPoint(int(cos(padAngle)*vec[0]*invx*nsx*0.5), int(-sin(padAngle)*vec[1]*invy*nsx*0.5))
    
    signx = copysign (1, vec[0])
    signy = copysign (1, vec[1])
    use_axis_shift = not __IsCircularPad(pad)

    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        if use_axis_shift:
            shiftP = wxPoint(int(invx*signx*nsy*0.5), int(invy*signy*nsy*0.5))
        else:
            shiftP = wxPoint(0, 0)
        shiftD= wxPoint(int(vec[0]*-0.12*radius), int(vec[1]*-0.12*radius))
    elif hasattr(pcbnew, 'wxPoint()'): # kv7:
        if use_axis_shift:
            shiftP = VECTOR2I(wxPoint(int(invx*signx*nsy*0.5), int(invy*signy*nsy*0.5)))
        else:
            shiftP = VECTOR2I(wxPoint(0, 0))
        shiftD= VECTOR2I(wxPoint(int(vec[0]*-0.12*radius), int(vec[1]*-0.12*radius)))
    else: #kv8
        if use_axis_shift:
            shiftP = VECTOR2I(int(invx*signx*nsy*0.5), int(invy*signy*nsy*0.5))
        else:
            shiftP = VECTOR2I(0, 0)
        shiftD= VECTOR2I(int(vec[0]*-0.12*radius), int(vec[1]*-0.12*radius))
    pointC2 = pointC + shiftP #wxPoint(int(invx*signx*nsy*0.25), int(invy*signy*nsy*0.25))
    pointE2 = pointE + shiftP #wxPoint(int(invx*signx*nsy*0.25), int(invy*signy*nsy*0.25))

    # Introduce a last point in order to cover the via centre.
    # If not, the zone won't be filled
    pointD = pad.GetPosition() + shiftD
    # pointD = via[0] + wxPoint(int(vec[0]*-0.5*radius), int(vec[1]*-0.5*radius))

    pts = [pointA, pointB, pointC2, pointD, pointE2]
    #pts = [pointA, pointB, pointF, pointC, pointD, pointE]
    if segs > 2:
        #pts = __ComputeCurved(vpercent, w, vecT, pad, pts, segs, nsx, nsy)
        curve1, curve2 = __ComputeCurved(vpercent, w, vecT, pad, pts, segs, nsx, nsy, shiftD, shiftP)
        # Introduce a last point in order to cover the via centre.
        # if not it may not be connected
        #pts = [pointF]+curve1+[pointC,pointD,pointE]+curve2
        pts = [pointF]+curve1+[pointC,pointD,pointE]+curve2
        #for i,p in enumerate(pts):
        #    if i> 0:
        #        pts_n.append(p)

    pts = __ClampTrackPadPointsToTargetSide(pts, pad, vec)

    return pts
##

def __ComputePointsTracks(track1, track2, segs, length_factor=1.0, fixed_length_iu=0):
    """Compute all taper points for tracks"""
    #segs=2
    hpercent=1; vpercent=100; noBulge=True
    start1 = track1.GetStart()
    end1 = track1.GetEnd()
    start2 = track2.GetStart()
    end2 = track2.GetEnd()
    w1 = track1.GetWidth()/2
    w2 = track2.GetWidth()/2
    if w1 <= 0 or w2 <= 0:
        wx.LogMessage('Track width is invalid... aborting')
        return False
    if w1>w2:
        shift1=0.;shift2=1.0
    else:
        shift2=0.;shift1=1.0
    if w1 == w2:
        wx.LogMessage('the Tracks have the same width... aborting')
        return False
    wxLogDebug('start1='+str(start1)+' end1='+str(end1)+' start2='+str(start2)+' end2='+str(end2) ,dbg)
    wxLogDebug('shift1='+str(shift1)+' shift2='+str(shift2) ,dbg)
    # ensure that start1, end2 are at the tracks common
    common = None
    if (start1 == start2):
        common = start1
        start2, end2 = end2, start2
        wxLogDebug('1 inverting trk2',dbg)
    elif (start1 == end2):
        common = start1
        #start2, end2 = end2, start2
        wxLogDebug('2 ',dbg)
    elif (end1 == end2):
        common = end1
        start1, end1 = end1, start1
        #start2, end2 = end2, start2
        wxLogDebug('3 inverting trk1, trk2',dbg)
    elif (end1 == start2):
        common = end1
        start1, end1 = end1, start1
        start2, end2 = end2, start2
        wxLogDebug('4 inverting trk1, trk2',dbg)
    else:
        # tracks detached
        # ensure that start is at the common point [or the nearest TBD]
        d_min = min(__PointDistance(start1, end2), __PointDistance(start1, start2), __PointDistance(end1, start2), __PointDistance(end1, end2)) 
        if (__PointDistance(start1, start2) == d_min):
            start2, end2 = end2, start2
            wxLogDebug('a ',dbg)
        elif(__PointDistance(end1, start2) == d_min):
            start1, end1 = end1, start1
            start2, end2 = end2, start2            
            wxLogDebug('b ',dbg)
        elif(__PointDistance(end1, end2) == d_min):
            start1, end1 = end1, start1
            #start2, end2 = end2, start2
            wxLogDebug('c ',dbg)
        else: # start1, end2
            wxLogDebug('d ',dbg)
    if common is not None:
        wxLogDebug('common point: common: '+str(ToMM(common.x))+','+str(ToMM(common.y))+' w1='+str(ToMM(w1))+' w2='+str(ToMM(w2)),dbg)
    # get normalized track vectors
    # it will be used a base vector pointing in the track direction
    vecT1 = __NormalizeVector(end1 - start1)
    if abs(vecT1[0]) <= EPSILON and abs(vecT1[1]) <= EPSILON:
        wx.LogMessage('First track has invalid geometry... aborting')
        return False
    trackAngle1 = atan2(vecT1[1],vecT1[0])
    if trackAngle1 > pi:
        trackAngle1 -=2*pi
    if trackAngle1 < -pi:
        trackAngle1 +=2*pi
    trackAngle1=degrees(trackAngle1)    
    vecT2 = __NormalizeVector(end2 - start2)
    if abs(vecT2[0]) <= EPSILON and abs(vecT2[1]) <= EPSILON:
        wx.LogMessage('Second track has invalid geometry... aborting')
        return False
    trackAngle2 = atan2(vecT2[1],vecT2[0])
    if trackAngle2 > pi:
        trackAngle2 -=2*pi
    if trackAngle2 < -pi:
        trackAngle2 +=2*pi
    trackAngle2=degrees(trackAngle2)
    wxLogDebug('trackAngle1='+str(trackAngle1),dbg)
    wxLogDebug('trackAngle2='+str(trackAngle2),dbg)
    #wxLogDebug('vecT='+str(vecT),dbg)
    
    radius = w1 # via[1]/2.0
    auto_target_length = w2*(hpercent/100.0) # via[1]*(hpercent/100.0)
    targetLength = __ResolveTargetLength(auto_target_length, length_factor, fixed_length_iu)
    if targetLength <= 0:
        wx.LogMessage('Taper length is invalid... aborting')
        return False
    wxLogDebug('targetLength='+str(ToMM(targetLength)),dbg)
    wxLogDebug('trak2 Length='+str(ToMM(track2.GetLength())),dbg)
    
    if vpercent > 100:
        vpercent = 100
    
    backoff=0
    # choose a teardrop length
    # targetLength = pad.GetSize().x*(hpercent/100.0) # via[1]*(hpercent/100.0)
    n = min(targetLength, track2.GetLength() - backoff)
    if n <= 0:
        wx.LogMessage('Track is too short for taper length... aborting')
        return False
    wxLogDebug('n='+str(ToMM(n)),dbg)    
    consumed = 0

    # if shortened, shrink width too
    if n+consumed < targetLength:
        minVpercent = 100* float(w1) / float(w2)
        vpercent = vpercent*n/targetLength + minVpercent*(1-n/targetLength)

    vpercent = __Clamp(float(vpercent), 0.0, 100.0)

    internal_delta_multiplier1 = 1.5
    idm1 = internal_delta_multiplier1 * (1+shift1*0.15)
    # find point on the track, sharp end of the teardrop
    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        pointB = start1 + wxPoint(int(vecT1[0]*n +vecT1[1]*w1) , int(vecT1[1]*n -vecT1[0]*w1) ) + wxPoint(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointA = start1 + wxPoint(int(vecT1[0]*n -vecT1[1]*w1) , int(vecT1[1]*n +vecT1[0]*w1) ) + wxPoint(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        # Introduce a last point in order to cover the via centre.
        # If not, the zone won't be filled or not connected
        
        #pointF = start1 + wxPoint( vecT1[0]*n -vecT1[1]*idm1*w1 , vecT1[1]*n -vecT1[0]*idm1*w1 )
        #pointF = start1 + wxPoint(int(vecT1[0]*idm1*1.15*w1) , int(vecT1[1]*idm1*1.15*w1)) + wxPoint(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointF = start1 + wxPoint(int(vecT1[0]*1.15*w1) , int(vecT1[1]*1.15*w1)) + wxPoint(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointA2 = pointA + wxPoint(int(vecT1[0]*w1), int(vecT1[1]*w1))
        pointB2 = pointB + wxPoint(int(vecT1[0]*w1), int(vecT1[1]*w1))    
        #pointA2 = pointA + wxPoint(int(vecT1[0]*idm1*w1), int(vecT1[1]*idm1*w1))
        #pointB2 = pointB + wxPoint(int(vecT1[0]*idm1*w1), int(vecT1[1]*idm1*w1))    
    elif hasattr(pcbnew, 'wxPoint()'): # kv7:
        pointB = start1 + VECTOR2I(int(vecT1[0]*n +vecT1[1]*w1) , int(vecT1[1]*n -vecT1[0]*w1) ) + VECTOR2I(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointA = start1 + VECTOR2I(int(vecT1[0]*n -vecT1[1]*w1) , int(vecT1[1]*n +vecT1[0]*w1) ) + VECTOR2I(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointF =  start1 + VECTOR2I(int(vecT1[0]*1.15*w1) , int(vecT1[1]*1.15*w1)) + VECTOR2I(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointA2 = pointA + VECTOR2I(int(vecT1[0]*w1), int(vecT1[1]*w1))
        pointB2 = pointB + VECTOR2I(int(vecT1[0]*w1), int(vecT1[1]*w1))    
    else: #kv8    
        pointB = start1 + VECTOR2I(int(vecT1[0]*n +vecT1[1]*w1) , int(vecT1[1]*n -vecT1[0]*w1) ) + VECTOR2I(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointA = start1 + VECTOR2I(int(vecT1[0]*n -vecT1[1]*w1) , int(vecT1[1]*n +vecT1[0]*w1) ) + VECTOR2I(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointF =  start1 + VECTOR2I(int(vecT1[0]*1.15*w1) , int(vecT1[1]*1.15*w1)) + VECTOR2I(int(vecT1[0]*idm1*w2*shift1), int(vecT1[1]*idm1*w2*shift1))
        pointA2 = pointA + VECTOR2I(int(vecT1[0]*w1), int(vecT1[1]*w1))
        pointB2 = pointB + VECTOR2I(int(vecT1[0]*w1), int(vecT1[1]*w1))    
    #wx.LogMessage('w1='+str(ToMM(w1))+'w2='+str(ToMM(w2)))
    # In some cases of very short, eccentric tracks the points can end up
    # inside the teardrop. If this happens just cancel adding it
    ## if (__PointDistance(pointA, common) < max(w1,w2)  or
    ##     __PointDistance(pointB, common) < max(w1,w2) ):
    ##     wxLogDebug('aborting'+str(targetLength),dbg)
    ##     return False
    # if ( __PointDistance(pointA, via[0]) < radius or
    #      __PointDistance(pointB, via[0]) < radius ):
    #     return False

    # via side points

    # angular positions of where the teardrop meets the via
    dC = asin(__Clamp(vpercent/100.0, -1.0, 1.0))
    dE = -dC

    if noBulge:
        # find (signed) angle between track and teardrop
        offAngle = atan2(vecT1[1],vecT1[0]) - atan2(vecT2[1],vecT2[0])
        if offAngle > pi:
            offAngle -=2*pi
        if offAngle < -pi:
            offAngle +=2*pi

        if offAngle+dC > pi/2:
            dC = pi/2 - offAngle

        if offAngle+dE < -pi/2:
            dE = -pi/2 - offAngle
        #wxLogDebug('offAngle='+str(degrees(offAngle)),dbg)
        
    vecC = [vecT2[0]*cos(dC)+vecT2[1]*sin(dC), -vecT2[0]*sin(dC)+vecT2[1]*cos(dC)]
    vecE = [vecT2[0]*cos(dE)+vecT2[1]*sin(dE), -vecT2[0]*sin(dE)+vecT2[1]*cos(dE)]

    internal_delta_multiplier2 = 1.5
    idm2 = internal_delta_multiplier2 *  (1+shift2*0.15)
    if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
        pointC = end2 + wxPoint(int(vecC[0] * w2), int(vecC[1] * w2)) + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointE = end2 + wxPoint(int(vecE[0] * w2), int(vecE[1] * w2)) + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        end2_shift = end2 + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        #pointC = end2 + wxPoint(int(vecC[0] *idm* w2), int(vecC[1] *idm* w2))
        #pointE = end2 + wxPoint(int(vecE[0] *idm* w2), int(vecE[1] *idm* w2))
        # pointC = via[0] + wxPoint(int(vecC[0] * radius), int(vecC[1] * radius))
        # pointE = via[0] + wxPoint(int(vecE[0] * radius), int(vecE[1] * radius))
        pointC2 = pointC + wxPoint(int(vecT2[0]*-0.15*w2), int(vecT2[1]*-0.15*w2))#  + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointE2 = pointE + wxPoint(int(vecT2[0]*-0.15*w2), int(vecT2[1]*-0.15*w2))#  + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        # Introduce a last point in order to cover the via centre.
        # If not, the zone won't be filled
        pointD = end2 + wxPoint(int(vecT2[0]*-0.5*w2) , int(vecT2[1]*-0.5*w2)) + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2)) 
        #pointD = end2 + wxPoint(int(vecT2[0]*-idm2*1.15*w2), int(vecT2[1]*-idm2*1.15*w2)) + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        # pointD = via[0] + wxPoint(int(vec[0]*-0.5*radius), int(vec[1]*-0.5*radius))
    elif hasattr(pcbnew, 'wxPoint()'): # kv7:
        pointC = end2 + VECTOR2I(wxPoint(int(vecC[0] * w2), int(vecC[1] * w2))) + VECTOR2I(wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2)))
        pointE = end2 + VECTOR2I(wxPoint(int(vecE[0] * w2), int(vecE[1] * w2))) + VECTOR2I(wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2)))
        end2_shift = end2 + VECTOR2I(wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2)))
        pointC2 = pointC + VECTOR2I(wxPoint(int(vecT2[0]*-0.15*w2), int(vecT2[1]*-0.15*w2)))#  + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointE2 = pointE + VECTOR2I(wxPoint(int(vecT2[0]*-0.15*w2), int(vecT2[1]*-0.15*w2)))#  + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointD = end2 + VECTOR2I(wxPoint(int(vecT2[0]*-0.5*w2) , int(vecT2[1]*-0.5*w2))) + VECTOR2I(wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2)))
    else: # kv8
        pointC = end2 + VECTOR2I(int(vecC[0] * w2), int(vecC[1] * w2)) + VECTOR2I(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointE = end2 + VECTOR2I(int(vecE[0] * w2), int(vecE[1] * w2)) + VECTOR2I(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        end2_shift = end2 + VECTOR2I(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointC2 = pointC + VECTOR2I(int(vecT2[0]*-0.15*w2), int(vecT2[1]*-0.15*w2))#  + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointE2 = pointE + VECTOR2I(int(vecT2[0]*-0.15*w2), int(vecT2[1]*-0.15*w2))#  + wxPoint(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
        pointD = end2 + VECTOR2I(int(vecT2[0]*-0.5*w2) , int(vecT2[1]*-0.5*w2)) + VECTOR2I(int(vecT2[0]*-idm2*w1*shift2), int(vecT2[1]*-idm2*w1*shift2))
    
    pts = [pointA, pointB, pointC, pointD, pointE]
    if segs > 2:
        # curve1 = __Bezier(pts[1], tangentB, tangentC, pts[2], n=segs)
        # curve2 = __Bezier(pts[4], tangentE, tangentA, pts[0], n=segs)
        # return curve1 + [pts[3]] + curve2
        #curve1, curve2 = __ComputeCurvedTracks(vpercent, w1, vecT1, w2, end2, pts, segs)
        curve1, curve2 = __ComputeCurvedTracks(vpercent, w1, vecT1, w2, end2_shift, pts, segs)
        ##pts = __ComputeCurvedTracks(vpercent, w1, vecT1, w2, end2, pts, segs)
        #pts = __ComputeCurved(vpercent, w, vecT, via, pts, segs)
        ##pts = [pointF]+pts
        pts = curve1+[pointC]+[pointC2,pointD,pointE2]+curve2+[pointA2,pointF,pointB2]
        wxLogDebug('point A:  '+str(ToMM(pointA.x))+','+str(ToMM(pointA.y)),dbg)
        wxLogDebug('point B:  '+str(ToMM(pointB.x))+','+str(ToMM(pointB.y)),dbg)
        wxLogDebug('point A2: '+str(ToMM(pointA2.x))+','+str(ToMM(pointA2.y)),dbg)
        wxLogDebug('point B2: '+str(ToMM(pointB2.x))+','+str(ToMM(pointB2.y)),dbg)
        wxLogDebug('point F:  '+str(ToMM(pointF.x))+','+str(ToMM(pointF.y)),dbg)
        wxLogDebug('point C:  '+str(ToMM(pointC.x))+','+str(ToMM(pointB.y)),dbg)
        wxLogDebug('point E:  '+str(ToMM(pointE.x))+','+str(ToMM(pointE.y)),dbg)
        wxLogDebug('point C2: '+str(ToMM(pointC2.x))+','+str(ToMM(pointC2.y)),dbg)
        wxLogDebug('point E2: '+str(ToMM(pointE2.x))+','+str(ToMM(pointE2.y)),dbg)
        wxLogDebug('point D:  '+str(ToMM(pointD.x))+','+str(ToMM(pointC.y)),dbg)
    return pts
##
##

def __IsArcTrack(track):
    return hasattr(pcbnew, 'PCB_ARC') and type(track) is pcbnew.PCB_ARC


def __InterpolateQuadratic(p0, p1, p2, n_pts):
    pts = []
    for i in range(n_pts):
        t = i / float(max(1, n_pts - 1))
        omt = 1.0 - t
        x = omt * omt * p0[0] + 2.0 * omt * t * p1[0] + t * t * p2[0]
        y = omt * omt * p0[1] + 2.0 * omt * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def __SampleTrackCenterline(track, from_start, segs):
    start = __PointTuple(track.GetStart())
    end = __PointTuple(track.GetEnd())
    if __IsArcTrack(track) and hasattr(track, 'GetMid'):
        mid = __PointTuple(track.GetMid())
        sample_count = max(6, int(segs) * 2)
        pts = __InterpolateQuadratic(start, mid, end, sample_count)
    else:
        pts = [start, end]
    return pts if from_start else list(reversed(pts))


def __BuildTrackChainCenterline(tracks, segs):
    if len(tracks) < 2:
        return None, 'Select at least 2 connected tracks.'

    net_code = tracks[0].GetNetCode()
    layer = tracks[0].GetLayer()
    for t in tracks:
        if t.GetNetCode() != net_code or t.GetLayer() != layer:
            return None, 'Selected tracks must share same net and layer.'

    endpoint_map = {}
    for t in tracks:
        s = __PointTuple(t.GetStart())
        e = __PointTuple(t.GetEnd())
        if s == e:
            continue
        endpoint_map.setdefault(s, []).append(t)
        endpoint_map.setdefault(e, []).append(t)

    if len(endpoint_map) < 2:
        return None, 'Unable to extract a track trajectory.'

    branch_nodes = [node for node, edges in endpoint_map.items() if len(edges) > 2]
    if branch_nodes:
        return None, 'Branching selections are not supported. Select a single line chain.'

    ends = [node for node, edges in endpoint_map.items() if len(edges) == 1]
    if len(ends) != 2:
        return None, 'Selection must form one open connected line (not a loop).'

    widths = [float(t.GetWidth()) / 2.0 for t in tracks]
    max_w = max(widths)
    min_w = min(widths)

    end_w0 = float(endpoint_map[ends[0]][0].GetWidth()) / 2.0
    end_w1 = float(endpoint_map[ends[1]][0].GetWidth()) / 2.0
    if end_w0 >= end_w1:
        start_node = ends[0]
        end_node = ends[1]
    else:
        start_node = ends[1]
        end_node = ends[0]

    visited_keys = set()
    track_infos = []

    def track_key(track):
        if hasattr(track, 'm_Uuid') and hasattr(track.m_Uuid, 'AsString'):
            return track.m_Uuid.AsString()
        return id(track)

    centerline = [start_node]
    current_node = start_node

    while current_node != end_node:
        candidates = [t for t in endpoint_map[current_node] if track_key(t) not in visited_keys]
        if len(candidates) == 0:
            return None, 'Track chain is disconnected or ambiguous.'
        track = candidates[0]
        visited_keys.add(track_key(track))

        track_start_index = len(centerline) - 1

        s = __PointTuple(track.GetStart())
        e = __PointTuple(track.GetEnd())
        from_start = (current_node == s)
        next_node = e if from_start else s

        sampled = __SampleTrackCenterline(track, from_start, segs)
        if len(sampled) > 1:
            if __TupleDistance(centerline[-1], sampled[0]) <= 1.0:
                centerline.extend(sampled[1:])
            else:
                centerline.extend(sampled)

        track_end_index = len(centerline) - 1
        track_infos.append({
            'is_arc': __IsArcTrack(track),
            'start_index': track_start_index,
            'end_index': track_end_index,
            'half_width': float(track.GetWidth()) / 2.0,
        })
        current_node = next_node

    if len(visited_keys) != len(tracks):
        return None, 'Selection includes disconnected tracks. Select one continuous line.'

    return {
        'centerline': centerline,
        'max_w': max_w,
        'min_w': min_w,
        'track_infos': track_infos,
    }, None


def __BuildVariableWidthOutline(centerline, start_half_width, end_half_width):
    if len(centerline) < 2:
        return []

    cumulative = [0.0]
    total_len = 0.0
    for i in range(1, len(centerline)):
        total_len += __TupleDistance(centerline[i], centerline[i-1])
        cumulative.append(total_len)

    if total_len <= EPSILON:
        return []

    left = []
    right = []
    prev_normal = (0.0, 1.0)
    for i, point in enumerate(centerline):
        if i == 0:
            direction = (centerline[1][0] - point[0], centerline[1][1] - point[1])
        elif i == len(centerline) - 1:
            direction = (point[0] - centerline[i-1][0], point[1] - centerline[i-1][1])
        else:
            direction = (centerline[i+1][0] - centerline[i-1][0], centerline[i+1][1] - centerline[i-1][1])

        dnorm = sqrt(direction[0] * direction[0] + direction[1] * direction[1])
        if dnorm <= EPSILON:
            nx, ny = prev_normal
        else:
            nx, ny = (-direction[1] / dnorm, direction[0] / dnorm)
            prev_normal = (nx, ny)

        ratio = cumulative[i] / total_len
        half_w = start_half_width + (end_half_width - start_half_width) * ratio

        left.append((point[0] + nx * half_w, point[1] + ny * half_w))
        right.append((point[0] - nx * half_w, point[1] - ny * half_w))

    outline = left + list(reversed(right))

    compact = []
    for pt in outline:
        if not compact or __TupleDistance(pt, compact[-1]) > 1.0:
            compact.append(pt)

    return [__MakePoint(pt[0], pt[1]) for pt in compact]


def __ComputePointsTrackChain(tracks, segs, emit_errors=True):
    chain_data, err = __BuildTrackChainCenterline(tracks, segs)
    if chain_data is None:
        if emit_errors:
            wx.LogMessage(err)
        return False

    centerline = chain_data['centerline']
    track_infos = chain_data.get('track_infos', [])

    # If the first traversed segment is an arc, start tapering from the very tip
    # (the end junction of the first arc), not from any arc span.
    if len(track_infos) > 1 and track_infos[0]['is_arc']:
        first = track_infos[0]
        new_start = first['end_index']
        if new_start < len(centerline) - 1:
            centerline = centerline[new_start:]

    start_w = chain_data['max_w']
    end_w = chain_data['min_w']
    return __BuildVariableWidthOutline(centerline, start_w, end_w)


def SetTaper_Zone(pcb=None, use_dialog=True):
    """Set tapers for track-pad, track-track, or connected track chains"""
    if pcb is None:
        pcb = GetBoard()

    settings = __GetTaperSettings()
    if use_dialog:
        user_settings = __ShowTaperSettingsDialog(settings)
        if user_settings is None:
            return
        if user_settings.get('action') == 'remove':
            count = RmTapers(pcb)
            wx.LogMessage('Removed ' + str(count) + ' Tapers')
            return
        settings.update(user_settings)
        __SaveTaperSettings(settings)
    else:
        settings['action'] = 'apply'

    segs = settings['segments']
    length_factor = settings['length_factor']
    fixed_length_iu = settings['fixed_length_iu']

    selPads = Layout.get_selected_pads()
    selTracks = Layout.get_selected_tracks()

    # taper btw pad & track
    if len(selTracks) == 1 and len(selPads) == 1:
        pad = selPads[0]
        track = selTracks[0]
        coor = __ComputePoints(track, pad, segs, length_factor, fixed_length_iu)
        if coor:
            pcb.Add(__Zone(pcb, coor, track, settings))
            RebuildAllZones(pcb)
    elif len(selTracks) == 2 and len(selPads) == 0:
        # Prefer full trajectory taper when 2 selected tracks form a connected path.
        # Fallback to legacy 2-track join taper for nearby/non-chain selections.
        coor = __ComputePointsTrackChain(selTracks, segs, emit_errors=False)
        if coor:
            pcb.Add(__Zone(pcb, coor, selTracks[0], settings))
            RebuildAllZones(pcb)
            return

        track1 = selTracks[0]
        track2 = selTracks[1]
        coor = __ComputePointsTracks(track1, track2, segs, length_factor, fixed_length_iu)
        if coor:
            pcb.Add(__Zone(pcb, coor, track1, settings))
            RebuildAllZones(pcb)
    elif len(selTracks) >= 3 and len(selPads) == 0:
        coor = __ComputePointsTrackChain(selTracks, segs)
        if coor:
            pcb.Add(__Zone(pcb, coor, selTracks[0], settings))
            RebuildAllZones(pcb)
    # square taper at the end of a track
    elif len(selTracks) == 1 and len(selPads) == 0:
        track = selTracks[0]
        start = track.GetStart()
        end = track.GetEnd()
        for t in pcb.GetTracks():
            if not(t.IsSelected()):
                if track.GetStart() == t.GetStart():
                    start = track.GetEnd()
                    end = track.GetStart()
                    break
                elif track.GetEnd() == t.GetStart():
                    start = track.GetStart()
                    end = track.GetEnd()
                    break
                elif track.GetStart() == t.GetEnd():
                    start = track.GetEnd()
                    end = track.GetStart()
                    break
                elif track.GetEnd() == t.GetEnd():
                    start = track.GetStart()
                    end = track.GetEnd()
                    break
        w = track.GetWidth()/2
        n = w
        vecT = __NormalizeVector(end - start)
        if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
            pointB = start + wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
            pointA = start + wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w )
            pointD = start - wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
            pointC = start - wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w )
        elif hasattr(pcbnew, 'wxPoint()'): #kv7
            pointB = start + VECTOR2I(wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w ))
            pointA = start + VECTOR2I(wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w ))
            pointD = start - VECTOR2I(wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w ))
            pointC = start - VECTOR2I(wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w ))
        else: #kv8
            pointB = start + VECTOR2I(int( vecT[0]*n +vecT[1]*w) , int(vecT[1]*n -vecT[0]*w ))
            pointA = start + VECTOR2I(int( vecT[0]*n -vecT[1]*w) , int(vecT[1]*n +vecT[0]*w ))
            pointD = start - VECTOR2I(int( vecT[0]*n +vecT[1]*w ), int(vecT[1]*n -vecT[0]*w ))
            pointC = start - VECTOR2I(int( vecT[0]*n -vecT[1]*w) , int(vecT[1]*n +vecT[0]*w ))
        points = [pointA,pointB,pointC,pointD]
        pcb.Add(__Zone(pcb, points, track, settings))
        RebuildAllZones(pcb)
    else:
        wx.LogMessage('Select one mode:\n- 1 track + 1 pad\n- 2 nearby tracks\n- 3+ connected tracks (trajectory taper)\n- 1 track for square end taper')
    
##
#
class Layout:
    """
    Class for common Pcbnew layout operations.
    """
    @staticmethod
    def get_selected_pads(board=None):
        if board is None:
            board = pcbnew.GetBoard()
        
        return list(filter(lambda p: p.IsSelected(), board.GetPads()))

    @staticmethod
    def get_selected_tracks(board=None):
        if board is None:
            board = pcbnew.GetBoard()

        selected = []
        if hasattr(pcbnew, 'TRACK'):
            track_item = pcbnew.TRACK
            arc_item = None
        else:
            track_item = pcbnew.PCB_TRACK
            arc_item = pcbnew.PCB_ARC if hasattr(pcbnew, 'PCB_ARC') else None

        for t in board.GetTracks():
            if not t.IsSelected():
                continue
            if type(t) is track_item or (arc_item is not None and type(t) is arc_item):
                selected.append(t)

        return selected
    
#
def RebuildAllZones(pcb):
    """Rebuilt all zones"""
    filler = ZONE_FILLER(pcb)
    filler.Fill(pcb.Zones())

#
def __GetAllTapers(board):
    """Just retrieves all teardrops of the current board classified by net"""
    tapers_zones = {}
    for zone in [board.GetArea(i) for i in range(board.GetAreaCount())]:
        if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
            zGA = zone.GetPriority()
        else: #kv7
            zGA = zone.GetAssignedPriority()
        if zGA == MAGIC_TAPER_ZONE_ID:
            netname = zone.GetNetname()
            if netname not in tapers_zones.keys():
                tapers_zones[netname] = []
            tapers_zones[netname].append(zone)
    return tapers_zones
#
def RmTapers(pcb=None):
    """Remove all tapers"""

    if pcb is None:
        pcb = GetBoard()

    count = 0
    tapers = __GetAllTapers(pcb)
    for netname in tapers:
        for taper in tapers[netname]:
            pcb.Remove(taper)
            count += 1

    RebuildAllZones(pcb)
    #print('{0} tapers removed'.format(count))
    return count
