"""ColorMap - the working code. RE-IMPORTED on every command (hot reload).

Fusion can't show a mesh's own colors: Insert Mesh drops them from 3MF and OBJ and
refuses PLY (tested 2026-11-05). So a Mimics color map (PLY with vertex colors) is drawn
here as custom graphics, a mesh with one color per vertex, on top of the bone.

  stored:  design attributes, group 'ColorMap': 'meta:<id>' (JSON: name, file, shown,
           counts) and 'data:<id>' (the PLY file itself, zlib + base64), so the map travels
           with the design and needs no file afterwards;
  drawn:   one custom graphics group per shown map, id 'ColorMap|<id>', depthPriority 1
           (it lies exactly on the bone: without it the bone shows through in patches),
           not selectable;
  never saved: drawings present at Save are stored in that version and come back on
           every open, out of the API's reach (found with MeasureTimeline, 2026-11-02), so
           everything is removed on documentSaving and drawn again on documentSaved.
  legend:  (v0.2) a docked panel, Inspect > Color Map Legend, shows the legend of each shown
           map: from the PLY's own 'comment legend {json}' (DensityMap maps), else from the
           <stem>_leyenda.svg next to the original file. Drawn by the panel page itself (colour
           bar + HU ticks + text), readable at panel width.

Coordinates are taken as millimetres (Mimics). The PLYs from Mimics are in the same
frame as the bone meshes inserted from Mimics, so the map lands on them as is (checked on
a radius and an ulna: same triangles, bounding boxes within 0.1 mm).
"""

import adsk.core
import adsk.fusion

import base64
import json
import math
import os
import re
import struct
import sys
import types
import zlib

PANELS = ['InspectPanel']
LEGEND_PALETTE_ID = 'ColorMap_LegendPanel'      # = the shell's
LEGEND_PANEL_W, LEGEND_PANEL_MIN_W = 330, 150
ATTR_GROUP = 'ColorMap'
GROUP_PREFIX = 'ColorMap|'
DEPTH_PRIORITY = 1
# The map is drawn this far out along its vertex normals. The bone the user sees may be a
# smooth body made from the same mesh (a NURBS "part" made from the scan): it stays within
# ~0.03 mm of the triangles but is outside them half the time, so bone and map took turns
# on screen in patches (2026-11-05). Triangle centroids + edge midpoints still inside that
# body: 0 mm 3022 of 6452, 0.05 mm 537, 0.1 mm 147, 0.2 mm 92.
OFFSET_MM = 0.2

_PLY_TYPES = {'char': 'b', 'int8': 'b', 'uchar': 'B', 'uint8': 'B', 'short': 'h', 'int16': 'h',
              'ushort': 'H', 'uint16': 'H', 'int': 'i', 'int32': 'i', 'uint': 'I', 'uint32': 'I',
              'float': 'f', 'float32': 'f', 'double': 'd', 'float64': 'd'}


def _state():
    """Survives the hot reload: files read in the open dialog, not stored yet."""
    return sys.modules.setdefault('cm_state', types.ModuleType('cm_state'))


# --------------------------------------------------------------------------- #
# toolbar
# --------------------------------------------------------------------------- #

def place_button(ui, cmd_def):
    """Add the button to PANELS (Inspect). Returns the controls."""
    controls = []
    for pid in PANELS:
        panel = ui.allToolbarPanels.itemById(pid)
        if not panel:
            continue
        old = panel.controls.itemById(cmd_def.id)
        if old:
            old.deleteMe()
        ctrl = panel.controls.addCommand(cmd_def)
        ctrl.isPromotedByDefault = False
        controls.append(ctrl)
    return controls


# --------------------------------------------------------------------------- #
# PLY
# --------------------------------------------------------------------------- #

def read_ply(raw):
    """(vertices [(x, y, z)], colors [(r, g, b)], triangles [(a, b, c)]) from a PLY file's
    bytes: ascii or binary, vertex colors red/green/blue (uchar 0-255 or float 0-1),
    polygons split into triangles."""
    end = raw.find(b'end_header')
    if not raw.startswith(b'ply') or end < 0:
        raise ValueError('not a PLY file')
    body = raw.index(b'\n', end) + 1
    fmt, elements = None, []
    for line in raw[:end].decode('ascii', 'replace').splitlines():
        w = line.split()
        if not w:
            continue
        if w[0] == 'format':
            fmt = w[1]
        elif w[0] == 'element':
            elements.append((w[1], int(w[2]), []))
        elif w[0] == 'property':
            props = elements[-1][2]
            if w[1] == 'list':
                props.append((w[4], _PLY_TYPES[w[2]], _PLY_TYPES[w[3]]))
            else:
                props.append((w[2], _PLY_TYPES[w[1]], None))
    if fmt not in ('ascii', 'binary_little_endian', 'binary_big_endian'):
        raise ValueError('unknown PLY format %r' % fmt)
    rows = (_ascii_rows if fmt == 'ascii' else _binary_rows)(
        raw, body, elements, '<' if fmt == 'binary_little_endian' else '>')
    vert = rows.get('vertex')
    if not vert:
        raise ValueError('no vertices')
    names = [p[0] for p in next(e for e in elements if e[0] == 'vertex')[2]]
    if not all(c in names for c in ('red', 'green', 'blue')):
        raise ValueError('the file has no vertex colors (red / green / blue)')
    ix, iy, iz = (names.index(c) for c in 'xyz')
    ir, ig, ib = (names.index(c) for c in ('red', 'green', 'blue'))
    scale = 255.0 if all(isinstance(r[ir], float) for r in vert[:10]) else 1.0
    V = [(r[ix], r[iy], r[iz]) for r in vert]
    C = [tuple(max(0, min(255, int(round(r[k] * scale)))) for k in (ir, ig, ib)) for r in vert]
    T = []
    face = next((e for e in elements if e[0] == 'face'), None)
    if face:
        fi = next(i for i, p in enumerate(face[2]) if p[2] is not None)   # the list property
        for r in rows['face']:
            poly = r[fi]
            for k in range(1, len(poly) - 1):
                T.append((poly[0], poly[k], poly[k + 1]))
    if not T:
        raise ValueError('no faces')
    if max(max(t) for t in T) >= len(V):
        raise ValueError('a face uses a vertex the file does not have')
    return V, C, T


def _binary_rows(raw, at, elements, order):
    out = {}
    for name, count, props in elements:
        rows = []
        if all(p[2] is None for p in props):                    # fixed size: fast path
            f = struct.Struct(order + ''.join(p[1] for p in props))
            rows = list(f.iter_unpack(raw[at:at + f.size * count]))
            at += f.size * count
        else:
            for _ in range(count):
                row = []
                for _pn, t, it in props:
                    if it is None:
                        s = struct.Struct(order + t)
                        row.append(s.unpack_from(raw, at)[0])
                        at += s.size
                    else:
                        cs = struct.Struct(order + t)
                        n = cs.unpack_from(raw, at)[0]
                        at += cs.size
                        s = struct.Struct(order + it * n)
                        row.append(s.unpack_from(raw, at))
                        at += s.size
                rows.append(row)
        out[name] = rows
    return out


def _ascii_rows(raw, at, elements, _order):
    words = iter(raw[at:].decode('ascii', 'replace').split())
    out = {}
    for name, count, props in elements:
        rows = []
        for _ in range(count):
            row = []
            for _pn, t, it in props:
                conv = float if t in 'fd' else int
                if it is None:
                    row.append(conv(next(words)))
                else:
                    n = int(next(words))
                    iconv = float if it in 'fd' else int
                    row.append(tuple(iconv(next(words)) for _ in range(n)))
            rows.append(row)
        out[name] = rows
    return out


def vertex_normals(V, T):
    """Area-weighted vertex normals, for smooth shading."""
    N = [[0.0, 0.0, 0.0] for _ in V]
    for a, b, c in T:
        ax, ay, az = V[a]
        ux, uy, uz = V[b][0] - ax, V[b][1] - ay, V[b][2] - az
        vx, vy, vz = V[c][0] - ax, V[c][1] - ay, V[c][2] - az
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        for i in (a, b, c):
            N[i][0] += n[0]
            N[i][1] += n[1]
            N[i][2] += n[2]
    out = []
    for n in N:
        L = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
        out.append((n[0] / L, n[1] / L, n[2] / L))
    return out


# --------------------------------------------------------------------------- #
# storage (design attributes)
# --------------------------------------------------------------------------- #

def map_id(name):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', name)


def maps(design):
    """[meta dict] of the maps stored in the design, by name."""
    out = []
    for a in design.attributes.itemsByGroup(ATTR_GROUP):
        if a.name.startswith('meta:'):
            try:
                m = json.loads(a.value)
                m['id'] = a.name[5:]
                out.append(m)
            except Exception:
                pass
    return sorted(out, key=lambda m: m['name'].lower())


def ply_bytes(design, mid):
    a = design.attributes.itemByName(ATTR_GROUP, 'data:' + mid)
    return zlib.decompress(base64.b64decode(a.value)) if a else None


def store(design, name, path, raw, counts):
    mid = map_id(name)
    meta = {'name': name, 'file': path, 'shown': True, 'vertices': counts[0], 'triangles': counts[1]}
    design.attributes.add(ATTR_GROUP, 'data:' + mid, base64.b64encode(zlib.compress(raw, 9)).decode('ascii'))
    design.attributes.add(ATTR_GROUP, 'meta:' + mid, json.dumps(meta))
    return mid


def set_shown(design, mid, shown):
    a = design.attributes.itemByName(ATTR_GROUP, 'meta:' + mid)
    m = json.loads(a.value)
    if m.get('shown') != shown:
        m['shown'] = shown
        a.value = json.dumps(m)


def remove(design, mid):
    """Delete a stored map (the dialog's Delete selected, v0.1.2)."""
    for key in ('meta:', 'data:'):
        a = design.attributes.itemByName(ATTR_GROUP, key + mid)
        if a:
            a.deleteMe()


# --------------------------------------------------------------------------- #
# drawing
# --------------------------------------------------------------------------- #

def _groups(design):
    gs = design.rootComponent.customGraphicsGroups
    return {gs.item(i).id[len(GROUP_PREFIX):]: gs.item(i) for i in range(gs.count)
            if gs.item(i).id.startswith(GROUP_PREFIX)}


def draw_map(design, mid, raw):
    V, C, T = read_ply(raw)
    N = vertex_normals(V, T)
    g = design.rootComponent.customGraphicsGroups.add()
    g.id = GROUP_PREFIX + mid
    co = adsk.fusion.CustomGraphicsCoordinates.create(
        [(v[i] + OFFSET_MM * n[i]) / 10.0 for v, n in zip(V, N) for i in range(3)])      # mm -> cm
    co.colors = [k for c in C for k in (c[0], c[1], c[2], 255)]
    idx = [i for t in T for i in t]
    mesh = g.addMesh(co, idx, [c for n in N for c in n], idx)
    mesh.color = adsk.fusion.CustomGraphicsVertexColorEffect.create()
    mesh.depthPriority = DEPTH_PRIORITY
    mesh.isSelectable = False
    g.isSelectable = False
    return g


def draw_all(app):
    """Draw every shown map that isn't drawn; remove drawings of hidden or deleted maps.
    Touches nothing when all is as it should be (any custom graphics change marks the
    document modified). Nothing is drawn while a document is still opening (no
    viewport): such drawings are never listed and can't be removed (MeasureTimeline)."""
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des or app.activeViewport is None:
        return
    want = {m['id'] for m in maps(des) if m.get('shown', True)}
    have = _groups(des)
    changed = False
    for mid, g in have.items():
        if mid not in want:
            g.deleteMe()
            changed = True
    for mid in want - set(have):
        raw = ply_bytes(des, mid)
        if raw:
            draw_map(des, mid, raw)
            changed = True
    if changed:
        app.activeViewport.refresh()


def clear_everything(design):
    for g in _groups(design).values():
        g.deleteMe()


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #

def on_document_activated(app):
    draw_all(app)
    push_legend(app)


def on_command_terminated(app):
    draw_all(app)


def on_document_saving(app, document):
    """About to save: remove the drawings, or they are stored in that version."""
    des = adsk.fusion.Design.cast(document.products.itemByProductType('DesignProductType'))
    if des:
        clear_everything(des)


def on_document_saved(app, document):
    """Saved: draw again (this marks the document modified; the design is unchanged)."""
    if document == app.activeDocument:
        draw_all(app)


def on_stop(app):
    """Don't leave drawings behind in any open design."""
    for i in range(app.documents.count):
        try:
            des = adsk.fusion.Design.cast(
                app.documents.item(i).products.itemByProductType('DesignProductType'))
            if des:
                clear_everything(des)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# the dialog
# --------------------------------------------------------------------------- #

def _row(table, mid, name, tip, shown):
    """One table row: name | Show. One box (2026-11-05, the user's wish): ticked, the map is
    drawn on the bone; unticked, it is taken off the model but stays stored in the design,
    so ticking it again brings it back."""
    ci = table.commandInputs
    r = table.rowCount
    t = ci.addTextBoxCommandInput('name_' + mid, '', name, 1, True)
    t.tooltip = tip
    table.addCommandInput(t, r, 0)
    show = ci.addBoolValueInput('show_' + mid, 'Show', True, '', shown)
    show.tooltip = 'Ticked: the map is shown on the bone. Unticked: it is taken off the model.'
    table.addCommandInput(show, r, 1)


def _header(table):
    """Column titles: Fusion tables have none of their own."""
    ci = table.commandInputs
    for col, (key, text) in enumerate((('name', 'Map'), ('show', 'Show'))):
        table.addCommandInput(ci.addTextBoxCommandInput('hdr_' + key, '', '<b>%s</b>' % text, 1, True), 0, col)


def _tip(m):
    return '%s\n%d vertices, %d triangles' % (m.get('file') or '', m.get('vertices', 0), m.get('triangles', 0))


def _row_exists(inputs, mid):
    return mid not in _state().deleted and inputs.itemById('show_' + mid) is not None


def on_created(app, cmd):
    des = adsk.fusion.Design.cast(app.activeProduct)
    _state().pending = {}
    _state().deleted = set()
    cmd.isRepeatable = False
    cmd.okButtonText = 'Apply'
    inputs = cmd.commandInputs
    inputs.addBoolValueInput('add', 'Add PLY files…', False, '', False)
    inputs.addTextBoxCommandInput(
        'help', '', 'Pick the PLY files exported from Mimics with vertex colors (one per '
        'bone). They are drawn where Mimics puts them, in millimetres. Ticked: the map is '
        'shown; unticked: it is taken off the model (on Apply). To delete a map from the '
        'design, click its name, then Delete selected.',
        4, True)
    table = inputs.addTableCommandInput('maps', 'Color maps', 2, '5:1')
    table.maximumVisibleRows = 9
    table.minimumVisibleRows = 3
    delete = table.commandInputs.addBoolValueInput('delete', 'Delete selected', False, '', False)
    delete.text = 'Delete selected'
    delete.tooltip = ('Delete the selected map from the design (on Apply). Only the copy '
                      'stored in the design is deleted; the PLY file on disk is not touched.')
    table.addToolbarCommandInput(delete)
    _header(table)
    for m in (maps(des) if des else []):
        _row(table, m['id'], m['name'], _tip(m), m.get('shown', True))
    inputs.addTextBoxCommandInput('report', '', '', 3, True)


def _delete_selected(inputs):
    """Take the selected row out of the table; the map is deleted on Apply."""
    table = adsk.core.TableCommandInput.cast(inputs.itemById('maps'))
    report = inputs.itemById('report')
    r = table.selectedRow
    if r <= 0:                                  # none, or the header row
        report.text = 'Select a map first: click its name in the table.'
        return
    mid = table.getInputAtPosition(r, 0).id[len('name_'):]
    name = table.getInputAtPosition(r, 0).text
    table.deleteRow(r)
    _state().pending.pop(mid, None)
    _state().deleted.add(mid)
    report.text = '%s will be deleted from the design when you press Apply.' % name


def on_input_changed(app, inputs, changed_id):
    if changed_id == 'delete':
        _delete_selected(inputs)
        return
    if changed_id != 'add':
        return
    dlg = app.userInterface.createFileDialog()
    dlg.title = 'Color maps (PLY with vertex colors)'
    dlg.filter = 'PLY files (*.ply);;All files (*.*)'
    dlg.isMultiSelectEnabled = True
    if dlg.showOpen() != adsk.core.DialogResults.DialogOK:
        return
    table = adsk.core.TableCommandInput.cast(inputs.itemById('maps'))
    pending = _state().pending
    notes = []
    for path in dlg.filenames:
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            raw = open(path, 'rb').read()
            V, C, T = read_ply(raw)
        except Exception as e:
            notes.append('%s: %s' % (name, e))
            continue
        mid = map_id(name)
        replaces = _row_exists(inputs, mid)
        pending[mid] = (name, path, raw, (len(V), len(T)))
        if not replaces:
            _state().deleted.discard(mid)           # deleted in this dialog, then added again
            _row(table, mid, name, '%s\n%d vertices, %d triangles' % (path, len(V), len(T)), True)
        notes.append('%s: %d vertices, %d triangles%s' % (
            name, len(V), len(T), ' (replaces the stored one)' if replaces else ''))
    inputs.itemById('report').text = '\n'.join(notes)


def on_validate(inputs):
    return True


def on_execute(app, cmd):
    des = adsk.fusion.Design.cast(app.activeProduct)
    inputs = cmd.commandInputs
    pending = _state().pending
    deleted = _state().deleted
    stored = {m['id'] for m in maps(des)}
    groups = _groups(des)
    for mid in deleted & stored:
        remove(des, mid)                            # its drawing goes in draw_all
    for mid in sorted((stored | set(pending)) - deleted):
        if mid in pending:
            name, path, raw, counts = pending[mid]
            store(des, name, path, raw, counts)
            if mid in groups:                       # replaced: draw the new one
                groups[mid].deleteMe()
        show = inputs.itemById('show_' + mid)
        if show:                                    # no row: leave that map as it is
            set_shown(des, mid, show.value)
    _state().pending = {}
    _state().deleted = set()
    draw_all(app)
    push_legend(app)


# --------------------------------------------------------------------------- #
# the legend panel (v0.2): Inspect > Color Map Legend
# --------------------------------------------------------------------------- #

def _legend_from_ply(raw):
    """The 'comment legend {json}' a DensityMap PLY carries in its header (2026-11-13 on)."""
    end = raw.find(b'end_header')
    for line in raw[:max(end, 0)].decode('ascii', 'replace').splitlines():
        if line.startswith('comment legend '):
            return json.loads(line[len('comment legend '):])
    return None


def _legend_from_svg(path):
    """Fallback for maps stored before legends were put in the PLY: the DensityMap legend file next to
    the original PLY (<stem>_leyenda.svg), parsed. Read only - nothing is written into the design."""
    svg = os.path.splitext(path)[0] + '_leyenda.svg'
    if not path or not os.path.isfile(svg):
        return None
    t = open(svg, encoding='utf-8').read()
    stops = [tuple(int(v) for v in m) for m in re.findall(r'stop-color="rgb\((\d+),(\d+),(\d+)\)"', t)]
    ticks = [int(v) for v in re.findall(r'>(-?\d+) HU</text>', t)]
    texts = re.findall(r'<text[^>]*font-size="13"[^>]*>([^<]*)</text>', t)
    title = re.search(r'font-weight="bold">([^<]*)</text>', t)
    lines = [x for x in texts if not re.fullmatch(r'-?\d+ HU', x)]
    if not stops or len(ticks) < 2:
        return None
    unesc = lambda s: s.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return {'title': unesc(title.group(1)) if title else '', 'unit': 'HU', 'lo': min(ticks), 'hi': max(ticks),
            'tick': ticks[1] - ticks[0] if len(ticks) > 1 else 100,
            'colors': [list(c) for c in stops[::-1]],       # the SVG lists them top (high) first
            'lines': [unesc(x) for x in lines], 'from_file': svg}


def legend_state(app):
    """What the legend panel shows: one entry per SHOWN map, with its legend or None."""
    des = adsk.fusion.Design.cast(app.activeProduct)
    out = {'doc': app.activeDocument.name if app.activeDocument else '', 'maps': []}
    if not des:
        return out
    for m in maps(des):
        if not m.get('shown', True):
            continue
        leg = None
        try:
            raw = ply_bytes(des, m['id'])
            leg = _legend_from_ply(raw) if raw else None
            if leg is None:
                leg = _legend_from_svg(m.get('file') or '')
        except Exception:
            leg = None
        out['maps'].append({'name': m['name'], 'legend': leg})
    return out


def push_legend(app):
    pal = app.userInterface.palettes.itemById(LEGEND_PALETTE_ID)
    if pal and pal.isVisible:
        pal.sendInfoToHTML('update', json.dumps(legend_state(app)))


def toggle_legend(app, pal):
    """The Color Map Legend button: open the panel (restoring a usable width if it was collapsed to its
    strip), or close it if it is open - same behaviour as the Measurements panel."""
    if pal.isVisible and pal.width >= LEGEND_PANEL_MIN_W:
        pal.isVisible = False
        return
    pal.isVisible = True
    if pal.width < LEGEND_PANEL_MIN_W:
        floating = adsk.core.PaletteDockingStates.PaletteDockStateFloating
        dock = pal.dockingState
        if dock != floating:
            pal.dockingState = floating
        pal.width = LEGEND_PANEL_W
        if dock != floating:
            pal.dockingState = dock
    push_legend(app)


def on_legend_message(app, action, data):
    """The panel asks for its content when it loads ('ready')."""
    if action == 'ready':
        return json.dumps(legend_state(app))
    return ''
