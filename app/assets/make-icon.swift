// SPDX-License-Identifier: GPL-3.0-only
// Vector artwork: camera, cable and computer. Run with an output PNG path.
import AppKit
let canvas = NSImage(size: NSSize(width: 1024, height: 1024))
canvas.lockFocus()
let green = NSColor(srgbRed: 0.08, green: 0.23, blue: 0.20, alpha: 1)
let cream = NSColor(srgbRed: 0.96, green: 0.95, blue: 0.86, alpha: 1)
let orange = NSColor(srgbRed: 0.96, green: 0.65, blue: 0.33, alpha: 1)
func box(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, _ radius: CGFloat, _ color: NSColor) {
    color.setFill()
    NSBezierPath(roundedRect: NSRect(x:x,y:y,width:w,height:h), xRadius:radius, yRadius:radius).fill()
}
box(48,48,928,928,205,green)
let cable = NSBezierPath()
cable.move(to:NSPoint(x:300,y:432))
cable.line(to:NSPoint(x:300,y:304))
cable.curve(to:NSPoint(x:374,y:230), controlPoint1:NSPoint(x:300,y:256), controlPoint2:NSPoint(x:326,y:230))
cable.line(to:NSPoint(x:655,y:230))
cable.curve(to:NSPoint(x:729,y:304), controlPoint1:NSPoint(x:703,y:230), controlPoint2:NSPoint(x:729,y:256))
cable.line(to:NSPoint(x:729,y:388))
cable.lineWidth=34; cable.lineCapStyle = .round
orange.setStroke();cable.stroke()
// Camera silhouette, raised prism, lens and viewfinder.
box(135,432,334,254,42,cream)
box(211,658,141,60,18,cream)
box(157,684,40,20,7,orange)
green.setFill();NSBezierPath(ovalIn:NSRect(x:217,y:479,width:172,height:172)).fill()
cream.setFill();NSBezierPath(ovalIn:NSRect(x:244,y:506,width:118,height:118)).fill()
green.setFill();NSBezierPath(ovalIn:NSRect(x:265,y:527,width:76,height:76)).fill()
box(401,631,35,20,6,green)
// Laptop: bezel, screen, and base.
box(581,447,300,250,30,cream)
box(604,473,254,200,13,green)
box(620,488,222,6,3,orange)
let base = NSBezierPath()
base.move(to:NSPoint(x:581,y:434));base.line(to:NSPoint(x:881,y:434))
base.line(to:NSPoint(x:921,y:390));base.line(to:NSPoint(x:541,y:390));base.close()
cream.setFill();base.fill()
box(686,418,90,12,6,green)
canvas.unlockFocus()
let rep = NSBitmapImageRep(data:canvas.tiffRepresentation!)!
try rep.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:CommandLine.arguments[1]))
