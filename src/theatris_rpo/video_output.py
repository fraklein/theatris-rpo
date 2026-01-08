import itertools
from pathlib import Path
from typing import Any, List

from returns.pointfree import bind
from returns.result import Result, Failure, Success
from returns.pipeline import flow

from log import logger
from slot_state import SlotState
from theatris_rpo.slot_flag import SlotFlag
from video_slot import VideoSlot


class BaseOutput:
    id_iterator = itertools.count()

    def __init__(
        self,
        py_kms_resource_manager: Any | None,
        file_descriptor: Any | None,
        connector_name: str,
    ):
        self._id = next(self.id_iterator)

        self._connector_name = connector_name
        self._res = py_kms_resource_manager
        self._conn = None
        self._crtc = None
        self._fd = None

        if self._res:
            self._conn = self._res.reserve_connector(connector_name)
            self._crtc = self._res.reserve_crtc(self._conn)

        if file_descriptor:
            self._fd = file_descriptor

        self._video_slots: List[VideoSlot] = []

        self._slot_id_iterator = itertools.count()

    @property
    def id(self) -> int:
        return self._id

    @property
    def conn(self):
        return self._conn

    @property
    def crtc(self):
        return self._crtc

    @property
    def fd(self):
        return self._fd

    @property
    def res(self):
        return self._res

    @property
    def video_slots(self) -> List["VideoSlot"]:
        return self._video_slots

    @property
    def connector_name(self):
        return self._connector_name

    @property
    def next_slot_id(self) -> int:
        return next(self._slot_id_iterator)

    def add_video_slot(self, file_path: Path | None):
        self._video_slots.append(VideoSlot(self, file_path, cfg_auto_fade_time=0.0))

    def play_video(
        self,
        slot_number: int,
        file_path: Path | None = None,
        restart_if_already_playing: bool = False,
    ) -> Result[None, str]:
        match self._get_slot(slot_number):  # type: ignore
            case Success(slot):
                if file_path is not None:
                    if (
                        file_path == slot.current_file_path
                        and not restart_if_already_playing
                        and slot.is_active
                        and not slot.is_paused
                    ):
                        msg = f"File is already playing on slot {slot_number} on output {self.id}. Set 'restart_if_already_playing' to trigger playback again."
                        logger.warning(msg)
                        return Failure(msg)

                    if not slot.is_paused:
                        match slot.set_file_path(file_path):
                            case Success(_):
                                return slot.play()
                            case Failure(msg):
                                return Failure(msg)
                    # Continue playing of paused slot
                    return slot.play()
                else:  # play already initialized slot
                    return slot.play()
            case Failure(msg):
                return Failure(msg)
        return None

    def play_test(self, slot_number: int) -> Result[None, str]:
        return flow(
            self._get_slot(slot_number),
            bind(lambda slot: slot.play_test()),
        )

    def stop_all_video(self) -> Result[None, str]:
        for video_slot in self._video_slots:
            if video_slot.state in (
                SlotState.ACTIVE,
                SlotState.ACTIVATING,
                SlotState.PAUSED,
            ):
                match video_slot.stop():
                    case Failure(msg):
                        return Failure(msg)
        return Success(None)

    def stop_video(self, slot_number: int) -> Result[None, str]:
        return flow(
            self._get_slot(slot_number),
            bind(lambda slot: slot.stop()),
        )

    def set_alpha(self, slot_number: int, factor: float) -> Result[None, str]:
        return flow(
            self._get_slot(slot_number),
            bind(lambda slot: slot.set_alpha(factor)),
        )

    def pause(self, slot_number: int) -> Result[None, str]:
        return flow(
            self._get_slot(slot_number),
            bind(lambda slot: slot.pause()),
        )

    def set_slot_config(
        self, slot_number: int, slot_flag: SlotFlag, *args
    ) -> Result[None, str]:
        return flow(
            self._get_slot(slot_number),
            bind(lambda slot: slot.set_config(slot_flag, *args)),
        )

    def update(self, dt):
        for slot in self._video_slots:
            slot.update(dt)

    def _get_slot(self, slot_number: int) -> Result[VideoSlot, str]:
        try:
            slot = self._video_slots[slot_number]
            return Success(slot)
        except (IndexError, TypeError):
            msg = f"No video slot found for slot number {slot_number}"
            logger.error(msg)
            return Failure(msg)


class TestOutput(BaseOutput):
    def __init__(self, connector_name):
        super().__init__(None, None, connector_name)

        logger.debug("Initialized test output %s", connector_name)

    def __repr__(self):
        return f"{type(self).__name__}({self.id}) '{self._connector_name}'"


class HDMIOutput(BaseOutput):
    def __init__(self, py_kms_resource_manager, file_descriptor, connector_name):
        super().__init__(py_kms_resource_manager, file_descriptor, connector_name)

        logger.debug(
            "Initialized output %s with connector ID %s", connector_name, self._conn.id
        )

    def __repr__(self):
        return f"{type(self).__name__}(#{self.id}) '{self._connector_name}' ({self._conn.id})"
