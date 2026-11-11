# title: L Bracket
# description: Wall-mount L bracket with clearance holes sized for M4 screws and a gusset.
width = param("width", 30.0, min=10, max=100)
leg_a = param("leg_a", 40.0, min=15, max=150)
leg_b = param("leg_b", 30.0, min=15, max=150)
thickness = param("thickness", 4.0, min=1.6, max=15)
screw = param("screw_diameter", 4.0, min=2, max=10)
fit = param("fit", "normal")

hole_d = tolerances.clearance_hole(screw, fit)

base = cq.Workplane("XY").box(leg_a, width, thickness, centered=(False, True, False))
wall = cq.Workplane("XY").box(thickness, width, leg_b, centered=(False, True, False))
body = base.union(wall)

gusset = (
    cq.Workplane("XZ")
    .polyline([(thickness, thickness), (thickness + leg_a / 2, thickness), (thickness, thickness + leg_b / 2)])
    .close()
    .extrude(thickness / 2, both=True)
)
body = body.union(gusset)

# Holes: two in the base plate (vertical), two in the upright (horizontal)
base_x = thickness + (leg_a - thickness) * 0.75
body = body.cut(
    cq.Workplane("XY").pushPoints([(base_x, 0)]).circle(hole_d / 2).extrude(thickness * 3).translate((0, 0, -thickness))
)
wall_z = thickness + (leg_b - thickness) * 0.65
body = body.cut(
    cq.Workplane("YZ").pushPoints([(0, wall_z)]).circle(hole_d / 2).extrude(thickness * 3).translate((-thickness, 0, 0))
)
result = body
