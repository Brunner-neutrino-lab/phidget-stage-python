"""
Phidget 2-axis stage basic usage — simulation mode.

Demonstrates:
  1. Absolute and relative moves
  2. Manual motor de-energization
  3. Raster scan with de-energization between moves
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from phidget_stage import StageController

stage = StageController(mode="simulation")

with stage:
    # --- 1. Home ---
    print("1. Homing")
    stage.home()
    print(f"   Position after home: {stage.position()}")

    # --- 2. Absolute move ---
    print("\n2. Absolute move to (10.0, 5.0) mm")
    stage.move_to(x_mm=10.0, y_mm=5.0)
    print(f"   Position: {stage.position()}")

    # --- 3. Relative move ---
    print("\n3. Relative move (+2.0, -1.0) mm")
    stage.move_by(dx_mm=2.0, dy_mm=-1.0)
    print(f"   Position: {stage.position()}")

    # --- 4. Manual de-energize before a measurement ---
    print("\n4. Manual de-energize / energize")
    stage.move_to(x_mm=15.0, y_mm=5.0)
    stage.deenergize()
    print(f"   Coils de-energized: {stage.is_energized()}")
    # ... do your measurement here ...
    stage.energize()
    print(f"   Coils re-energized: {stage.is_energized()}")

    # --- 5. Move with automatic de-energize ---
    print("\n5. Move with deenergize_after=True")
    stage.move_to(x_mm=20.0, y_mm=10.0, deenergize_after=True)
    print(f"   Position: {stage.position()}, coils: {stage.is_energized()}")
    stage.energize()  # re-engage before next move

    # --- 6. Raster scan ---
    measurements = []

    def measure(x, y):
        # Placeholder: in real use, trigger IV or pulse acquisition here
        measurements.append((x, y))

    print("\n6. Raster scan 0–3 mm x 0–2 mm, 1 mm step, de-energize between moves")
    visited = stage.scan_raster(
        x0=0.0, x1=3.0,
        y0=0.0, y1=2.0,
        step_mm=1.0,
        callback=measure,
        settle_s=0.0,
        deenergize_between_moves=True,
        on_progress=lambda s, t: print(f"   point {s}/{t}  pos={stage.position()}"),
    )
    print(f"   {len(visited)} positions visited")

print("\nDone.")
