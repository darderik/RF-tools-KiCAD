#!/usr/bin/env python

# Implementation of the action plugin derived from pcbnew.ActionPlugin
import pcbnew
import os
import sys
import re
import time
import json
import math
import wx
import uuid
import random
import configparser

from collections import OrderedDict
from .viafence import *
from .viafence_dialogs import *

debug = False  # Set to True to see detailed filtering logs
temporary_fix = True

def wxLogDebug(msg,show):
    """printing messages only if show is omitted or True"""
    if show:
        wx.LogMessage(msg)
# 
def getTrackAngleRadians(track):
    #return math.degrees(math.atan2((p1.y-p2.y),(p1.x-p2.x)))
    return (math.atan2((track.GetEnd().y - track.GetStart().y), (track.GetEnd().x - track.GetStart().x)))
#

def distance (p1,p2):
    return math.hypot(p1.y-p2.y,p1.x-p2.x)

# De-duplicate a list of [x, y] points using a distance tolerance (internal units)
# Keeps the first point encountered and removes subsequent points closer than tol
# This is used to avoid overlapping vias when multiple fence parts touch at endpoints
# and should run regardless of DRC-collision removal setting.
def dedupe_points(points, tol):
    unique = []
    for v in points:
        vx, vy = int(v[0]), int(v[1])
        keep = True
        for u in unique:
            if distance(pcbnew.wxPoint(vx, vy), pcbnew.wxPoint(int(u[0]), int(u[1]))) <= tol:
                keep = False
                break
        if keep:
            unique.append(v)
    return unique

# Geometry helpers for precise overlap tests (user request: avoid overlapping pads/traces, allow proximity and same-net zones)
# Internal units.

def point_segment_distance(point, start, end):
    dx = end.x - start.x
    dy = end.y - start.y
    if dx == 0 and dy == 0:
        return distance(point, start)
    t = ((point.x - start.x) * dx + (point.y - start.y) * dy) / float(dx*dx + dy*dy)
    t = max(0.0, min(1.0, t))
    cx = start.x + t * dx
    cy = start.y + t * dy
    return math.hypot(point.x - cx, point.y - cy)

def via_track_overlaps(via_pos, via_diam, track, clearance):
    # Check if via overlaps with track copper area
    # Returns True if via annular ring intersects track copper
    via_pt = pcbnew.wxPoint(int(via_pos[0]), int(via_pos[1]))
    start = track.GetStart()
    end = track.GetEnd()
    track_half = track.GetWidth() / 2.0
    via_radius = via_diam / 2.0
    d = point_segment_distance(via_pt, start, end)
    # Add clearance tolerance; use 10% for better safety margin on discretized curves
    tol = via_diam * 0.1
    # Overlap if center distance is less than track half-width + via radius + clearance
    return d < (track_half + via_radius + clearance + tol)

def via_pad_overlaps(via_pos, via_diam, pad, clearance):
    # Simplified: treat pad as rectangle (or oval) bounding box and test center distance against half-diagonal + via radius
    via_pt = pcbnew.wxPoint(int(via_pos[0]), int(via_pos[1]))
    pad_center = pad.GetPosition()
    size = pad.GetSize()
    # Use worst case radius (half diagonal) to be conservative
    pad_rx = size.x / 2.0
    pad_ry = size.y / 2.0
    pad_radius = math.hypot(pad_rx, pad_ry)  # inscribed circle of bounding box diagonal / 2
    via_radius = via_diam / 2.0
    d = distance(via_pt, pad_center)
    tol = via_diam * 0.05
    return d < (pad_radius + via_radius + clearance + tol)

# New helper: via-via overlap
def via_via_overlaps(via_pos, new_via_diam, existing_via, clearance):
    center2 = existing_via.GetPosition()
    via_pt = pcbnew.wxPoint(int(via_pos[0]), int(via_pos[1]))
    r_new = new_via_diam / 2.0
    r_old = existing_via.GetWidth() / 2.0
    d = distance(via_pt, center2)
    tol = new_via_diam * 0.05
    return d < (r_new + r_old + clearance + tol)

class ViaFenceAction(pcbnew.ActionPlugin):
    # ActionPlugin descriptive information
    def defaults(self):
        self.name = "Via Fence Generator\nversion 3.2"
        self.category = "Modify PCB"
        self.description = "Add a via fence to nets or tracks on the board"
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources/fencing-vias.png")
        self.show_toolbar_button = True

    def dumpJSON(self, file):
        dict = {
            'pathList': self.pathList, 
            'viaOffset': self.viaOffset, 
            'viaPitch': self.viaPitch, 
            'viaPoints': self.viaPoints if hasattr(self, 'viaPoints') else []
        }
        with open(file, 'w') as file:
            json.dump(dict, file, indent=4, sort_keys=True)

    # Return an ordered {layerId: layerName} dict of enabled layers
    def getLayerMap(self):
        layerMap = []
        for i in list(range(pcbnew.PCB_LAYER_ID_COUNT)):
            if self.boardObj.IsLayerEnabled(i):
                layerMap += [[i, self.boardObj.GetLayerName(i)]]
        return OrderedDict(layerMap)

    # Return an ordered {netCode: netName} dict of nets in the board
    def getNetMap(self):
        netMap = OrderedDict(self.boardObj.GetNetsByNetcode())
        netMap.pop(0) # TODO: What is Net 0?
        return netMap

    # Generates a list of net filter phrases using the local netMap
    # Currently all nets are included as filter phrases
    # Additionally, differential Nets get a special filter phrase
    def createNetFilterSuggestions(self):
        netFilterList = ['*']
        netList = [self.netMap[item].GetNetname() for item in self.netMap]
        diffMap = {'+': '-', 'P': 'N', '-': '+', 'N': 'P'}
        regexMap = {'+': '[+-]', '-': '[+-]', 'P': '[PN]', 'N': '[PN]'}
        invertDiffNet = lambda netName : netName[0:-1] + diffMap[netName[-1]]
        isDiffNet = lambda netName : True if netName[-1] in diffMap.keys() else False

        # Translate board nets into a filter list
        for netName in netList:
            if isDiffNet(netName) and invertDiffNet(netName) in netList:
                # If we have a +/- or P/N pair, we insert a regex entry once into the filter list
                filterText = netName[0:-1] + regexMap[netName[-1]]
                if (filterText not in netFilterList): netFilterList += [filterText]

            # Append every net to the filter list
            netFilterList += [netName]

        return netFilterList

    # Generates a RegEx string from a SimpleEx (which is a proprietary invention ;-))
    # The SimpleEx only supports [...] with single chars and * used as a wildcard
    def regExFromSimpleEx(self, simpleEx):
        # Escape the entire filter string. Unescape and remap specific characters that we want to allow
        subsTable = {r'\[':'[', r'\]':']', r'\*':'.*'}
        regEx = re.escape(simpleEx)
        for subsFrom, subsTo in subsTable.items(): regEx = regEx.replace(subsFrom, subsTo)
        return regEx

    def createVias(self, viaPoints, viaDrill, viaSize, netCode):
        newVias = []
        for viaPoint in viaPoints:
            if not(hasattr(pcbnew,'DRAWSEGMENT')):
                newVia = pcbnew.PCB_VIA(self.boardObj)
            else:
                newVia = pcbnew.VIA(self.boardObj)
            if hasattr(newVia, 'SetTimeStamp'):
                ts = 55
                newVia.SetTimeStamp(ts)  # adding a unique number as timestamp to mark this via as generated by this script
            self.boardObj.Add(newVia)

            if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
                newVia.SetPosition(pcbnew.wxPoint(viaPoint[0], viaPoint[1]))
            elif hasattr(pcbnew, 'wxPoint()'): # kv7
                newVia.SetPosition(pcbnew.VECTOR2I(pcbnew.wxPoint(viaPoint[0], viaPoint[1])))
            else: #kv8
                newVia.SetPosition(pcbnew.VECTOR2I(int(viaPoint[0]), int(viaPoint[1])))
            newVia.SetWidth(viaSize)
            newVia.SetDrill(viaDrill)
            if hasattr(pcbnew, 'VIA_THROUGH'):
                newVia.SetViaType(pcbnew.VIA_THROUGH)
            else:
                newVia.SetViaType(pcbnew.VIATYPE_THROUGH)
            newVia.SetNetCode(netCode)
            newVias += [newVia]

        return newVias

    def onDeleteClick(self, event):
        return self.mainDlg.EndModal(wx.ID_DELETE)
    
    def checkPads(self):
    ##Check vias collisions with all pads => all pads on all layers (remove any overlap regardless of net)
        # Get DRC clearance - KiCad 9 uses GetClearanceConstraint
        design_settings = self.boardObj.GetDesignSettings()
        try:
            # Try KiCad 9 API first
            clearance = design_settings.GetClearanceConstraint()
        except AttributeError:
            try:
                # Try KiCad 5-8 API
                clearance = design_settings.GetDefault().GetClearance()
            except AttributeError:
                # Fallback to 0
                clearance = 0
        viasToRemove = []
        removed = False
        for pad in self.boardObj.GetPads():
            for viaPos in self.viaPointsSafe:
                try:
                    if via_pad_overlaps(viaPos, self.viaSize, pad, self.clearance):
                        wxLogDebug('Pad overlap -> removing via at {}'.format(viaPos), debug)
                        viasToRemove.append(viaPos)
                        removed = True
                except Exception as exc:
                    wxLogDebug('Pad check exception: {}'.format(exc), debug)
        if viasToRemove:
            self.viaPointsSafe = [p for p in self.viaPointsSafe if p not in viasToRemove]
        return removed

    def checkTracks(self):
    ##Check vias collisions with tracks (avoid overlapping copper on all nets)
        # Get DRC clearance - KiCad 9 uses GetClearanceConstraint
        design_settings = self.boardObj.GetDesignSettings()
        try:
            # Try KiCad 9 API first
            self.clearance = design_settings.GetClearanceConstraint()
        except AttributeError:
            try:
                # Try KiCad 5-8 API
                self.clearance = design_settings.GetDefault().GetClearance()
            except AttributeError:
                # Fallback to 0
                self.clearance = 0
        viasToRemove = []
        removed = False
        if (hasattr(pcbnew,'DRAWSEGMENT')):
            trk_type = pcbnew.TRACK
        else:
            trk_type = pcbnew.PCB_TRACK
        for track in self.boardObj.GetTracks():
            if type(track) != trk_type:
                continue
            for viaPos in self.viaPointsSafe:
                try:
                    # Apply clearance to same-net traces too (0.5mm minimum for safety)
                    # Different nets get full DRC clearance
                    if track.GetNetCode() == self.viaNetId:
                        # Same net: use minimum 0.5mm clearance to avoid sitting on trace
                        min_same_net_clearance = max(pcbnew.FromMM(0.5), self.clearance // 2)
                        extra_clearance = min_same_net_clearance
                    else:
                        # Different net: use full DRC clearance
                        extra_clearance = self.clearance
                    if via_track_overlaps(viaPos, self.viaSize, track, extra_clearance):
                        wxLogDebug('Track overlap(net:{} viaNet:{} clearance:{}) -> removing via {}'.format(
                            track.GetNetCode(), self.viaNetId, pcbnew.ToMM(extra_clearance), viaPos), debug)
                        viasToRemove.append(viaPos)
                        removed = True
                except Exception as exc:
                    wxLogDebug('Track check exception: {}'.format(exc), debug)
        if viasToRemove:
            self.viaPointsSafe = [p for p in self.viaPointsSafe if p not in viasToRemove]
        return removed

    # Missing earlier, define precise per-via filter now
    def filter_vias_precise(self, candidate_points):
        """Return list of via points not overlapping any pad, track, or existing via."""
        # Get DRC clearance - KiCad 9 uses GetClearanceConstraint
        design_settings = self.boardObj.GetDesignSettings()
        try:
            # Try KiCad 9 API first
            clearance = design_settings.GetClearanceConstraint()
        except AttributeError:
            try:
                # Try KiCad 5-8 API
                clearance = design_settings.GetDefault().GetClearance()
            except AttributeError:
                # Fallback to 0
                clearance = 0
        
        pads = list(self.boardObj.GetPads())
        # collect existing vias
        if hasattr(pcbnew,'VIA'):
            via_type = pcbnew.VIA
        else:
            via_type = pcbnew.PCB_VIA
        existing_vias = [t for t in self.boardObj.GetTracks() if isinstance(t, via_type)]
        if (hasattr(pcbnew,'DRAWSEGMENT')):
            trk_type = pcbnew.TRACK
        else:
            trk_type = pcbnew.PCB_TRACK
        tracks = [t for t in self.boardObj.GetTracks() if type(t) is trk_type]
        
        wxLogDebug('filter_vias_precise: Testing {} candidate vias, {} tracks, {} pads, {} existing_vias'.format(
            len(candidate_points), len(tracks), len(pads), len(existing_vias)), debug)
        
        accepted = []
        rejected_reasons = {'pad': 0, 'same_net_track': 0, 'diff_net_track': 0, 'existing_via': 0}
        
        for pt in candidate_points:
            if any(via_pad_overlaps(pt, self.viaSize, pad, clearance) for pad in pads):
                wxLogDebug('  Reject via at [{:.0f}, {:.0f}] - pad overlap'.format(pt[0], pt[1]), debug)
                rejected_reasons['pad'] += 1
                continue
            # Apply same clearance logic as checkTracks: same-net gets 0.5mm min, different nets get full DRC
            reject_track = False
            for trk in tracks:
                if trk.GetNetCode() == self.viaNetId:
                    # Same net: use minimum 0.5mm clearance
                    min_same_net_clearance = max(pcbnew.FromMM(0.5), clearance // 2)
                    if via_track_overlaps(pt, self.viaSize, trk, min_same_net_clearance):
                        wxLogDebug('  Reject via at [{:.0f}, {:.0f}] - same-net track overlap (clearance={:.2f}mm)'.format(
                            pt[0], pt[1], pcbnew.ToMM(min_same_net_clearance)), debug)
                        rejected_reasons['same_net_track'] += 1
                        reject_track = True
                        break
                else:
                    # Different net: use full DRC clearance
                    if via_track_overlaps(pt, self.viaSize, trk, clearance):
                        wxLogDebug('  Reject via at [{:.0f}, {:.0f}] - diff-net track overlap (clearance={:.2f}mm)'.format(
                            pt[0], pt[1], pcbnew.ToMM(clearance)), debug)
                        rejected_reasons['diff_net_track'] += 1
                        reject_track = True
                        break
            if reject_track:
                continue
            if any(via_via_overlaps(pt, self.viaSize, ev, clearance) for ev in existing_vias):
                wxLogDebug('  Reject via at [{:.0f}, {:.0f}] - existing via overlap'.format(pt[0], pt[1]), debug)
                rejected_reasons['existing_via'] += 1
                continue
            accepted.append(pt)
        
        wxLogDebug('filter_vias_precise: Accepted {}/{} vias. Rejections: pad={}, same_net_track={}, diff_net_track={}, existing_via={}'.format(
            len(accepted), len(candidate_points), rejected_reasons['pad'], rejected_reasons['same_net_track'],
            rejected_reasons['diff_net_track'], rejected_reasons['existing_via']), debug)
        
        return accepted
# ------------------------------------------------------------------------------------
    
    def DoKeyPress(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN: 
            self.mainDlg.EndModal(wx.ID_OK)
        else:
            event.Skip()
    
    def selfToMainDialog(self):
        self.mainDlg.lstLayer.SetItems(list(self.layerMap.values()))  #maui
        self.mainDlg.lstLayer.SetSelection(self.layerId)
        self.mainDlg.txtNetFilter.SetItems(self.netFilterList)
        self.mainDlg.txtNetFilter.SetSelection(self.netFilterList.index(self.netFilter))
        self.mainDlg.txtViaOffset.SetValue(str(pcbnew.ToMM(self.viaOffset)))
        self.mainDlg.txtViaPitch.SetValue(str(pcbnew.ToMM(self.viaPitch)))
        # Inter-row offset defaults to viaOffset if not set
        if not hasattr(self, 'interRowOffset') or self.interRowOffset is None:
            self.interRowOffset = self.viaOffset
        self.mainDlg.txtInterRowOffset.SetValue(str(pcbnew.ToMM(self.interRowOffset)))
        self.mainDlg.txtViaDrill.SetValue(str(pcbnew.ToMM(self.viaDrill)))
        self.mainDlg.txtViaSize.SetValue(str(pcbnew.ToMM(self.viaSize)))
        self.mainDlg.spnFenceRows.SetValue(self.fenceRows)
        self.mainDlg.txtViaOffset.Bind(wx.EVT_KEY_DOWN, self.DoKeyPress)
        #self.mainDlg.txtViaOffset.Bind(wx.EVT_TEXT_ENTER, self.mainDlg.EndModal(wx.ID_OK))
        self.mainDlg.txtViaPitch.Bind(wx.EVT_KEY_DOWN, self.DoKeyPress)
        self.mainDlg.txtViaDrill.Bind(wx.EVT_KEY_DOWN, self.DoKeyPress)
        self.mainDlg.txtViaSize.Bind(wx.EVT_KEY_DOWN, self.DoKeyPress)
        
        self.mainDlg.lstViaNet.SetItems([item.GetNetname() for item in self.netMap.values()])
        for i, item  in enumerate (self.netMap.values()):
            if self.mainDlg.lstViaNet.GetString(i) in ["GND", "/GND"]:
                self.mainDlg.lstViaNet.SetSelection(i)
                break
        if not(hasattr(pcbnew,'DRAWSEGMENT')) and temporary_fix: #temporary_fix!!!
            self.mainDlg.chkNetFilter.Enable (False)
        self.mainDlg.chkNetFilter.SetValue(self.isNetFilterChecked)
        self.mainDlg.txtNetFilter.Enable(self.isNetFilterChecked)
        self.mainDlg.chkLayer.SetValue(self.isLayerChecked)
        self.mainDlg.lstLayer.Enable(self.isLayerChecked)
        self.mainDlg.chkIncludeDrawing.SetValue(self.isIncludeDrawingChecked)
        self.mainDlg.chkIncludeSelection.SetValue(self.isIncludeSelectionChecked)
        self.mainDlg.chkDebugDump.SetValue(self.isDebugDumpChecked)
        self.mainDlg.chkRemoveViasWithClearanceViolation.SetValue(self.isRemoveViasWithClearanceViolationChecked)
        self.mainDlg.chkSameNetZoneViasOnly.SetValue(self.isSameNetZoneViasOnlyChecked)
        self.mainDlg.m_buttonDelete.Bind(wx.EVT_BUTTON, self.onDeleteClick)
        # hiding unimplemented controls
        #self.mainDlg.chkRemoveViasWithClearanceViolation.Hide()
        self.mainDlg.chkSameNetZoneViasOnly.Hide()

    def mainDialogToSelf(self):
        self.netFilter = self.mainDlg.txtNetFilter.GetValue()
        if len(list(self.layerMap.keys())) > 0:
            self.layerId = list(self.layerMap.keys())[self.mainDlg.lstLayer.GetSelection()]   #maui
        self.viaOffset = pcbnew.FromMM(float(self.mainDlg.txtViaOffset.GetValue().replace(',','.')))
        self.viaPitch = pcbnew.FromMM(float(self.mainDlg.txtViaPitch.GetValue().replace(',','.')))
        self.interRowOffset = pcbnew.FromMM(float(self.mainDlg.txtInterRowOffset.GetValue().replace(',','.')))
        self.viaDrill = pcbnew.FromMM(float(self.mainDlg.txtViaDrill.GetValue().replace(',','.')))
        self.viaSize = pcbnew.FromMM(float(self.mainDlg.txtViaSize.GetValue().replace(',','.')))
        self.fenceRows = self.mainDlg.spnFenceRows.GetValue()
        if len(list(self.netMap.keys())) > 0:
            self.viaNetId = list(self.netMap.keys())[self.mainDlg.lstViaNet.GetSelection()]   #maui
        self.isNetFilterChecked = self.mainDlg.chkNetFilter.GetValue()
        self.isLayerChecked = self.mainDlg.chkLayer.GetValue()
        self.isIncludeDrawingChecked = self.mainDlg.chkIncludeDrawing.GetValue()
        self.isIncludeSelectionChecked = self.mainDlg.chkIncludeSelection.GetValue()
        self.isDebugDumpChecked = self.mainDlg.chkDebugDump.GetValue()
        self.isSameNetZoneViasOnlyChecked = self.mainDlg.chkSameNetZoneViasOnly.GetValue()
        self.isRemoveViasWithClearanceViolationChecked = self.mainDlg.chkRemoveViasWithClearanceViolation.GetValue()

    def Run(self):
        #check for pyclipper lib
        pyclip = False
        try:
            import pyclipper  # runtime import; may not resolve in static analysis
            pyclip = True
        except Exception:
            import sys, os
            from sys import platform as _platform
            if sys.version_info.major == 2 and sys.version_info.minor == 7:
                if _platform == "linux" or _platform == "linux2":
                    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'python-pyclipper', 'py2-7-linux-64'))
                elif _platform == "darwin":
                    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'python-pyclipper', 'py2-7-mac-64'))
                else:
                    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'python-pyclipper', 'py2-7-win-64'))
            try:
                import pyclipper
                pyclip = True
            except Exception:
                msg = u"\u2718 ERROR Missing KiCAD 'pyclipper' python module:\nplease install it using pip\nin your KiCAD python environment.\n[You may need administrative rights]"
                wdlg = wx.MessageDialog(None, msg, 'ERROR message', wx.OK | wx.ICON_WARNING)
                wdlg.ShowModal()
        if pyclip:
            import os
            import random, string
            def randomword(length):
                letters = string.ascii_lowercase
                return ''.join(random.choice(letters) for _ in range(length))
            def randomnum(length):
                return ''.join(random.sample('0123456789', length))
            self.boardObj = pcbnew.GetBoard()
            self.boardDesignSettingsObj = self.boardObj.GetDesignSettings()
            self.boardPath = os.path.dirname(os.path.realpath(self.boardObj.GetFileName()))
            self.layerMap = self.getLayerMap()
            if not(hasattr(pcbnew,'DRAWSEGMENT')) and temporary_fix:
                self.highlightedNetId = -1
            else:
                self.highlightedNetId = self.boardObj.GetHighLightNetCode()
            self.netMap = self.getNetMap()
            self.netFilterList = self.createNetFilterSuggestions()
            self.netFilter = self.netMap[self.highlightedNetId].GetNetname() if self.highlightedNetId != -1 else self.netFilterList[0]
            self.viaSize = self.boardDesignSettingsObj.GetCurrentViaSize()
            self.layerId = 0
            self.viaDrill = self.boardDesignSettingsObj.GetCurrentViaDrill()
            self.viaPitch = pcbnew.FromMM(1.3)
            self.viaOffset = pcbnew.FromMM(1.3)
            self.fenceRows = 1  # Rows per side
            self.viaNetId = 0
            self.isNetFilterChecked = 1 if self.highlightedNetId != -1 else 0
            self.isLayerChecked = 0
            self.isIncludeDrawingChecked = 0
            self.isIncludeSelectionChecked = 1
            self.isDebugDumpChecked = 0
            self.isRemoveViasWithClearanceViolationChecked = 1
            self.isSameNetZoneViasOnlyChecked = 0
            self.mainDlg = MainDialog(None)
            self.selfToMainDialog()
            self.local_config_file = os.path.join(os.path.dirname(__file__), 'vf_config.ini')
            config = configparser.ConfigParser()
            config.read(self.local_config_file)
            if hasattr(self.boardObj, 'm_Uuid'):
                self.mainDlg.m_buttonDelete.Disable()
                self.mainDlg.m_buttonDelete.SetToolTip( u"fencing vias are placed in a group,\nto delete fencing vias, just delete the group" )
            reply = self.mainDlg.ShowModal()
            if (reply == wx.ID_OK):
                self.mainDialogToSelf()
                lineObjects = []
                arcObjects = []
                pcb_group = None  # ensure defined
                if not(hasattr(pcbnew,'DRAWSEGMENT')):
                    VIA_GROUP_NAME = "ViaFencing_{}".format(randomnum(3))
                    pcb_group = pcbnew.PCB_GROUP(None)
                    pcb_group.SetName(VIA_GROUP_NAME)
                    self.boardObj.Add(pcb_group)
                viaPointsArcsAll = []
                if (self.isNetFilterChecked):
                    netRegex = self.regExFromSimpleEx(self.netFilter)
                    for netId in self.netMap:
                        if re.match(netRegex, self.netMap[netId].GetNetname()):
                            for trackObject in self.boardObj.TracksInNet(netId):
                                if (hasattr(pcbnew,'DRAWSEGMENT')):
                                    trk_type = pcbnew.TRACK
                                else:
                                    trk_type = pcbnew.PCB_TRACK
                                    trk_arc = pcbnew.PCB_ARC
                                if hasattr(trackObject,'GetMid()'):
                                    arcObjects += [trackObject]
                                elif type(trackObject) is trk_type:
                                    lineObjects += [trackObject]
                if (self.isIncludeDrawingChecked):
                    boardItems = []  # predefine to silence potential unbound warning
                    if hasattr(self.boardObj.GetDrawings, 'GetFirst'):
                        boardItem = self.boardObj.GetDrawings().GetFirst()
                    else:
                        self.boardObj.GetDrawings().sort
                        boardItems = self.boardObj.GetDrawings()
                        boardItem = boardItems[0] if boardItems else None
                    i = 0
                    while boardItem is not None:
                        if hasattr(pcbnew,'DRAWSEGMENT'):
                            res = pcbnew.DRAWSEGMENT.ClassOf(boardItem)
                        else:
                            res = pcbnew.PCB_SHAPE().ClassOf(boardItem)
                        if res:
                            # A drawing segment (not a text or something else)
                            drawingObject = boardItem.Cast()
                            if drawingObject.GetShape() == pcbnew.S_SEGMENT:
                                # A straight line
                                lineObjects += [drawingObject]
                        if hasattr(pcbnew,'DRAWSEGMENT'):
                            boardItem = boardItem.Next()
                        else:
                            if i < len(boardItems) - 1:
                                i += 1
                                boardItem = boardItems[i]
                            else:
                                boardItem = None
                if (self.isIncludeSelectionChecked):
                    if (hasattr(pcbnew,'DRAWSEGMENT')):
                        trk_type = pcbnew.TRACK
                        trk_arc = None
                    else:
                        trk_type = pcbnew.PCB_TRACK
                        trk_arc = pcbnew.PCB_ARC
                    for item in self.boardObj.GetTracks():
                        if trk_arc and type(item) is trk_arc and item.IsSelected():
                            arcObjects += [item]
                        if type(item) is trk_type and item.IsSelected():
                            lineObjects += [item]
                if (self.isLayerChecked):
                    lineObjects = [lo for lo in lineObjects if lo.IsOnLayer(self.layerId)]
                    arcObjects = [ao for ao in arcObjects if ao.IsOnLayer(self.layerId)]
                for arc in arcObjects:
                    start = arc.GetStart(); end = arc.GetEnd(); md = arc.GetMid(); width = arc.GetWidth(); layer = arc.GetLayerSet(); netName = None
                    cnt, rad = getCircleCenterRadius(start, end, md)
                    # Calculate arc angle
                    a1 = math.atan2(float(start.y - cnt.y), float(start.x - cnt.x))
                    a2 = math.atan2(float(end.y - cnt.y), float(end.x - cnt.x))
                    arc_angle = abs(a2 - a1)
                    if arc_angle > math.pi:
                        arc_angle = 2 * math.pi - arc_angle
                    # Use adaptive segmentation: 0.1mm max deviation for tight serpentine curves
                    segNBR = calculate_adaptive_segments(rad, arc_angle, max_deviation_mm=0.1, min_segments=16)
                    pts = create_round_pts(start, end, cnt, rad, layer, width, netName, segNBR)
                    self.pathListArcs = [[[p.x, p.y], [pts[i+1].x, pts[i+1].y]] for i, p in enumerate(pts[:-1])]
                    try:
                        if len(arcObjects) > 0:
                            viaPointsArcs = generateViaFenceMultiRow(self.pathListArcs, self.viaOffset, self.viaPitch,
                                                                      self.fenceRows, self.interRowOffset)
                            viaPointsArcsAll.extend(viaPointsArcs)
                    except Exception as exc:
                        wx.LogMessage('exception on via fence generation: {}'.format(exc))
                        import traceback; wx.LogMessage(traceback.format_exc())
                self.pathList = [[[lo.GetStart()[0], lo.GetStart()[1]], [lo.GetEnd()[0], lo.GetEnd()[1]]] for lo in lineObjects]
                try:
                    viaPoints = generateViaFenceMultiRow(self.pathList, self.viaOffset, self.viaPitch,
                                                        self.fenceRows, self.interRowOffset)
                    wxLogDebug('Generated {} vias from {} line objects ({} rows per side)'.format(
                        len(viaPoints), len(lineObjects), self.fenceRows), debug)
                except Exception as exc:
                    wx.LogMessage('exception on via fence generation: {}'.format(exc))
                    import traceback; wx.LogMessage(traceback.format_exc()); viaPoints = []
                if (self.isDebugDumpChecked):
                    self.viaPoints = viaPoints
                    self.dumpJSON(os.path.join(self.boardPath, time.strftime("viafence-%Y%m%d-%H%M%S.json")))
                combinedViaPoints = viaPoints + viaPointsArcsAll
                uniq = []
                seen = set()
                for v in combinedViaPoints:
                    key = (int(v[0]), int(v[1]))
                    if key not in seen:
                        uniq.append(v); seen.add(key)
                self.viaPointsSafe = dedupe_points(uniq, int(self.viaSize * 1.05))
                removed = False
                if (self.isRemoveViasWithClearanceViolationChecked):
                    removed = self.checkPads()
                    remvd = self.checkTracks(); removed = removed or remvd
                # Per-via final precise filtering (ensures no overlaps remain)
                before_cnt = len(self.viaPointsSafe)
                self.viaPointsSafe = self.filter_vias_precise(self.viaPointsSafe)
                if len(self.viaPointsSafe) < before_cnt:
                    removed = True
                    wxLogDebug('Filtered {} overlapping vias (precise pass)'.format(before_cnt - len(self.viaPointsSafe)), debug)
                viaObjList = self.createVias(self.viaPointsSafe, self.viaDrill, self.viaSize, self.viaNetId)
                if pcb_group is not None:
                    for v in viaObjList:
                        pcb_group.AddItem(v)
                via_nbr = len(self.viaPointsSafe)
                msg = u'Placed {0:} Fencing Vias.\n\u26A0 Please run a DRC check on your board.'.format(str(via_nbr))
                if removed:
                    msg += u'\n\u281B Removed DRC colliding vias.'
                wx.LogMessage(msg)
            elif (reply == wx.ID_DELETE):
                # Delete previous fencing vias by timestamp marker
                target_tracks = filter(lambda x: ((x.Type() == pcbnew.PCB_VIA_T) and (x.GetTimeStamp() == 55)), self.boardObj.GetTracks())
                for via in list(target_tracks):
                    self.boardObj.RemoveNative(via)
            self.local_config_file = os.path.join(os.path.dirname(__file__), 'vf_config.ini')
            config = configparser.ConfigParser(); config.read(self.local_config_file)
            config['params']['offset'] = self.mainDlg.txtViaOffset.GetValue()
            config['params']['pitch'] = self.mainDlg.txtViaPitch.GetValue()
            config['params']['inter_row_offset'] = self.mainDlg.txtInterRowOffset.GetValue()
            config['params']['via_drill'] = self.mainDlg.txtViaDrill.GetValue()
            config['params']['via_size'] = self.mainDlg.txtViaSize.GetValue()
            config['params']['fence_rows_per_side'] = str(self.mainDlg.spnFenceRows.GetValue())
            config['options']['include_selected'] = str(self.mainDlg.chkIncludeSelection.GetValue())
            config['options']['include_drawings'] = str(self.mainDlg.chkIncludeDrawing.GetValue())
            config['options']['remove_violations'] = str(self.mainDlg.chkRemoveViasWithClearanceViolation.GetValue())
            with open(self.local_config_file, 'w') as configfile:
                config.write(configfile)
            self.mainDlg.Destroy()  #the Dlg needs to be destroyed to release pcbnew

# TODO: Implement
#            if (self.isRemoveViasWithClearanceViolationChecked):
#                # Remove Vias that violate clearance to other things
#                # Check against other tracks
#                for viaObj in viaObjList:
#                    for track in self.boardObj.GetTracks():
#                        clearance = track.GetClearance(viaObj)
#                        if track.HitTest(False, clearance):
#                            self.boardObj.RemoveNative(viaObj)

# TODO: Implement
#            if (self.isSameNetZoneViasOnlyChecked):
#                # Keep via only if it is in a filled zone with the same net

#            import numpy as np
#            import matplotlib.pyplot as plt

#            for path in self.pathList:
#                plt.plot(np.array(path).T[0], np.array(path).T[1], linewidth=2)
#            for via in viaPoints:
#                plt.plot(via[0], via[1], 'o', markersize=10)


#            plt.ylim(plt.ylim()[::-1])
#            plt.axes().set_aspect('equal','box')
#            plt.show()

