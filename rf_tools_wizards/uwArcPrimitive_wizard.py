#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
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
#

# This python script wizard creates an arc track for microwave applications
# Author  easyw
# taskkill -im pcbnew.exe /f &  C:\KiCad-v5-nightly\bin\pcbnew

from __future__ import division

import math, cmath

from pcbnew import *
import pcbnew
import FootprintWizardBase


class uwArcPrimitive_wizard(FootprintWizardBase.FootprintWizard):

    def GetName(self):
        return "uW Arc Pad"

    def GetDescription(self):
        return "uW Arc Pad Footprint Wizard"

    def GenerateParameterList(self):

        self.AddParam("Corner", "width", self.uMM, 1.319)
        self.AddParam("Corner", "radius", self.uMM, 5.0, min_value=0, designator='r', hint="Arc radius")
        self.AddParam("Corner", "angle", self.uDegrees, 90, designator='a')
        self.AddParam("Corner", "square_end", self.uBool, False)
        self.AddParam("Corner", "solder_clearance", self.uMM, 0.0)
        self.AddParam("Corner", "linear", self.uBool, False)

    def CheckParameters(self):

        pads = self.parameters['Corner']
        

    def GetValue(self):
        name = "{0:.2f}_{1:0.2f}_{2:.0f}".format(pcbnew.ToMM(self.parameters["Corner"]["width"]),pcbnew.ToMM(self.parameters["Corner"]["radius"]),(self.parameters["Corner"]["angle"]))
        if not self.parameters["Corner"]["linear"]:
            pref = "uwArc"
        else:
            pref = "uwLine"
        if self.parameters["Corner"]["square_end"]:
            pref += "R"
        return pref + "%s" % name
    
    def GetReferencePrefix(self):
        if not self.parameters["Corner"]["linear"]:
            pref = "uwA"
        else:
            pref = "uwL"
        #if self.parameters["Corner"]["rectangle"]:
        #    pref += "R"
        return pref + "***"

    def arc_points(self, centre, start, angle_D, cw=True):
        num_points = 20

        center_complex = complex(*centre)
        start_complex = complex(*start)

        radius = abs(start_complex - center_complex)
        start_angle = cmath.phase(start_complex - center_complex)

        arc_angle_rad = math.radians(angle_D)
        shape = pcbnew.SHAPE_LINE_CHAIN()
        if cw:
            step_angle = arc_angle_rad / (num_points - 1)
            for i in range(num_points):
                angle = start_angle + i * step_angle
                point = center_complex + cmath.rect(radius, angle)
                shape.Append(pcbnew.VECTOR2I(int(point.real), int(point.imag)))
        else:
            step_angle = arc_angle_rad / (num_points - 1)
            for i in range(num_points):
                angle = start_angle + ((num_points - 1) - i) * step_angle
                point = center_complex + cmath.rect(radius, angle)
                shape.Append(pcbnew.VECTOR2I(int(point.real), int(point.imag)))


        return shape
        
    # build a custom pad
    def smdCustomArcPad(self, module, size, pos, rad, name, angle_D, layer, ln, solder_clearance):
        if hasattr(pcbnew, 'D_PAD'):
            pad = D_PAD(module)
        else:
            pad = PAD(module)
        ## NB pads must be the same size and have the same center
        pad.SetSize(size)
        #pad.SetSize(pcbnew.wxSize(size[0]/5,size[1]/5))
        pad.SetShape(PAD_SHAPE_CUSTOM) #PAD_RECT)
        pad.SetAttribute(PAD_ATTRIB_SMD) #PAD_SMD)
        #pad.SetDrillSize (0.)
        #Set only the copper layer without mask
        #since nothing is mounted on these pads
        #pad.SetPos0(pos)
        pad.SetPosition(pos)
        pad.SetPadName(name)
        #pad.Rotate(pos, angle)
        pad.SetAnchorPadShape(PAD_SHAPE_CIRCLE) #PAD_SHAPE_RECT)
        if solder_clearance > 0:
            pad.SetLocalSolderMaskMargin(solder_clearance)
            pad.SetLayerSet(pad.ConnSMDMask())
        else:
            pad.SetLayerSet( LSET(layer) )
        
        if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
            if not ln:
                pad.AddPrimitive(pcbnew.wxPoint(0,rad), pcbnew.wxPoint(0,0), int(angle_D*10), (size[0]))
            else:
                pad.AddPrimitive(pcbnew.wxPoint(0,0), pcbnew.wxPoint(rad,0), (size[0]))
        elif hasattr(pcbnew, 'wxPoint()'): # kv7
            if not ln:
                pad.AddPrimitive(pcbnew.VECTOR2I(wxPoint(0,rad)), pcbnew.VECTOR2I(wxPoint(0,0)), pcbnew.EDA_ANGLE(int(angle_D*10),pcbnew.DEGREES_T), (size[0]))
            else:
                pad.AddPrimitive(pcbnew.VECTOR2I(wxPoint(0,0)), pcbnew.VECTOR2I(wxPoint(rad,0)), (size[0]))            
        else: # kv8
            if not ln:
                shape = pcbnew.SHAPE_LINE_CHAIN()
                shape.Append(self.arc_points((0,rad), (0,-size[0] / 2), int(angle_D*1), True))
                shape.Append(self.arc_points((0,rad), (0,size[0] / 2), int(angle_D*1), False))
                # shape.Append(self.arc_points((rad,rad), (0,size[0] / 2), int(angle_D*1), True))
                poly = pcbnew.SHAPE_POLY_SET(shape)
                pad.AddPrimitivePoly(poly, 0, True)
                # pad.AddPrimitive(pcbnew.VECTOR2I(int(0),int(rad)), pcbnew.VECTOR2I(int(0),int(0)), pcbnew.EDA_ANGLE(int(angle_D*10),pcbnew.DEGREES_T), (size[0])) 
                #pad.AddPrimitive(int(0),int(rad), int(0),int(0), pcbnew.EDA_ANGLE(int(angle_D*10),pcbnew.DEGREES_T), (size[0])) 
                #pad.AddPrimitive((int(0),int(rad)), (int(0),int(0)), pcbnew.EDA_ANGLE(int(angle_D*10),pcbnew.DEGREES_T), (size[0])) 
            else:
                pad.AddPrimitive(pcbnew.VECTOR2I(int(0),int(0)), pcbnew.VECTOR2I(int(rad),int(0)), (size[0]))            
        return pad

    def smdPad(self,module,size,pos,name,ptype,angle_D,layer,solder_clearance,offs=None):
        if hasattr(pcbnew, 'D_PAD'):
            pad = D_PAD(module)
        else:
            pad = PAD(module)
        pad.SetSize(size)
        pad.SetShape(ptype)  #PAD_SHAPE_RECT PAD_SHAPE_OVAL PAD_SHAPE_TRAPEZOID PAD_SHAPE_CIRCLE 
        # PAD_ATTRIB_CONN PAD_ATTRIB_SMD
        pad.SetAttribute(PAD_ATTRIB_SMD)
        if solder_clearance > 0:
            pad.SetLocalSolderMaskMargin(solder_clearance)
            pad.SetLayerSet(pad.ConnSMDMask())
        else:
            pad.SetLayerSet( LSET(layer) )
        #pad.SetDrillSize (0.)
        #pad.SetLayerSet(pad.ConnSMDMask())
        #pad.SetPos0(pos)
        pad.SetPosition(pos)
        #pad.SetOrientationDegrees(90-angle_D/10)
        pad.SetOrientationDegrees(angle_D)
        if offs is not None:
            pad.SetOffset(offs)
        pad.SetName(name)
        return pad
        
    def BuildThisFootprint(self):

        pads = self.parameters['Corner']
        
        radius = pads['radius'] #outline['diameter'] / 2
        width = pads['width']
        sold_clear = pads['solder_clearance']
        line = pads['linear']
        
        angle_deg = float(pads["angle"]) #*10)
        angle = math.radians(angle_deg) #/10) #To radians
        sign = 1.
        if angle < 0:
            sign = -1.
        
        module = self.module
        if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
            pos = pcbnew.wxPoint(0,0)
            offset1 = pcbnew.wxPoint(-sign*width/2,0)
            offset2 = pcbnew.wxPoint(0,0)
            size_pad = pcbnew.wxSize(width, width)
            module.Add(self.smdCustomArcPad(module, size_pad, pcbnew.wxPoint(0,0), radius, "1", (angle_deg), F_Cu, line, sold_clear))
            size_pad = pcbnew.wxSize(width, width)
        elif hasattr(pcbnew, 'wxPoint()'): # kv7
            pos = pcbnew.VECTOR2I(wxPoint(0,0))
            offset1 = pcbnew.VECTOR2I(wxPoint(-sign*width/2,0))
            offset2 = pcbnew.VECTOR2I(wxPoint(0,0))
            size_pad = pcbnew.VECTOR2I(VECTOR2I(width, width))
            module.Add(self.smdCustomArcPad(module, size_pad, pcbnew.VECTOR2I(wxPoint(0,0)), radius, "1", (angle_deg), F_Cu, line, sold_clear))
            size_pad = pcbnew.VECTOR2I(width, width)
        else: # kv8
            pos = pcbnew.VECTOR2I(int(0),int(0))
            offset1 = pcbnew.VECTOR2I(int(-sign*width/2),int(0))
            offset2 = pcbnew.VECTOR2I(int(0),int(0))
            size_pad = pcbnew.VECTOR2I(VECTOR2I(int(width), int(width)))
            module.Add(self.smdCustomArcPad(module, size_pad, pcbnew.VECTOR2I(int(0),int(0)), radius, "1", (angle_deg), F_Cu, line, sold_clear))
            size_pad = pcbnew.VECTOR2I(int(width), int(width))
        #size_pad = pcbnew.wxSize(width/5, width/5)
        end_coord = (radius) * cmath.exp(math.radians(angle_deg-90)*1j)
        if pads['square_end'] or angle_deg == 0 or radius == 0:
            if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
                if not line:
                    ## NB pads must be the same size and have the same center
                    module.Add(self.smdPad(module, size_pad, pcbnew.wxPoint(0,0), "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear,offset1))
                else:
                    module.Add(self.smdPad(module, size_pad, pcbnew.wxPoint(0,0), "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear))
                if not line:
                    #pos = pcbnew.wxPoint(end_coord.real+(sign*width/2)*math.cos(angle),end_coord.imag+(sign*width/2)*math.sin(angle)+radius)
                    pos = pcbnew.wxPoint(end_coord.real,end_coord.imag+radius)
                    module.Add(self.smdPad(module, size_pad, pos, "1", PAD_SHAPE_RECT,90-angle_deg,F_Cu,sold_clear,wxPoint(0,(sign*width/2))))
                    #*math.sin(math.pi/2-angle),(sign*width/2)*math.cos(math.pi/2-angle))))
                else:
                    pos = pcbnew.wxPoint(radius,0) #+width/2,0)
                    module.Add(self.smdPad(module, size_pad, pos, "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear))
            elif hasattr(pcbnew, 'wxPoint()'): # kv7
                if not line:
                    ## NB pads must be the same size and have the same center
                    module.Add(self.smdPad(module, size_pad, pcbnew.VECTOR2I(wxPoint(0,0)), "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear,offset1))
                else:
                    module.Add(self.smdPad(module, size_pad, pcbnew.VECTOR2I(wxPoint(0,0)), "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear))
                if not line:
                    #pos = pcbnew.wxPoint(end_coord.real+(sign*width/2)*math.cos(angle),end_coord.imag+(sign*width/2)*math.sin(angle)+radius)
                    pos = pcbnew.VECTOR2I(wxPoint(end_coord.real,end_coord.imag+radius))
                    module.Add(self.smdPad(module, size_pad, pos, "1", PAD_SHAPE_RECT,90-angle_deg,F_Cu,sold_clear,pcbnew.VECTOR2I(wxPoint(0,(sign*width/2)))))
                    #*math.sin(math.pi/2-angle),(sign*width/2)*math.cos(math.pi/2-angle))))
                else:
                    pos = pcbnew.VECTOR2I(wxPoint(radius,0)) #+width/2,0)
                    module.Add(self.smdPad(module, size_pad, pos, "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear))
            else: # kv8
                if not line:
                    ## NB pads must be the same size and have the same center
                    module.Add(self.smdPad(module, size_pad, pcbnew.VECTOR2I(0,0), "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear,offset1))
                else:
                    module.Add(self.smdPad(module, size_pad, pcbnew.VECTOR2I(0,0), "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear))
                if not line:
                    #pos = pcbnew.wxPoint(end_coord.real+(sign*width/2)*math.cos(angle),end_coord.imag+(sign*width/2)*math.sin(angle)+radius)
                    pos = pcbnew.VECTOR2I(int(end_coord.real),int(end_coord.imag+radius))
                    module.Add(self.smdPad(module, size_pad, pos, "1", PAD_SHAPE_RECT,90-angle_deg,F_Cu,sold_clear,pcbnew.VECTOR2I(int(0),int(sign*width/2))))
                    #*math.sin(math.pi/2-angle),(sign*width/2)*math.cos(math.pi/2-angle))))
                else:
                    pos = pcbnew.VECTOR2I(int(radius),int(0)) #+width/2,0)
                    module.Add(self.smdPad(module, size_pad, pos, "1", PAD_SHAPE_RECT,0,F_Cu,sold_clear))
        else:
            ## NB pads must be the same size and have the same center
            #size_pad = pcbnew.wxSize(width/5, width/5)
            if hasattr(pcbnew, 'EDA_RECT'): # kv5,kv6
                size_pad = pcbnew.wxSize(width, width)
                if not line:
                    pos = pcbnew.wxPoint(end_coord.real,end_coord.imag+radius)
                else:
                    pos = pcbnew.wxPoint(radius,0)
            elif hasattr(pcbnew, 'wxPoint()'): # kv7
                size_pad = pcbnew.VECTOR2I(width, width)
                if not line:
                    pos = pcbnew.VECTOR2I(wxPoint(end_coord.real,end_coord.imag+radius))
                else:
                    pos = pcbnew.VECTOR2I(wxPoint(radius,0))
            else: # kv8
                size_pad = pcbnew.VECTOR2I(int(width), int(width))
                if not line:
                    pos = pcbnew.VECTOR2I(int(end_coord.real),int(end_coord.imag+radius))
                else:
                    pos = pcbnew.VECTOR2I(int(radius),int(0))
            module.Add(self.smdPad(module, size_pad, pos, "1", PAD_SHAPE_CIRCLE,0,F_Cu,sold_clear))

        # Text size
        text_size = self.GetTextSize()  # IPC nominal
        thickness = self.GetTextThickness()
        textposy = self.draw.GetLineThickness()/2 + self.GetTextSize()/2 + thickness #+ outline['margin']
        self.draw.Reference( 0, -textposy-width, text_size )
        if not line:
            self.draw.Value( 0, radius+textposy+width, text_size )
        else:
            self.draw.Value( 0, textposy+width, text_size )
        # set SMD attribute
        # set SMD attribute
        if hasattr(pcbnew, 'MOD_VIRTUAL'):
            module.SetAttributes(pcbnew.MOD_VIRTUAL)
        else:
            module.SetAttributes(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        __version__ = 1.8
        self.buildmessages += ("version: {:.1f}".format(__version__))

uwArcPrimitive_wizard().register()
