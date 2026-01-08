import enum


class SlotFlag(enum.Enum):
    FULL_ALPHA_AT_START = enum.auto()
    FADE_IN_TIME_SECONDS = enum.auto()
    FADE_OUT_TIME_SECONDS = enum.auto()
    LOOPING = enum.auto()
    PUSH_OTHER_SLOTS_AT_START = enum.auto()
