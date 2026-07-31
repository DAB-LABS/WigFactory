"""Constants for the Sanmli TH-05 candle integration."""

from __future__ import annotations

DOMAIN = "sanmli_th05_ir"

CONF_INFRARED_ENTITY_ID = "infrared_entity_id"
CONF_INFRARED_RECEIVER_ENTITY_ID = "infrared_receiver_entity_id"
CONF_SEND_COUNT = "send_count"

# How many times one press transmits, and the pause between frames.
#
# Three by default, which is what the candles on the bench wanted. A press on
# the physical remote is not one frame: RC-5 re-sends every 114ms for as long
# as the key is held, so a real press is three or four frames. These candles
# appear to sample their receiver on a duty cycle to save battery, so a lone
# frame can land in a gap and be missed. That showed up on the bench as a
# button working on the first press sometimes and the third press other times.
#
# Repeating in the integration rather than through the command's repeat_count
# is deliberate: core does not read repeat_count on the Broadlink emitter path
# (pulses_to_data never sets the repeat byte), so a frame count set there would
# silently do nothing on common hardware.
DEFAULT_SEND_COUNT = 4
MIN_SEND_COUNT = 1
MAX_SEND_COUNT = 10
SEND_REPEAT_GAP = 0.1

MANUFACTURER = "Sanmli"
MODEL = "TH-05"
DEVICE_NAME = "Candles"
