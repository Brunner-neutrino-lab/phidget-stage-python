"""
phidget_stage/gui.py

NiceGUI control panel for the Phidget XY stage.

Same two-mode pattern as the b2987b / vx2740 / pulse_mux panels:

  - Standalone (`python -m phidget_stage.gui`): opens a browser
    with a Connection card (three Phidget serials + connect/
    disconnect) that creates and owns its own StageController.

  - Embedded (`build_page(get_controller=..., show_connection=False)`):
    called from a parent NiceGUI app (the ETS DAQ web shell). The
    parent passes a getter that returns the shared controller; this
    panel hides its Connection card and drives the parent's
    controller.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional

from nicegui import ui

from .controller import StageController


# ---------------------------------------------------------------------------
# Style — xsphere/DAQ palette
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --bg:#11151c; --panel:#1b2230; --panel2:#232c3d;
  --fg:#dde3ee; --mut:#8a93a6;
  --ok:#3fb950; --warn:#d29922; --bad:#f85149; --acc:#58a6ff;
  --line:#2d3648;
}
html, body, .nicegui-content { background:var(--bg) !important; color:var(--fg);
  font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; margin:0; }
.pill { padding:.15rem .55rem; border-radius:999px; font-size:.78rem;
  font-weight:600; white-space:nowrap; display:inline-flex; align-items:center; gap:.3rem; }
.pill.ok   { background:rgba(63,185,80,.18);  color:var(--ok); }
.pill.bad  { background:rgba(248,81,73,.18);  color:var(--bad); }
.pill.warn { background:rgba(210,153,34,.18); color:var(--warn); }
.pill.mut  { background:rgba(138,147,166,.15);color:var(--mut); }
.q-card, .stage-card {
  background:var(--panel) !important; color:var(--fg) !important;
  border:1px solid var(--line); border-radius:10px;
  box-shadow:none !important; padding:.55rem .85rem .7rem !important;
}
.stage-card h2 { font-size:.92rem; margin:.05rem 0 .45rem; color:var(--acc);
  font-weight:600; letter-spacing:.3px; }
.q-btn { background:var(--panel2) !important; color:var(--fg) !important;
  border:1px solid var(--line) !important; border-radius:6px !important;
  box-shadow:none !important; padding:.18rem .65rem !important;
  min-height:32px !important; text-transform:none !important; }
.q-btn:hover { border-color:var(--acc) !important; }
.q-btn[data-q-color="primary"], .q-btn.bg-primary {
  background:var(--acc) !important; color:#08111f !important;
  border-color:var(--acc) !important; font-weight:600 !important; }
.q-btn[data-q-color="negative"], .q-btn.bg-negative {
  background:transparent !important; color:var(--bad) !important;
  border-color:var(--bad) !important; }
.q-btn[data-q-color="warning"], .q-btn.bg-warning {
  background:transparent !important; color:var(--warn) !important;
  border-color:var(--warn) !important; }
.q-field__control, .q-field--filled .q-field__control {
  background:var(--panel2) !important; border:1px solid var(--line) !important;
  border-radius:6px !important; min-height:32px !important; color:var(--fg) !important; }
.q-field__label, .q-field__native, .q-field input { color:var(--fg) !important; }
.q-field__label { color:var(--mut) !important; }
.q-field--filled .q-field__control:before,
.q-field--filled .q-field__control:after { display:none !important; }
.q-tab { color:var(--mut) !important; text-transform:none !important; }
.q-tab--active { color:var(--acc) !important; }
.q-tab__indicator { background:var(--acc) !important; }
.q-log, .nicegui-log { background:var(--panel2) !important; color:var(--fg) !important;
  border:1px solid var(--line); border-radius:6px;
  font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.82rem; }
.num { font-variant-numeric:tabular-nums; }
"""


async def _in_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


# ===========================================================================
# build_page
# ===========================================================================

def build_page(get_controller: Optional[Callable[[], Optional[StageController]]] = None,
               *, show_connection: Optional[bool] = None) -> None:
    """Render the Phidget stage control panel into the current container."""
    if show_connection is None:
        show_connection = (get_controller is None)

    _own = {"ctrl": None}
    if get_controller is None:
        def get_controller():
            return _own["ctrl"]

    log = ui.log(max_lines=120).classes("h-32 w-full")
    def log_msg(s: str): log.push(f"[{time.strftime('%H:%M:%S')}] {s}")

    def ensure_ctrl() -> Optional[StageController]:
        c = get_controller()
        if c is None:
            log_msg("not connected" + (" — use the Connection card"
                                       if show_connection else
                                       " — connect on the DAQ's Connections tab"))
            return None
        return c

    # --- Top row: connection (optional) + position display ---

    with ui.row().classes("w-full gap-3 items-start"):

        if show_connection:
            with ui.card().classes("stage-card"):
                ui.html("<h2>connection</h2>")
                sx = ui.number(label="x stepper serial",   value=523267, step=1).classes("w-40 num")
                sy = ui.number(label="y stepper serial",   value=523253, step=1).classes("w-40 num")
                sh = ui.number(label="limit hub serial",   value=527475, step=1).classes("w-40 num")
                mode_in = ui.select(["simulation", "hardware"],
                                    value="simulation", label="mode").classes("w-40")
                conn_pill = ui.html('<span class="pill mut">disconnected</span>')

                def set_pill(text: str, cls: str):
                    conn_pill.content = f'<span class="pill {cls}">{text}</span>'

                async def do_connect():
                    c = StageController(serial_x=int(sx.value), serial_y=int(sy.value),
                                        serial_limit=int(sh.value), mode=mode_in.value)
                    set_pill("connecting…", "warn")
                    try:
                        await _in_thread(c.connect)
                        _own["ctrl"] = c
                        set_pill("OK — stage connected", "ok")
                        log_msg(f"connected ({mode_in.value})")
                    except Exception as e:
                        set_pill(f"FAIL: {type(e).__name__}", "bad")
                        log_msg(f"connect FAIL: {type(e).__name__}: {e}")

                async def do_disconnect():
                    c = _own["ctrl"]
                    if c is None: return
                    try: await _in_thread(c.disconnect)
                    except Exception as e: log_msg(f"disconnect warn: {e}")
                    _own["ctrl"] = None
                    set_pill("disconnected", "mut")
                    log_msg("disconnected")

                with ui.row().classes("mt-1 gap-2"):
                    ui.button("connect",    on_click=do_connect).props("color=primary")
                    ui.button("disconnect", on_click=do_disconnect).props("color=negative flat")

        # ----------- Position display + read -----------
        with ui.card().classes("stage-card"):
            ui.html("<h2>position</h2>")
            pos_lbl = ui.label("x = — mm, y = — mm").classes("num text-lg")
            energ_lbl = ui.label("coils: —").classes("num text-sm text-gray-400")

            async def read_pos():
                c = ensure_ctrl()
                if c is None: return
                try:
                    x, y = await _in_thread(c.position)
                    pos_lbl.text = f"x = {x:+.4f} mm,  y = {y:+.4f} mm"
                    xen, yen = await _in_thread(c.is_energized)
                    energ_lbl.text = (f"coils: x={'on' if xen else 'off'}, "
                                      f"y={'on' if yen else 'off'}")
                except Exception as e:
                    log_msg(f"read FAIL: {type(e).__name__}: {e}")

            ui.button("read position", on_click=read_pos).props("color=primary")

        # ----------- Energize / deenergize -----------
        with ui.card().classes("stage-card"):
            ui.html("<h2>coils</h2>")
            axis_sel = ui.select(["both", "x", "y"], value="both",
                                 label="axis").classes("w-32")

            async def do_energize():
                c = ensure_ctrl()
                if c is None: return
                try:
                    await _in_thread(c.energize, str(axis_sel.value))
                    log_msg(f"energize {axis_sel.value}")
                except Exception as e:
                    log_msg(f"energize FAIL: {type(e).__name__}: {e}")

            async def do_deenergize():
                c = ensure_ctrl()
                if c is None: return
                try:
                    await _in_thread(c.deenergize, str(axis_sel.value))
                    log_msg(f"deenergize {axis_sel.value}")
                except Exception as e:
                    log_msg(f"deenergize FAIL: {type(e).__name__}: {e}")

            with ui.row().classes("gap-2 mt-1"):
                ui.button("energize",   on_click=do_energize).props("color=primary")
                ui.button("deenergize", on_click=do_deenergize)

    # --- Second row: move absolute, move relative, home ---

    with ui.row().classes("w-full gap-3 items-start"):

        with ui.card().classes("stage-card"):
            ui.html("<h2>move absolute</h2>")
            x_in = ui.number(label="x (mm)", value=0.0, step=0.1, format="%.3f").classes("w-32 num")
            y_in = ui.number(label="y (mm)", value=0.0, step=0.1, format="%.3f").classes("w-32 num")
            denerg_after = ui.switch("de-energize after move", value=True)

            async def do_move():
                c = ensure_ctrl()
                if c is None: return
                tx, ty = float(x_in.value), float(y_in.value)
                log_msg(f"move → ({tx:.3f}, {ty:.3f}) mm")
                try:
                    await _in_thread(c.move_to, tx, ty, bool(denerg_after.value))
                    x, y = await _in_thread(c.position)
                    pos_lbl.text = f"x = {x:+.4f} mm,  y = {y:+.4f} mm"
                    log_msg(f"  arrived ({x:.4f}, {y:.4f}) mm")
                except Exception as e:
                    log_msg(f"move FAIL: {type(e).__name__}: {e}")

            ui.button("move", on_click=do_move).props("color=primary")

        with ui.card().classes("stage-card"):
            ui.html("<h2>move relative</h2>")
            dx_in = ui.number(label="dx (mm)", value=0.0, step=0.1, format="%.3f").classes("w-32 num")
            dy_in = ui.number(label="dy (mm)", value=0.0, step=0.1, format="%.3f").classes("w-32 num")

            async def do_move_rel():
                c = ensure_ctrl()
                if c is None: return
                dx, dy = float(dx_in.value), float(dy_in.value)
                log_msg(f"move by ({dx:+.3f}, {dy:+.3f}) mm")
                try:
                    await _in_thread(c.move_by, dx, dy, bool(denerg_after.value))
                    x, y = await _in_thread(c.position)
                    pos_lbl.text = f"x = {x:+.4f} mm,  y = {y:+.4f} mm"
                    log_msg(f"  now at ({x:.4f}, {y:.4f}) mm")
                except Exception as e:
                    log_msg(f"move_by FAIL: {type(e).__name__}: {e}")

            ui.button("move by", on_click=do_move_rel).props("color=primary")

        with ui.card().classes("stage-card"):
            ui.html("<h2>home</h2>")
            home_axis = ui.select(["both", "x", "y"], value="both",
                                  label="axis").classes("w-32")
            ui.label(
                "Drives the selected axis (or both) to the home limit switch "
                "and resets the position origin to 0."
            ).classes("text-xs text-gray-400")

            async def do_home():
                c = ensure_ctrl()
                if c is None: return
                log_msg(f"homing {home_axis.value}…")
                try:
                    await _in_thread(c.home, str(home_axis.value))
                    x, y = await _in_thread(c.position)
                    pos_lbl.text = f"x = {x:+.4f} mm,  y = {y:+.4f} mm"
                    log_msg(f"  homed → ({x:.4f}, {y:.4f}) mm")
                except Exception as e:
                    log_msg(f"home FAIL: {type(e).__name__}: {e}")

            ui.button("home", on_click=do_home).props("color=warning")


# ---------------------------------------------------------------------------
# Standalone entry — `python -m phidget_stage.gui`
# ---------------------------------------------------------------------------

def main():
    import argparse
    p = argparse.ArgumentParser(description="Phidget XY stage web GUI")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8769)
    args = p.parse_args()

    @ui.page("/")
    def index():
        ui.add_head_html(f"<style>{_CSS}</style>")
        ui.dark_mode().enable()
        with ui.element("header").style(
            "display:flex;align-items:center;gap:.8rem;"
            "padding:.55rem 1rem;background:var(--panel);"
            "border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5"
        ):
            ui.html("<h1 style='font-size:1.05rem;font-weight:600;margin:0'>"
                    "Phidget · XY stage</h1>")
        build_page()

    ui.run(host=args.host, port=args.port, reload=False,
           title="Phidget XY Stage", show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
