import enum


class SlotState(enum.Enum):
    UNINITIALIZED = enum.auto()
    ACTIVATING = enum.auto()
    ACTIVE = enum.auto()
    DEACTIVATING = enum.auto()
    DEACTIVATED = enum.auto()
    PAUSED = enum.auto()
