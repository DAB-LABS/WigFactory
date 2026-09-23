"""Constants for the Daikin FTXS50KVM infrared integration."""

from __future__ import annotations

DOMAIN = "daikin_ftxs50kvm_ir"

CONF_INFRARED_ENTITY_ID = "infrared_entity_id"
CONF_SEND_COUNT = "send_count"

# How many times each change transmits, and the pause between transmissions.
#
# One by default, because that is what the wig states: every cell carries the
# default send count of one. An air conditioner code is not a button press. It
# carries the whole state, so sending it twice sets the same state twice and
# costs nothing but airtime. That makes a higher count a safe thing to reach
# for when a room eats the odd transmission, which is why it is an option.
DEFAULT_SEND_COUNT = 1
MIN_SEND_COUNT = 1
MAX_SEND_COUNT = 10
# A Daikin code is about 0.32 s on the air, both frames and the terminator.
# Half a second between sends keeps two of them from running into each other
# on an emitter that returns before it has finished transmitting.
SEND_REPEAT_GAP = 0.5

MANUFACTURER = "Daikin"
MODEL = "FTXS50KVM"
DEVICE_NAME = "Daikin FTXS50KVM"
