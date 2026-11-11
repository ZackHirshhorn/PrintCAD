# title: Electronics Enclosure
# description: Rounded box with screw posts and a lid, printed together side by side.
length = param("length", 60.0, min=30, max=200)
width = param("width", 40.0, min=20, max=200)
height = param("height", 25.0, min=12, max=100)
wall = param("wall", 2.0, min=1.2, max=6)
post_d = param("post_diameter", 6.0, min=4, max=12)
screw_d = param("screw_diameter", 2.5, min=1.6, max=5)
lid_gap = param("lid_gap", 0.2, min=0.05, max=1)

# Body: hollow box open at the top
outer = cq.Workplane("XY").box(length, width, height, centered=(True, True, False)).edges("|Z").fillet(3)
inner = (
    cq.Workplane("XY")
    .workplane(offset=wall)
    .rect(length - 2 * wall, width - 2 * wall)
    .extrude(height)
    .edges("|Z")
    .fillet(max(0.5, 3 - wall))
)
body = outer.cut(inner)

# Screw posts in the corners
# Posts overlap the walls slightly so they fuse (a tangent contact would be non-manifold)
px = length / 2 - wall - post_d / 2 + 0.5
py = width / 2 - wall - post_d / 2 + 0.5
corners = [(px, py), (-px, py), (px, -py), (-px, -py)]
posts = cq.Workplane("XY").workplane(offset=wall / 2).pushPoints(corners).circle(post_d / 2).extrude(height - wall / 2 - 1)
body = body.union(posts)
body = body.cut(
    cq.Workplane("XY").workplane(offset=height - 8).pushPoints(corners).circle(screw_d / 2).extrude(8)
)

# Lid: plate with a lip that fits inside the body, placed beside the body
lid = (
    cq.Workplane("XY")
    .box(length, width, wall, centered=(True, True, False))
    .edges("|Z")
    .fillet(3)
)
lip = (
    cq.Workplane("XY")
    .workplane(offset=wall)
    .rect(length - 2 * wall - 2 * lid_gap, width - 2 * wall - 2 * lid_gap)
    .extrude(1.5)
)
lip = lip.cut(
    cq.Workplane("XY").workplane(offset=wall).rect(length - 4 * wall, width - 4 * wall).extrude(1.5)
)
lid = lid.union(lip)
lid = lid.cut(
    cq.Workplane("XY").pushPoints(corners).circle(tolerances.clearance_hole(screw_d, "normal") / 2).extrude(wall)
)
lid = lid.translate((0, width + 10, 0))

result = body.union(lid)
