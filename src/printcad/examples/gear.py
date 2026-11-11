# title: Spur Gear
# description: Involute spur gear with a bore and hub, sized by module and tooth count.
teeth = param("teeth", 20, min=8, max=80)
module = param("module", 2.0, min=0.5, max=6)
thickness = param("thickness", 8.0, min=2, max=40)
pressure_angle = param("pressure_angle", 20.0, min=14.5, max=25)
bore = param("bore", 5.0, min=0.0, max=60)

pitch_r = module * teeth / 2.0
base_r = pitch_r * math.cos(math.radians(pressure_angle))
outer_r = pitch_r + module
root_r = max(pitch_r - 1.25 * module, 0.5)


def involute(t):
    # Point on the involute of the base circle at roll angle t
    return (
        base_r * (math.cos(t) + t * math.sin(t)),
        base_r * (math.sin(t) - t * math.cos(t)),
    )


# Roll angle at which the involute reaches the outer radius
t_max = math.sqrt(max((outer_r / base_r) ** 2 - 1, 0.0))
t_pitch = math.sqrt(max((pitch_r / base_r) ** 2 - 1, 0.0))
inv_pitch = math.atan2(*involute(t_pitch)[::-1])
half_tooth = math.pi / (2 * teeth)  # half tooth angle at the pitch circle
steps = 8

profile = []
pitch_angle = 2 * math.pi / teeth
for i in range(teeth):
    rot = i * pitch_angle
    # Right flank rotated so the tooth is centered on angle `rot`
    offset = rot - inv_pitch - half_tooth
    right = []
    for k in range(steps + 1):
        t = t_max * k / steps
        x, y = involute(t)
        a = offset + 0.0
        right.append((x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)))
    # Left flank is the mirror image about the tooth center line
    center = rot - 0.0
    left = []
    for x, y in reversed(right):
        # reflect across the line at angle `center`
        c2, s2 = math.cos(2 * center), math.sin(2 * center)
        left.append((x * c2 + y * s2, x * s2 - y * c2))
    root_start = right[0]
    ra = math.atan2(root_start[1], root_start[0])
    la = math.atan2(left[-1][1], left[-1][0])
    flank = [(root_r * math.cos(ra), root_r * math.sin(ra))] if root_r < base_r else []
    profile.extend(flank + right + left)
    if root_r < base_r:
        profile.append((root_r * math.cos(la), root_r * math.sin(la)))

gear = cq.Workplane("XY").polyline(profile).close().extrude(thickness)
if bore > 0:
    gear = gear.cut(cq.Workplane("XY").circle(tolerances.clearance_hole(bore, "tight") / 2).extrude(thickness))
result = gear
