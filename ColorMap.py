"""ColorMap - Fusion 360 add-in. THIS FILE IS THE SHELL, NOT THE WORK.

Lifecycle, the toolbar buttons (Inspect > Color Map, Inspect > Color Map Legend), the legend
panel and event wiring. All the real code lives in cm_core.py and is RE-IMPORTED FRESH on
every command, so editing it takes effect on the next click. Only changes to this file need
the add-in stopped and run again.
"""

import adsk.core
import adsk.fusion

import importlib
import os
import pathlib
import sys
import time
import traceback

CMD_ID = 'ColorMap_Manage'
CMD_NAME = 'Color Map'
CMD_TOOLTIP = (
    'Show a color map exported from Mimics (PLY with vertex colors) on the bones.\n\n'
    'Add the PLY files; each is stored in the design and drawn with its own colors where '
    'Mimics puts it. Tick a map to show it, untick it to take it off the model. The drawing is not part of the model '
    'and is never saved: it is drawn again when the design is opened.'
)

LEGEND_CMD_ID = 'ColorMap_Legend'
LEGEND_CMD_NAME = 'Color Map Legend'
LEGEND_TOOLTIP = (
    'Open or close the legend panel: the colour scale (HU) and the information of each colour map '
    'shown on the model.'
)
PALETTE_ID = 'ColorMap_LegendPanel'          # = cm_core.LEGEND_PALETTE_ID
PALETTE_NAME = 'Color Map – leyenda'

ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
RES_DIR = os.path.join(ADDIN_DIR, 'resources', 'ColorMap')
LEGEND_RES_DIR = os.path.join(ADDIN_DIR, 'resources', 'ColorMapLegend')
PALETTE_HTML = os.path.join(ADDIN_DIR, 'resources', 'legend', 'legend.html')
LOG_PATH = os.path.join(ADDIN_DIR, 'ColorMap.log')
OWN_MODULES = ('cm_core',)

_app = None
_ui = None
_handlers = []
_controls = []
_listeners = []          # (event, handler) for documents / commands, removed on stop
_palette_handler = None  # the legend panel's incomingFromHTML handler (attached once per palette)


def _log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write('%s  %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg))
    except Exception:
        pass


def _core():
    """Fresh import of the worker module. This is the hot reload.

    Fusion runs every add-in and script in ONE Python: drop a same-named module loaded
    from elsewhere and keep this folder first on sys.path, so the add-in always runs
    its own installed files."""
    while ADDIN_DIR in sys.path:
        sys.path.remove(ADDIN_DIR)
    sys.path.insert(0, ADDIN_DIR)
    here = os.path.normcase(ADDIN_DIR)
    for name in OWN_MODULES:
        mod = sys.modules.get(name)
        if mod and os.path.normcase(os.path.dirname(os.path.realpath(mod.__file__))) != here:
            del sys.modules[name]
    if 'cm_core' in sys.modules:
        return importlib.reload(sys.modules['cm_core'])
    return importlib.import_module('cm_core')


def _loaded_core():
    """The module as loaded (events fire often: no reload)."""
    return sys.modules.get('cm_core') or _core()


def _fail(where):
    tb = traceback.format_exc()
    _log('%s\n%s' % (where, tb))
    if _ui:
        _ui.messageBox('%s\n\n%s\n\nFull traceback in\n%s'
                       % (where, tb.strip().splitlines()[-1], LOG_PATH), CMD_NAME)


# --------------------------------------------------------------------------- #
# command handlers - thin, they only delegate
# --------------------------------------------------------------------------- #

class _Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            _core().on_created(_app, cmd)
            for h, ev in ((_Execute(), cmd.execute),
                          (_Changed(), cmd.inputChanged),
                          (_Validate(), cmd.validateInputs)):
                ev.add(h)
                _handlers.append(h)
        except Exception:
            _fail('Color Map could not open its dialog.')


class _Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            sys.modules['cm_core'].on_execute(_app, args.command)
        except Exception:
            _fail('Color Map failed.')


class _Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            sys.modules['cm_core'].on_input_changed(
                _app, args.input.parentCommand.commandInputs, args.input.id)
        except Exception:
            _fail('Color Map could not read the file.')


class _Validate(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            args.areInputsValid = sys.modules['cm_core'].on_validate(args.inputs)
        except Exception:
            args.areInputsValid = False


# --------------------------------------------------------------------------- #
# document / command events: draw on activation, never keep a drawing in a save
# --------------------------------------------------------------------------- #

class _DocumentActivated(adsk.core.DocumentEventHandler):
    def notify(self, args):
        try:
            _loaded_core().on_document_activated(_app)
        except Exception:
            _log(traceback.format_exc())


class _DocumentSaving(adsk.core.DocumentEventHandler):
    """Drawings present at Save are stored in the file: remove them first."""

    def notify(self, args):
        try:
            _loaded_core().on_document_saving(_app, args.document)
        except Exception:
            _log(traceback.format_exc())


class _DocumentSaved(adsk.core.DocumentEventHandler):
    def notify(self, args):
        try:
            _loaded_core().on_document_saved(_app, args.document)
        except Exception:
            _log(traceback.format_exc())


class _CommandTerminated(adsk.core.ApplicationCommandEventHandler):
    """A design that was opening had no viewport: draw at the first command after."""

    def notify(self, args):
        try:
            _loaded_core().on_command_terminated(_app)
        except Exception:
            _log(traceback.format_exc())


# --------------------------------------------------------------------------- #
# the legend panel
# --------------------------------------------------------------------------- #

class _LegendCreated(adsk.core.CommandCreatedEventHandler):
    """The Color Map Legend button: open / close the panel."""

    def notify(self, args):
        try:
            h = _LegendExecute()
            args.command.execute.add(h)
            _handlers.append(h)
        except Exception:
            _log(traceback.format_exc())


class _LegendExecute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _core().toggle_legend(_app, _palette())
        except Exception:
            _fail('The Color Map legend panel could not open.')


class _PaletteIncoming(adsk.core.HTMLEventHandler):
    """The panel page asks for its content when it loads."""

    def notify(self, args):
        try:
            args.returnData = _loaded_core().on_legend_message(_app, args.action, args.data)
        except Exception:
            _log(traceback.format_exc())
            args.returnData = ''


def _palette():
    """The legend panel, created (docked right) the first time, with its message handler attached
    once. A real file URL: a plain Windows path with spaces never loads (MeasureTimeline)."""
    global _palette_handler
    pal = _ui.palettes.itemById(PALETTE_ID)
    if pal is None:
        url = pathlib.Path(PALETTE_HTML).as_uri()
        pal = _ui.palettes.add(PALETTE_ID, PALETTE_NAME, url, False, True, True, 330, 520, True)
        pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        _palette_handler = None
    if _palette_handler is None:
        _palette_handler = _PaletteIncoming()
        pal.incomingFromHTML.add(_palette_handler)
    return pal


# --------------------------------------------------------------------------- #
# add-in entry points
# --------------------------------------------------------------------------- #

def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        old = _ui.commandDefinitions.itemById(CMD_ID)
        if old:
            old.deleteMe()
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME, CMD_TOOLTIP, RES_DIR)
        h = _Created()
        cmd_def.commandCreated.add(h)
        _handlers.append(h)
        _controls[:] = _core().place_button(_ui, cmd_def)
        old = _ui.commandDefinitions.itemById(LEGEND_CMD_ID)
        if old:
            old.deleteMe()
        leg_def = _ui.commandDefinitions.addButtonDefinition(
            LEGEND_CMD_ID, LEGEND_CMD_NAME, LEGEND_TOOLTIP, LEGEND_RES_DIR)
        h = _LegendCreated()
        leg_def.commandCreated.add(h)
        _handlers.append(h)
        _controls.extend(_core().place_button(_ui, leg_def))
        for ev, h in ((_app.documentActivated, _DocumentActivated()),
                      (_app.documentSaving, _DocumentSaving()),
                      (_app.documentSaved, _DocumentSaved()),
                      (_ui.commandTerminated, _CommandTerminated())):
            ev.add(h)
            _listeners.append((ev, h))
        _core().draw_all(_app)
        _log('started, button in %d panel(s)' % len(_controls))
    except Exception:
        _fail('ColorMap failed to start.')


def stop(context):
    global _palette_handler
    try:
        pal = _ui.palettes.itemById(PALETTE_ID) if _ui else None
        if pal:
            pal.deleteMe()
        _palette_handler = None
        for ev, h in _listeners:
            try:
                ev.remove(h)
            except Exception:
                pass
        _listeners[:] = []
        try:                     # don't leave a drawing behind
            _loaded_core().on_stop(_app)
        except Exception:
            pass
        for ctrl in _controls:
            try:
                ctrl.deleteMe()
            except Exception:
                pass
        _controls[:] = []
        for cid in (CMD_ID, LEGEND_CMD_ID):
            cmd_def = _ui.commandDefinitions.itemById(cid)
            if cmd_def:
                cmd_def.deleteMe()
        _handlers[:] = []
        _log('stopped')
    except Exception:
        _fail('ColorMap failed to stop.')
