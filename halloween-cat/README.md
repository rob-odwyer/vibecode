# Spooky black cat face (Halloween cut file)

A black cat face silhouette to cut from black material, with two large round
eye holes so a pair of small screens showing animated eyes can sit behind it.

![preview](preview.png)

## Files

| File | Use it for |
| --- | --- |
| `cat-face.svg` | The design. Black filled shape with the holes already cut through. Works as-is in Cricut Design Space, Silhouette Studio, Inkscape, Illustrator, etc. |
| `cat-face-cutlines.svg` | Same geometry as 0.1 mm red hairline strokes, no fill. For laser cutters (LightBurn, Glowforge, xTool) and CNC software that want outlines. |

Both files are drawn in millimetres: the page is 300 x 300 mm and one SVG unit
is one millimetre.

## Key dimensions at 100 %

| Feature | Size |
| --- | --- |
| Overall width (cheek tuft to cheek tuft) | 288 mm |
| Overall height (ear tip to chin) | 278 mm |
| Eye hole diameter | 72 mm |
| Eye centre spacing | 104 mm |
| Eye centres | (98, 165) and (202, 165) |
| Thinnest material bridge (nose to grin) | about 8 mm |

## Scaling to your screens

Measure the *visible* diameter of your displays and scale the whole file so
the 72 mm hole is a little smaller than the bezel but no smaller than the
visible area. Scale factor = desired hole diameter / 72.

| Display | Visible area | Scale | Resulting face width |
| --- | --- | --- | --- |
| 1.28" round LCD (GC9A01, very common for "eye" projects) | ~32.4 mm | 45 % | ~130 mm |
| 1.85" round | ~47 mm | 65 % | ~187 mm |
| 2.1" round (480x480) | ~53 mm | 74 % | ~213 mm |
| 2.8" round or a phone behind a round mask | ~71 mm | 100 % | 288 mm |

If you want a bigger face than the display dictates, leave the file at 100 %
and change only the eye circle radius (`r="36"` in `#eyes` and the two `a 36 36`
arcs in `#head`) to match your screen, then re-save.

## Options

* **Plain face.** Delete the `#mouth` group for a silhouette with only the eye
  holes. Light or a glowing backdrop behind the grin looks great, but it is
  optional.
* **Material.** Anything stiff and black: 3 mm MDF or plywood painted black,
  black acrylic, black foam board, or black card for a quick version. The
  cheek tufts and fang tips are the most fragile points; in paper or thin
  card, round them off slightly or glue the piece to a backing.
* **Mounting the screens.** The eye holes are plain circles, so you can hot
  glue the displays to the back of the face or cut a second backing board with
  matching holes to sandwich them.
