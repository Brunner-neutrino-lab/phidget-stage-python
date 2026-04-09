"""
phidget_stage/controller.py

High-level controller for the 2-axis Phidget stepper stage.

Wraps the low-level driver with:
  - move_to() / move_by()  with optional motor de-energization
  - home()
  - scan_raster()          boustrophedon 2-D scan with a user callback
    at each grid point

Motor noise notes
-----------------
Stepper coils left energised create electrical interference that can raise the
noise floor on sensitive current measurements (picoammeter, SiPM dark current).
Set `deenergize_between_moves=True` in scan_raster() to automatically
de-energize both coils before the measurement callback fires and re-energize
before each subsequent move.

You can also call de-energize() / energize() directly for manual control.
"""

import time
from typing import Callable

import numpy as np

from .driver import (PhidgetStageDriver,
                     DEFAULT_SERIAL_X, DEFAULT_SERIAL_Y, DEFAULT_SERIAL_LIMIT,
                     STEPS_PER_MM_X, STEPS_PER_MM_Y)


class StageController:
    """
    High-level 2-axis stage controller.

    Parameters
    ----------
    serial_x, serial_y, serial_limit : int
        Phidget serial numbers.  Defaults match the ETS lab hardware.
    steps_per_mm_x, steps_per_mm_y : float
        Conversion factors.
    mode : str
        "hardware" or "simulation".
    """

    def __init__(self,
                 serial_x:        int   = DEFAULT_SERIAL_X,
                 serial_y:        int   = DEFAULT_SERIAL_Y,
                 serial_limit:    int   = DEFAULT_SERIAL_LIMIT,
                 steps_per_mm_x:  float = STEPS_PER_MM_X,
                 steps_per_mm_y:  float = STEPS_PER_MM_Y,
                 mode: str = "simulation"):
        self._drv = PhidgetStageDriver(
            serial_x        = serial_x,
            serial_y        = serial_y,
            serial_limit    = serial_limit,
            steps_per_mm_x  = steps_per_mm_x,
            steps_per_mm_y  = steps_per_mm_y,
            mode            = mode,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self):
        self._drv.connect()

    def disconnect(self):
        self._drv.deenergize("both")
        self._drv.disconnect()

    @property
    def mode(self) -> str:
        return self._drv.mode

    # ------------------------------------------------------------------
    # Motor coil control
    # ------------------------------------------------------------------

    def energize(self, axis: str = "both"):
        """Energize (engage) motor coil(s). axis: 'x', 'y', or 'both'."""
        self._drv.energize(axis)

    def deenergize(self, axis: str = "both"):
        """
        De-energize (disengage) motor coil(s).

        Safe to call before measurements to reduce electrical noise.
        The stage holds position mechanically while de-energized; re-energize
        before the next move.
        """
        self._drv.deenergize(axis)

    def is_energized(self) -> tuple[bool, bool]:
        """Return (x_engaged, y_engaged)."""
        return self._drv.is_energized()

    # ------------------------------------------------------------------
    # Position
    # ------------------------------------------------------------------

    def position(self) -> tuple[float, float]:
        """Return current (x_mm, y_mm)."""
        return self._drv.position()

    # ------------------------------------------------------------------
    # Motion
    # ------------------------------------------------------------------

    def move_to(self, x_mm: float | None = None,
                       y_mm: float | None = None,
                       deenergize_after: bool = False):
        """
        Move to an absolute position.

        Parameters
        ----------
        x_mm : float, optional
            Target X in mm.  None = do not move X.
        y_mm : float, optional
            Target Y in mm.  None = do not move Y.
        deenergize_after : bool
            De-energize coils after the move.  Use this when a measurement
            immediately follows.
        """
        self._drv.move_to(x_mm, y_mm, deenergize_after=deenergize_after)

    def move_by(self, dx_mm: float = 0.0,
                       dy_mm: float = 0.0,
                       deenergize_after: bool = False):
        """
        Move by a relative displacement.

        Parameters
        ----------
        dx_mm, dy_mm : float
            Displacement in mm.
        deenergize_after : bool
            De-energize coils after the move.
        """
        self._drv.move_by(dx_mm, dy_mm, deenergize_after=deenergize_after)

    def home(self, axis: str = "both"):
        """
        Drive to the home limit switch and reset position origin to (0, 0).

        Parameters
        ----------
        axis : str
            "x", "y", or "both".
        """
        self._drv.home(axis)

    # ------------------------------------------------------------------
    # Raster scan
    # ------------------------------------------------------------------

    def scan_raster(self,
                    x0: float, x1: float,
                    y0: float, y1: float,
                    step_mm: float,
                    callback: Callable[[float, float], None],
                    settle_s: float = 0.0,
                    deenergize_between_moves: bool = True,
                    on_progress: Callable[[int, int], None] | None = None
                    ) -> list[tuple[float, float]]:
        """
        Execute a boustrophedon raster scan over the rectangle
        (x0, y0) – (x1, y1) in step_mm increments.

        At each grid point the function:
          1. Moves to the next (x, y) position.
          2. Optionally de-energizes the motor coils.
          3. Waits settle_s seconds.
          4. Calls callback(x_mm, y_mm) — do your measurement here.
          5. Re-energizes coils (if de-energized) before the next move.

        Parameters
        ----------
        x0, x1 : float   X range in mm (x0 ≤ x1)
        y0, y1 : float   Y range in mm (y0 ≤ y1)
        step_mm : float  Grid spacing in mm
        callback : Callable[[float, float], None]
            Called at each position with (x_mm, y_mm).  This is where
            you trigger your IV sweep / pulse acquisition / etc.
        settle_s : float
            Settling delay after each move before callback fires (s).
        deenergize_between_moves : bool
            If True, de-energize both coils before each callback and
            re-energize before the next move.  Reduces motor electrical
            noise during measurements.
        on_progress : Callable[[int, int], None], optional
            Called after each point as on_progress(step, total).

        Returns
        -------
        list of (x_mm, y_mm) tuples in the order visited.
        """
        grid = PhidgetStageDriver.raster_grid(x0, x1, y0, y1, step_mm)
        total = len(grid)
        visited = []

        for step_idx, (x, y) in enumerate(grid):
            # Move — always energized during motion
            self._drv.energize("both")
            self._drv.move_to(x, y, deenergize_after=False)

            if deenergize_between_moves:
                self._drv.deenergize("both")

            if settle_s > 0:
                time.sleep(settle_s)

            callback(x, y)
            visited.append((x, y))

            if deenergize_between_moves:
                self._drv.energize("both")

            if on_progress is not None:
                on_progress(step_idx + 1, total)

        # Leave coils de-energized at the end of a scan
        self._drv.deenergize("both")
        return visited

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()
