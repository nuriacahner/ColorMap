# Color Map (ColorMap)

A Fusion add-in that shows a **color map on a bone**: a mesh with one color per vertex,
exported as a PLY file, drawn on the model with its own colors. For example:
- a vertex-color map made in Mimics;
- a density map made from the CT by the DensityMap tool (separate repository).

A **legend panel** shows the color scale and the information of each map.

**Inspect → Color Map** and **Inspect → Color Map Legend**

## Why

Fusion can't show a mesh's own colors:
- **Insert Mesh drops them** from 3MF and OBJ files: the body comes in one color;
- **it doesn't accept PLY at all,** the usual format for vertex colors.

This add-in reads the PLY and draws it with Fusion's custom graphics, which can color each
vertex. The map lands on the bone where it belongs, as long as both were exported in the
same coordinates (Mimics exports its parts that way).

## Using it

### Color Map

1. Open **Color Map** and press **Add PLY files…** You can pick several files at once.
   Each is read straight away; a file that can't be used is reported in the dialog.
2. Each map is a row in the table, with a **Show** box:
   - ticked, the map is drawn on the model;
   - unticked, it's taken off the model but stays stored, so you can show it again later.
3. To delete a map from the design: click its name, then **Delete selected**. The PLY
   file on disk is never touched.
4. Press **Apply**.

Each map is **stored inside the design**, so it travels with the file and the original PLY
isn't needed afterwards. Adding a file with the same name replaces the stored map.

### Color Map Legend

**Color Map Legend** opens a panel docked on the right. For each map shown, it displays:
- the color bar with its scale marks (e.g. every 100 HU);
- the information lines: method, data, range, values, date.

The same button closes the panel.

The legend comes from:
1. **the PLY itself:** maps made by the DensityMap tool carry their legend inside the file,
   so it's stored in the design together with the map;
2. **otherwise, a `<name>_leyenda.svg` file** next to the original PLY, if it can still be
   found. The panel then says so;
3. **otherwise,** the panel says the map has no legend (e.g. a map exported directly from
   Mimics).

## Install

1. Clone or copy this folder anywhere.
2. Run `powershell -File install.ps1`. It copies the add-in to
   `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\ColorMap`.
3. In Fusion: **Utilities → ADD-INS → Scripts and Add-Ins → Add-Ins**, select
   **ColorMap**, keep *Run on Startup* ticked, and press **Run**.
4. The **Color Map** and **Color Map Legend** buttons appear in **Inspect**.

No extra Python packages are needed.

## How it works

- **Reading:** PLY files, ASCII or binary (little- or big-endian), with per-vertex
  `red green blue` (0–255 or 0–1). Polygons are split into triangles.
- **Storing:** each map is kept in the design's attributes: the PLY file itself,
  compressed, plus its name, source file and *Show* state. Maps of about 1 MB (40,000
  triangles) have been tested.
- **Drawing:** a custom-graphics mesh with one color per vertex and smooth shading.
  - **Units:** coordinates are taken as millimetres.
  - **Pushed 0.2 mm outward,** along each vertex's normal. The bone you see may be a
    smooth body made from the same mesh, sitting a few hundredths of a millimetre outside
    the triangles in places. Without the offset, bone and map take turns on screen in
    patches.
  - **Not selectable,** so clicks go through it to the bone underneath.
- **Never saved:** a drawing present when a design is saved would be stored in that version
  and come back on every open, out of the API's reach. So the drawings are removed just
  before saving and drawn again just after.
  - The design then shows as modified right after a save; the model itself is unchanged.
- **Legend panel:** an HTML page that draws the legend itself (color bar, marks and text),
  so it stays readable at panel width. Text from files is inserted as plain text, never as
  HTML.

## Repository layout

| Path | |
|---|---|
| `ColorMap.py` | add-in shell: lifecycle, the two buttons, the legend panel, events |
| `cm_core.py` | reading PLY, storing, drawing, the dialog, the legend data; re-imported on every command |
| `resources/legend/legend.html` | the legend panel |
| `resources/ColorMap/`, `resources/ColorMapLegend/` | toolbar icons |
| `install.ps1` | copies the add-in into Fusion's AddIns folder |
| `tools/make_icons.py` | draws the icons |

## Tests

There are no automated tests. The add-in was tested inside Fusion, in throwaway documents:
- storing, drawing, showing and hiding maps;
- deleting a map;
- removing the drawings before a save and redrawing them after;
- a 1 MB map.

The PLY and legend readers were also tested outside Fusion, on real and hand-written files.

## Known limits

- **The map is a drawing, not a body.** It can't be selected, measured or cut with Section
  Analysis.
- **It's opaque:** Fusion's per-vertex colors can't be made transparent. To see inside,
  hide the map.
- **The add-in must be running** to see the maps; they stay stored in the design either way.
- **After opening a design,** the maps may only appear at the first click or command.
- **The PLY must be in the model's coordinates, in millimetres.** The add-in doesn't move or
  scale it.

## Licence

MIT. See `LICENSE`.
