"""Nominal dimensions of purchased parts: the single source of truth.

Print allowances are added by the parts (from common.py tolerances), never stored here.
"""

import math

# Fasteners
M3_CLEARANCE = 3.4  # clearance hole for an M3 screw
M3_SELF_TAP_PILOT = 2.5  # pilot hole for an M3 self-tapping screw into PLA
M4_BUTTON_HEAD_HEIGHT = 2.2  # ISO 7380 M4 button head
M3_NUT_FLATS = 5.5  # ISO 4032 M3 nut, across flats
M3_NUT_THICKNESS = 2.4  # ISO 4032 M3 nut
M4_CLEARANCE = 4.5  # clearance hole for an M4 screw
M4_SELF_TAP_PILOT = 3.3  # pilot hole for an M4 self-tapping screw into PLA
M2_5_SELF_TAP_PILOT = 2.0  # pilot hole for an M2.5 self-tapping screw into PLA
M5_CLEARANCE = 5.5  # clearance hole for an M5 screw
M5_CSK_HEAD = 11.2  # ISO 10642 M5 flat head: theoretical (sharp-edge) cone diameter, 90 degrees

# Lazy susan bearing, Amazon B0DDBBZZTB (https://www.amazon.com/dp/B0DDBBZZTB): two square plates turned 45 degrees apart
BEARING_SPACING = 82.0  # neighbouring hole centres (81 by caliper; printed fit check showed +1 mm)
BEARING_RADIUS = BEARING_SPACING / math.sqrt(2)
BEARING_HOLE = M4_CLEARANCE  # the plates' holes are 4 mm, for M4 screws
BEARING_PLATE = 95.0  # plate square (listing: 9.5 cm)
BEARING_THICKNESS = 8.5  # both plates together, outside (user measurement, +-0.5 all round; listing says 0.8 cm)
BEARING_PLATE_GAP = 6.0  # inside gap between the plates at the corner screw holes (user measured 6-7; minimum)
BEARING_BORE = 54.0  # central opening (user measurement)

# Motor: 23HS5628, NEMA 23, Amazon B0H8D4RZWZ (https://www.amazon.com/dp/B0H8D4RZWZ) (datasheet; shaft and flat measured)
NEMA23_FLANGE = 56.4  # square face
NEMA23_FLANGE_THICKNESS = 5.0  # user measurement
NEMA23_HOLE_SPACING = 47.14  # mounting holes on this square, 4 x 5 mm
NEMA23_PILOT = 38.1  # pilot boss diameter on the face
MOTOR_BODY_LENGTH = 56.0  # face to back end
SHAFT_DIAMETER = 6.35  # 1/4" (user measured 6.3)
SHAFT_FLAT_ACROSS = 5.8  # D-shaft, across the flat (user measurement)
SHAFT_LENGTH = 28.0  # shaft beyond the mounting flange (user measurement; datasheet says 20.6)

# Bucket: Home Depot Homer 5 gallon, 05GLHD2 (https://www.homedepot.com/p/100087613)
BUCKET_FLOOR_DIAMETER = 255.0  # inside at the floor (typical Homer; not measured, the printed stand fits)
BUCKET_TURNTABLE_DIAMETER = 262.0  # inside, ~95 mm above the floor where the turntable sits (user measurement)
BUCKET_TAPER = 0.045  # radius gained per mm of height (estimate: ~9 mm of diameter per 100 mm; not measured, the printed chute fits)
BUCKET_WALL = 2.3  # wall thickness (estimate for a Homer bucket; not measured, the printed chute fits)

# Drain pipe from the chute: Amerimax FLEX-Drain 4 in (Home Depot 202745394, https://www.homedepot.com/p/202745394), corrugated, flexible
DRAIN_PIPE_ID = 89.0  # inside, across the corrugation crests (user felt ~3.5 in; nominal 4 in; the printed spigot fits)

# IR break-beam pair, Amazon B0G38TCZS6 (https://www.amazon.com/dp/B0G38TCZS6, listing drawing); emitter and receiver are the same shape
BEAM_BODY_LENGTH = 20.0
BEAM_BODY_WIDTH = 10.0
BEAM_BODY_HEIGHT = 8.0  # listing text; not on the drawing
BEAM_LED = 3.0  # LED lens on the body's 20 x 10 top face, centred across the width
BEAM_LED_BOSS = 5.0  # round collar at the lens base (estimate from the photo; within the 6.8 mm LED hole)
BEAM_LED_HEIGHT = 5.0  # lens tip above the top face, collar included (estimate; the printed ramp fits)
BEAM_HOLE = 3.0  # mounting hole through the body, top to bottom
BEAM_LED_TO_HOLE = 9.0  # LED centre to mounting-hole centre, along the body (estimate; the printed ramp fits)

# Arduino Uno R3 (Arduino reference drawing). Board frame: origin at the corner by the barrel
# jack, x along the long edge away from the USB/jack edge (x = 0), y across, z up from the board's underside
UNO_LENGTH = 68.58
UNO_WIDTH = 53.34
UNO_THICKNESS = 1.6
UNO_HOLES = ((13.97, 2.54), (15.24, 50.8), (66.04, 7.62), (66.04, 35.56))  # 3.2 mm, for M3
UNO_UNDERSIDE = 3.0  # through-hole pins below the board
UNO_USB_Y = (31.75, 43.81)  # USB-B socket, across the board; sits on the board's top face
UNO_USB_HEIGHT = 11.0
UNO_USB_OVERHANG = 6.2  # past the x = 0 edge
UNO_JACK_Y = (3.3, 12.2)  # 2.1 mm barrel jack
UNO_JACK_HEIGHT = 11.0
UNO_JACK_OVERHANG = 1.8

# RJ45 to 8-pin screw terminal adapter, Amazon B0DK8ZW218 (Teansic, https://www.amazon.com/dp/B0DK8ZW218). T-shaped, no mounting holes:
# a narrow nose with the RJ45 socket on a wide body, the removable green terminal block behind it
RJ45_BODY_WIDTH = 34.45  # listing drawing
RJ45_NOSE_WIDTH = 20.5  # user measurement (listing drawing says 19.5)
RJ45_TERMINAL_WIDTH = 31.29  # listing drawing
RJ45_HEIGHT = 18.0  # body and nose, bottoms flush (user measurement)
RJ45_NOSE_LENGTH = 12.0  # socket face to the body's shoulders (user measurement)
RJ45_BODY_LENGTH = 10.5  # shoulders to the back face the terminal block plugs into (user measurement)
RJ45_TERMINAL_LENGTH = 14.0  # terminal block past the body, wire entries included (user measurement; overall 36.5)

# TB6600 stepper driver (black "Microstep Driver 9-42VDC" box, in the motor's Amazon B0H8D4RZWZ bundle), lying flat, label face up: the
# slotted base plate is one 95.8 x 28 side face, the green terminals stick out of the opposite one
TB6600_LENGTH = 95.8  # user measurement
TB6600_WIDTH = 57.0  # base plate to the terminal face (user measurement)
TB6600_HEIGHT = 28.0  # across the base plate (user measurement)
TB6600_TERMINALS = 11.0  # terminal blocks past the terminal face (user: 68 mm overall)
TB6600_SLOT_WIDTH = 4.4  # U-slot in each end of the base plate, opening outward along the length (user measurement)
TB6600_SLOT_HEIGHT = 16.0  # slot centre from the face opposite the label face (user: roughly)
TB6600_SLOT_INSET = 3.0  # slot's round end centre from the plate's end (estimate from the photo; the printed driver_case fits)

# C14 panel inlet, Amazon B07PVP7XB7 (uxcell, https://www.amazon.com/dp/B07PVP7XB7), screw mount, flange outside the panel
C14_FLANGE_WIDTH = 50.0  # listing drawing
C14_FLANGE_HEIGHT = 22.0  # listing drawing
C14_HOLE_SPACING = 40.0  # listing drawing; 3.5 mm countersunk holes, for M3
C14_BODY_WIDTH = 27.0  # behind the flange (estimate: scaled from the listing drawing; the printed driver_case fits)
C14_BODY_HEIGHT = 19.5  # behind the flange (estimate: usual C14 panel cut-out; the printed driver_case fits)
C14_DEPTH = 27.0  # flange to the tips of the tabs (listing drawing)
