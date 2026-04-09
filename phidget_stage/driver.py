"""
phidget_stage/driver.py

Low-level driver for a 2-axis stepper stage controlled by Phidget stepper
modules (Phidget STC1001 or similar).

Hardware background
-------------------
The ETS XY stage uses two stepper motors wired to two independent Phidget
stepper controllers identified by serial number.  Four digital inputs (two
per axis) are used as limit switches to define the travel extents.

Motor noise
-----------
Stepper coils are energised between moves by default (holding torque keeps the
stage from drifting).  When making sensitive current measurements the energised
coil acts as an interference source.  Call `deenergize()` before measurement
and `energize()` / re-engage before the next move.  The convenience parameter
`deenergize_between_moves` in `move_to()` / `scan_raster()` handles this
automatically.

Units
-----
All public positions are in mm.  Internal conversion factors (`steps_per_mm`)
are set at construction time and match the original ETSStageController values:
  X axis: 800 steps/mm  (2 mm pitch ball screw, 1600-step/rev micro-stepping)
  Y axis: 1600 steps/mm (1 mm pitch ball screw)

Two modes
---------
"hardware"   — connects via Phidget22 library
"simulation" — no hardware needed; positions tracked in software
"""

import time
import math
import numpy as np

# ---------------------------------------------------------------------------
# Default hardware parameters (from ETSStageController.py)
# ---------------------------------------------------------------------------

# Phidget serial numbers used in the ETS lab
DEFAULT_SERIAL_X     = 523267
DEFAULT_SERIAL_Y     = 523253
DEFAULT_SERIAL_LIMIT = 527475   # VINT hub carrying the four limit-switch channels

# Limit switch VINT hub channels
LIMIT_X_HOME = 1   # chx1 — x home / negative limit
LIMIT_X_FAR  = 0   # chx2 — x far / positive limit
LIMIT_Y_HOME = 2   # chy1 — y home / negative limit
LIMIT_Y_FAR  = 3   # chy2 — y far  / positive limit

# Motor parameters
STEPS_PER_MM_X   = 800    # 2 mm pitch screw
STEPS_PER_MM_Y   = 1600   # 1 mm pitch screw
VELOCITY_LIMIT_X = 2000   # steps/s
VELOCITY_LIMIT_Y = 1000   # steps/s
CURRENT_LIMIT_X  = 0.5    # A
CURRENT_LIMIT_Y  = 0.25   # A

# Timeout waiting for motion to complete
MOVE_TIMEOUT_S = 60.0


class PhidgetStageDriver:
    """
    Low-level 2-axis stepper stage driver.

    Parameters
    ----------
    serial_x : int
        Phidget serial number for the X-axis stepper controller.
    serial_y : int
        Phidget serial number for the Y-axis stepper controller.
    serial_limit : int
        Phidget serial number for the VINT hub carrying the limit switches.
    steps_per_mm_x : float
        Conversion factor for X axis.
    steps_per_mm_y : float
        Conversion factor for Y axis.
    mode : str
        "hardware" or "simulation".
    """

    def __init__(self,
                 serial_x:     int   = DEFAULT_SERIAL_X,
                 serial_y:     int   = DEFAULT_SERIAL_Y,
                 serial_limit: int   = DEFAULT_SERIAL_LIMIT,
                 steps_per_mm_x: float = STEPS_PER_MM_X,
                 steps_per_mm_y: float = STEPS_PER_MM_Y,
                 mode: str = "simulation"):
        if mode not in ("hardware", "simulation"):
            raise ValueError(f"mode must be 'hardware' or 'simulation', got {mode!r}")

        self._mode          = mode
        self._serial_x      = serial_x
        self._serial_y      = serial_y
        self._serial_limit  = serial_limit
        self._spmx          = steps_per_mm_x
        self._spmy          = steps_per_mm_y
        self._connected     = False

        # Phidget objects (hardware mode)
        self._stepx  = None
        self._stepy  = None
        self._chx1   = None   # x home limit
        self._chx2   = None   # x far limit
        self._chy1   = None   # y home limit
        self._chy2   = None   # y far limit

        # Simulation state
        self._sim_x_steps   = 0.0   # current position in steps
        self._sim_y_steps   = 0.0
        self._sim_engaged_x = False
        self._sim_engaged_y = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        if self._connected:
            return
        if self._mode == "hardware":
            self._connect_hardware()
        self._connected = True

    def disconnect(self):
        if not self._connected:
            return
        if self._mode == "hardware":
            self._disconnect_hardware()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # Motor engagement (coil energize / de-energize)
    # ------------------------------------------------------------------

    def energize(self, axis: str = "both"):
        """
        Energize (engage) motor coil(s).

        Parameters
        ----------
        axis : str
            "x", "y", or "both".
        """
        ax = axis.lower()
        if ax in ("x", "both"):
            if self._mode == "hardware":
                self._stepx.setEngaged(True)
            else:
                self._sim_engaged_x = True
        if ax in ("y", "both"):
            if self._mode == "hardware":
                self._stepy.setEngaged(True)
            else:
                self._sim_engaged_y = True

    def deenergize(self, axis: str = "both"):
        """
        De-energize (disengage) motor coil(s) to reduce electrical noise
        during measurements.

        Parameters
        ----------
        axis : str
            "x", "y", or "both".
        """
        ax = axis.lower()
        if ax in ("x", "both"):
            if self._mode == "hardware":
                self._stepx.setEngaged(False)
            else:
                self._sim_engaged_x = False
        if ax in ("y", "both"):
            if self._mode == "hardware":
                self._stepy.setEngaged(False)
            else:
                self._sim_engaged_y = False

    def is_energized(self) -> tuple[bool, bool]:
        """Return (x_engaged, y_engaged)."""
        if self._mode == "hardware":
            return self._stepx.getEngaged(), self._stepy.getEngaged()
        return self._sim_engaged_x, self._sim_engaged_y

    # ------------------------------------------------------------------
    # Position
    # ------------------------------------------------------------------

    def position(self) -> tuple[float, float]:
        """
        Return current (x, y) position in mm.

        The position is read from the Phidget position counter and reflects
        the last commanded position (open-loop stepper, no encoder).
        """
        if self._mode == "hardware":
            x_mm = self._stepx.getPosition() / self._spmx
            y_mm = self._stepy.getPosition() / self._spmy
        else:
            x_mm = self._sim_x_steps / self._spmx
            y_mm = self._sim_y_steps / self._spmy
        return x_mm, y_mm

    # ------------------------------------------------------------------
    # Single-axis moves (relative, in steps)
    # ------------------------------------------------------------------

    def _move_steps_x(self, steps: float):
        """Move X by a relative number of steps, stopping at limits."""
        if self._mode == "simulation":
            self._sim_x_steps += steps
            return

        target = self._stepx.getPosition() + steps
        self._stepx.setTargetPosition(target)
        t0 = time.monotonic()
        while time.monotonic() - t0 < MOVE_TIMEOUT_S:
            at_home = self._chx1.getState() == 1 and steps < 0
            at_far  = self._chx2.getState() == 1 and steps > 0
            if at_home or at_far:
                self._stepx.setTargetPosition(self._stepx.getPosition())
                break
            if self._stepx.getPosition() == target:
                break
            time.sleep(0.005)

    def _move_steps_y(self, steps: float):
        """Move Y by a relative number of steps, stopping at limits."""
        if self._mode == "simulation":
            self._sim_y_steps += steps
            return

        target = self._stepy.getPosition() + steps
        self._stepy.setTargetPosition(target)
        t0 = time.monotonic()
        while time.monotonic() - t0 < MOVE_TIMEOUT_S:
            at_home = self._chy1.getState() == 1 and steps < 0
            at_far  = self._chy2.getState() == 1 and steps > 0
            if at_home or at_far:
                self._stepy.setTargetPosition(self._stepy.getPosition())
                break
            if self._stepy.getPosition() == target:
                break
            time.sleep(0.005)

    # ------------------------------------------------------------------
    # Public move API
    # ------------------------------------------------------------------

    def move_to(self, x_mm: float | None = None,
                       y_mm: float | None = None,
                       deenergize_after: bool = False):
        """
        Move to an absolute position.

        Parameters
        ----------
        x_mm : float, optional
            Target X position in mm.  None = do not move X.
        y_mm : float, optional
            Target Y position in mm.  None = do not move Y.
        deenergize_after : bool
            If True, de-energize both coils after the move completes.
            Use this when measurement follows immediately.
        """
        self.energize("both")

        if x_mm is not None:
            target_steps = round(x_mm * self._spmx)
            current_x = (self._stepx.getPosition() if self._mode == "hardware"
                         else self._sim_x_steps)
            self._move_steps_x(target_steps - current_x)

        if y_mm is not None:
            target_steps = round(y_mm * self._spmy)
            current_y = (self._stepy.getPosition() if self._mode == "hardware"
                         else self._sim_y_steps)
            self._move_steps_y(target_steps - current_y)

        if deenergize_after:
            self.deenergize("both")

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
            De-energize coils after move.
        """
        x_now, y_now = self.position()
        self.move_to(x_now + dx_mm, y_now + dy_mm,
                     deenergize_after=deenergize_after)

    # ------------------------------------------------------------------
    # Homing
    # ------------------------------------------------------------------

    def home(self, axis: str = "both"):
        """
        Drive axis to the home limit switch and reset the position origin.

        Parameters
        ----------
        axis : str
            "x", "y", or "both".  X is always homed before Y to avoid
            mechanical collisions (same convention as ETSStageController).
        """
        if self._mode == "simulation":
            if axis in ("x", "both"):
                self._sim_x_steps = 0.0
            if axis in ("y", "both"):
                self._sim_y_steps = 0.0
            return

        ax = axis.lower()
        if ax in ("x", "both"):
            self._home_axis_hardware("x")
        if ax in ("y", "both"):
            self._home_axis_hardware("y")

    def _home_axis_hardware(self, ax: str):
        """Drive one axis to its home switch using velocity control."""
        from Phidget22.StepperControlMode import StepperControlMode

        step  = self._stepx if ax == "x" else self._stepy
        lim   = self._chx1  if ax == "x" else self._chy1
        vlim  = VELOCITY_LIMIT_X if ax == "x" else VELOCITY_LIMIT_Y

        step.setEngaged(True)

        # If already at home, nudge away first
        if lim.getState() == 1:
            self._move_steps_x(6000) if ax == "x" else self._move_steps_y(6000)
            time.sleep(0.5)

        # Velocity-mode drive toward home
        step.setControlMode(StepperControlMode.CONTROL_MODE_RUN)
        step.setVelocityLimit(-vlim)

        t0 = time.monotonic()
        while time.monotonic() - t0 < MOVE_TIMEOUT_S:
            if lim.getState() == 1:
                break
            time.sleep(0.005)

        # Return to position-control mode (stops motion)
        step.setControlMode(StepperControlMode.CONTROL_MODE_STEP)
        time.sleep(0.1)

        # Small back-off to relieve the switch
        if ax == "x":
            self._move_steps_x(-10)
        else:
            self._move_steps_y(-10)

        # Re-open channel so internal position counter resets to 0
        time.sleep(0.2)
        step.close()
        time.sleep(0.3)
        self._reopen_stepper(ax)

    def _reopen_stepper(self, ax: str):
        """Reopen a stepper channel after homing to reset its position to 0."""
        from Phidget22.Devices.Stepper import Stepper
        from Phidget22.StepperControlMode import StepperControlMode

        if ax == "x":
            s = Stepper()
            s.setDeviceSerialNumber(self._serial_x)
            s.setChannel(0)
            s.setHubPort(0)
            s.setIsRemote(False)
            s.openWaitForAttachment(5000)
            s.setCurrentLimit(CURRENT_LIMIT_X)
            s.setEngaged(True)
            s.setControlMode(StepperControlMode.CONTROL_MODE_STEP)
            s.setVelocityLimit(VELOCITY_LIMIT_X)
            self._stepx = s
        else:
            s = Stepper()
            s.setDeviceSerialNumber(self._serial_y)
            s.setChannel(0)
            s.setHubPort(0)
            s.setIsRemote(False)
            s.openWaitForAttachment(5000)
            s.setCurrentLimit(CURRENT_LIMIT_Y)
            s.setEngaged(True)
            s.setControlMode(StepperControlMode.CONTROL_MODE_STEP)
            s.setVelocityLimit(VELOCITY_LIMIT_Y)
            self._stepy = s

    # ------------------------------------------------------------------
    # Raster scan path generator
    # ------------------------------------------------------------------

    @staticmethod
    def raster_grid(x0: float, x1: float,
                    y0: float, y1: float,
                    step_mm: float) -> list[tuple[float, float]]:
        """
        Generate a boustrophedon (snake) raster grid of (x, y) positions.

        Parameters
        ----------
        x0, x1 : float  — X extent in mm (x0 < x1)
        y0, y1 : float  — Y extent in mm (y0 < y1)
        step_mm : float — grid spacing in mm

        Returns
        -------
        list of (x_mm, y_mm) tuples in scan order.
        """
        xs = np.arange(x0, x1 + step_mm * 0.5, step_mm)
        ys = np.arange(y0, y1 + step_mm * 0.5, step_mm)

        grid = []
        for i, x in enumerate(xs):
            col = list(ys) if i % 2 == 0 else list(reversed(ys))
            for y in col:
                grid.append((float(round(x, 6)), float(round(y, 6))))
        return grid

    # ------------------------------------------------------------------
    # Hardware connect / disconnect internals
    # ------------------------------------------------------------------

    def _connect_hardware(self):
        try:
            from Phidget22.Devices.Stepper      import Stepper
            from Phidget22.Devices.DigitalInput  import DigitalInput
            from Phidget22.StepperControlMode    import StepperControlMode
        except ImportError as e:
            raise ImportError(
                "Phidget22 not installed. Run: pip install Phidget22"
            ) from e

        # Limit switches
        self._chx1 = self._open_di(self._serial_limit, LIMIT_X_HOME)
        self._chx2 = self._open_di(self._serial_limit, LIMIT_X_FAR)
        self._chy1 = self._open_di(self._serial_limit, LIMIT_Y_HOME)
        self._chy2 = self._open_di(self._serial_limit, LIMIT_Y_FAR)

        # X stepper
        sx = Stepper()
        sx.setDeviceSerialNumber(self._serial_x)
        sx.setChannel(0)
        sx.setHubPort(0)
        sx.setIsRemote(False)
        sx.openWaitForAttachment(5000)
        sx.setCurrentLimit(CURRENT_LIMIT_X)
        sx.setEngaged(True)
        sx.setControlMode(StepperControlMode.CONTROL_MODE_STEP)
        sx.setVelocityLimit(VELOCITY_LIMIT_X)
        self._stepx = sx

        # Y stepper
        sy = Stepper()
        sy.setDeviceSerialNumber(self._serial_y)
        sy.setChannel(0)
        sy.setHubPort(0)
        sy.setIsRemote(False)
        sy.openWaitForAttachment(5000)
        sy.setCurrentLimit(CURRENT_LIMIT_Y)
        sy.setEngaged(True)
        sy.setControlMode(StepperControlMode.CONTROL_MODE_STEP)
        sy.setVelocityLimit(VELOCITY_LIMIT_Y)
        self._stepy = sy

    def _open_di(self, serial: int, channel: int):
        from Phidget22.Devices.DigitalInput import DigitalInput
        ch = DigitalInput()
        ch.setDeviceSerialNumber(serial)
        ch.setChannel(channel)
        ch.setHubPort(0)
        ch.setIsRemote(False)
        ch.openWaitForAttachment(5000)
        return ch

    def _disconnect_hardware(self):
        for obj in (self._stepx, self._stepy):
            if obj is not None:
                try:
                    obj.setEngaged(False)
                    obj.close()
                except Exception:
                    pass
        for obj in (self._chx1, self._chx2, self._chy1, self._chy2):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()
