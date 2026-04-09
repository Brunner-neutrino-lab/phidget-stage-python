# phidget-stage

Python driver and controller for the ETS 2-axis Phidget stepper stage.

Extracted and modernised from `scanIV/ETSStageController.py`.

## Quick Start

```bash
pip install -r requirements.txt

python examples/basic_usage.py   # simulation mode, no hardware needed
```

## API

```python
from phidget_stage import StageController

with StageController(mode="hardware") as stage:

    stage.home()                          # drive to limit switches, zero origin

    # Absolute move
    stage.move_to(x_mm=10.0, y_mm=5.0)

    # Relative move
    stage.move_by(dx_mm=2.0, dy_mm=-1.0)

    # ---- Motor noise mitigation ----------------------------------------
    # After moving, de-energize before measuring to reduce electrical noise.
    stage.move_to(x_mm=15.0, y_mm=5.0, deenergize_after=True)
    # ... measure ...
    stage.energize()                      # re-engage before next move

    # Or use the convenience methods directly:
    stage.deenergize()
    # ... measure ...
    stage.energize()

    # ---- Raster scan ----------------------------------------------------
    def my_measurement(x, y):
        # trigger IV sweep / pulse acquisition here
        pass

    stage.scan_raster(
        x0=0.0, x1=10.0,
        y0=0.0, y1=10.0,
        step_mm=1.0,
        callback=my_measurement,
        settle_s=0.1,                     # wait 100 ms after each move
        deenergize_between_moves=True,    # coils off during measurement
    )
```

## Motor de-energization

Stepper motor coils act as interference sources when kept energised.
For sensitive measurements (sub-nA currents, SiPM dark current IV):

| Scenario | Setting |
|----------|---------|
| Motor noise is acceptable (e.g. fast survey) | `deenergize_between_moves=False` |
| Low-noise measurement required | `deenergize_between_moves=True` or call `stage.deenergize()` manually |

The stage holds its mechanical position when de-energized as long as the
lead screw provides enough friction (typical for ball screws under light load).

## Hardware parameters

Default serial numbers match the ETS McGill/Yale lab hardware:

| Parameter | Value | Source |
|-----------|-------|--------|
| X stepper serial | 523267 | ETSStageController.py |
| Y stepper serial | 523253 | ETSStageController.py |
| Limit switch hub serial | 527475 | ETSStageController.py |
| X steps/mm | 800 | 2 mm pitch ball screw |
| Y steps/mm | 1600 | 1 mm pitch ball screw |
| X current limit | 0.5 A | ETSStageController.py |
| Y current limit | 0.25 A | ETSStageController.py |

Override at construction time if hardware changes:

```python
stage = StageController(
    serial_x=123456,
    steps_per_mm_x=400,
    mode="hardware",
)
```
