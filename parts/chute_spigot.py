"""Chute spigot: funnel from the ramp's channel into the drain pipe, in line with the ramp.

The ramp's lower end slides into the socket until its floor and rails stop on the 45
degree shoulder, and is held by 4 x M4 x 10 self-tapping screws through the socket walls
into the rails. Inside, the floor steps down 0.5 mm and the walls step out 0.5 mm past
the channel's end, so candy never meets an edge. The channel funnels into a round bore
whose bottom carries on the floor line. It ends in a tapered spigot that the corrugated
drain pipe (hardware DRAIN_PIPE_ID) pushes over; a zip tie round the pipe, over the
groove, holds it.

assembled() is in chute_ramp's reference mount; chute_frame.RAMP_MOUNT places it in the
assembly frame. Print (build()) socket mouth down, spigot
up; no supports. Everything narrows going up: the shoulder, the funnel and the spigot's
taper. The socket's top is closed by the hood so nothing starts in mid-air.
"""

from build123d import (
    Align,
    BuildPart,
    BuildSketch,
    Cone,
    Cylinder,
    Location,
    Locations,
    Part,
    RectangleRounded,
    Rot,
    extrude,
    loft,
)
from chute_ramp import (
    CHANNEL,
    CHANNEL_LENGTH,
    FLOOR,
    JOINT_OVERLAP,
    JOINT_SCREWS,
    RAIL_HEIGHT,
    RAIL_OUT,
    SLOPE,
    STEP,
    across,
    across_plane,
    at,
)
from common import CLEARANCE, WALL, export
from hardware import DRAIN_PIPE_ID, M4_CLEARANCE

SOCKET_WALL = 4.0  # round the channel's end; the joint screws' heads bear on it
FUNNEL_LENGTH = 30.0  # channel to round bore; shorter puts the inside corners past 45 degrees in print
SPIGOT_LENGTH = 40.0
SPIGOT_TIP = DRAIN_PIPE_ID - 3.0  # outside diameter at the tip: starts easily into the pipe
SPIGOT_BASE = DRAIN_PIPE_ID + 5.0  # the flexible pipe stretches over the taper
BORE = SPIGOT_TIP - 2 * WALL
GROOVE_AT = 25.0  # zip-tie groove centre, from the spigot tip
GROOVE_WIDTH = 6.0
GROOVE_DEPTH = 1.2

SOCKET_IN = RAIL_OUT + CLEARANCE  # half width
SOCKET_FLOOR = -FLOOR - CLEARANCE  # h of the socket's inside bottom, under the channel floor
SOCKET_TOP = RAIL_HEIGHT + CLEARANCE  # over the rails; the hood's inside carries on above
SOCKET_OUT = SOCKET_IN + SOCKET_WALL
SOCKET_BOTTOM = SOCKET_FLOOR - SOCKET_WALL
SHOULDER = SOCKET_IN - (CHANNEL + STEP)  # 45 degree step in, from the socket to the funnel
FUNNEL_START = CHANNEL_LENGTH + SHOULDER
SPIGOT_START = FUNNEL_START + FUNNEL_LENGTH
LENGTH = SPIGOT_START + SPIGOT_LENGTH  # s of the tip
AXIS_H = BORE / 2 - STEP  # the bore's bottom carries on the stepped-down floor
HOOD_TOP = -STEP + BORE + WALL


def section(w: float, h0: float, h1: float):
    """Rectangle x +-w/2, from h0 to h1 above the floor line, on the current sketch plane."""
    with Locations((0, (h0 + h1) / 2)):
        RectangleRounded(w, h1 - h0, 0.5)


def socket() -> Part:
    """Solid block from the socket mouth to the funnel; cavity() hollows it."""
    with BuildPart() as p:
        with BuildSketch(across_plane(CHANNEL_LENGTH - JOINT_OVERLAP)):
            section(2 * SOCKET_OUT, SOCKET_BOTTOM, HOOD_TOP)
        extrude(amount=JOINT_OVERLAP + SHOULDER)
    return p.part


def cavity() -> Part:
    """Room for the channel's end, the shoulder it stops on, and the space under the hood."""
    mouth = across_plane(CHANNEL_LENGTH - JOINT_OVERLAP).offset(-0.01)
    with BuildPart() as p:
        with BuildSketch(mouth):
            section(2 * SOCKET_IN, SOCKET_FLOOR, SOCKET_TOP)
        extrude(amount=JOINT_OVERLAP + 0.01)
        with BuildSketch(mouth):
            section(2 * (CHANNEL + STEP), -STEP, -STEP + BORE)
        extrude(amount=JOINT_OVERLAP + SHOULDER + 0.02)
        with BuildPart():  # the shoulder, added to the cavity on exit
            with BuildSketch(across_plane(CHANNEL_LENGTH)):
                section(2 * SOCKET_IN, SOCKET_FLOOR, SOCKET_TOP)
            with BuildSketch(across_plane(FUNNEL_START + 0.01)):
                section(2 * (CHANNEL + STEP), -STEP, SOCKET_TOP)
            loft(ruled=True)
    return p.part


def funnel(inner: bool) -> Part:
    """Socket-sized box at FUNNEL_START lofted into the spigot's base circle."""
    start, end = across_plane(FUNNEL_START), across_plane(SPIGOT_START)
    if inner:  # a hair longer each way, so the cuts are clean
        start, end = start.offset(-0.01), end.offset(0.01)
    with BuildPart() as p:
        with BuildSketch(start):
            if inner:
                section(2 * (CHANNEL + STEP), -STEP, -STEP + BORE)
            else:
                section(2 * SOCKET_OUT, SOCKET_BOTTOM, HOOD_TOP)
        with BuildSketch(end), Locations((0, AXIS_H)):
            d = BORE if inner else SPIGOT_BASE
            RectangleRounded(d, d, d / 2 - 0.01)
        loft(ruled=True)
    return p.part


def spigot() -> Part:
    """Tapered tube from the funnel to the tip, with a zip-tie groove; bore() hollows it."""
    taper = (SPIGOT_BASE - SPIGOT_TIP) / 2 / SPIGOT_LENGTH  # radius lost per mm towards the tip

    def radius(t: float) -> float:
        return SPIGOT_BASE / 2 - taper * t

    g0 = SPIGOT_LENGTH - GROOVE_AT - GROOVE_WIDTH / 2  # groove, from the base
    g1 = g0 + GROOVE_WIDTH
    d = GROOVE_DEPTH  # 45 degree groove flanks print unsupported
    rings = [  # (start, end, r_start, r_end) along the spigot from its base
        (0, g0, radius(0), radius(g0)),
        (g0, g0 + d, radius(g0), radius(g0) - d),
        (g0 + d, g1 - d, radius(g0) - d, radius(g1) - d),
        (g1 - d, g1, radius(g1) - d, radius(g1)),
        (g1, SPIGOT_LENGTH, radius(g1), radius(SPIGOT_LENGTH)),
    ]
    with BuildPart(across_plane(SPIGOT_START, AXIS_H)) as p:
        for t0, t1, r0, r1 in rings:
            with Locations((0, 0, t0)):
                Cone(r0, r1, t1 - t0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return p.part


def bore() -> Part:
    with BuildPart(across_plane(SPIGOT_START, AXIS_H).offset(-0.01)) as p:
        Cylinder(BORE / 2, SPIGOT_LENGTH + 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return p.part


def assembled() -> Part:
    part = socket() + funnel(inner=False) + spigot()
    part -= cavity() + funnel(inner=True) + bore()
    for s, h in JOINT_SCREWS:  # clearance through the socket walls; the rails take the thread
        y, z = at(s, h)
        for sx in (-1, 1):
            part -= across(y, z, M4_CLEARANCE, sx * (SOCKET_IN - 1), sx * (SOCKET_OUT + 1))
    return part


TO_PRINT = Rot(X=-90 - SLOPE)  # downhill turns to +Z: the socket mouth goes on the bed


def build() -> Part:
    part = TO_PRINT * assembled()
    return part.moved(Location((0, 0, -part.bounding_box().min.Z)))


if __name__ == "__main__":
    export(build(), "chute_spigot")
