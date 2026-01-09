import itertools
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from returns.result import Result, Success, Failure

from gst_pipeline import BasePipeline, VideoPipelineDecodebin, VideoPipelineTestSrc
from slot_state import SlotState
from theatris_rpo.gst_pipeline import VideoPipelinePlaybin3
from theatris_rpo.slot_flag import SlotFlag

if TYPE_CHECKING:
    from video_output import BaseOutput


logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s.%(msecs)03d][%(name)s] [%(levelname)8s] - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class VideoSlot:
    def __init__(
        self,
        output: "BaseOutput",
        file_path: Path | None = None,
        cfg_auto_fade_time: float = 0.0,
    ):
        self._output = output
        self._id = output.next_slot_id
        self._state = SlotState.UNINITIALIZED

        if file_path:
            if not self.set_file_path(file_path):
                return

        self._use_test_source = not file_path
        self._file_path = file_path

        self.blanked = True

        self._pipeline: BasePipeline | None = None
        self._alpha = 1.0
        self._plane = None
        if output.res:
            self._plane = output.res.reserve_overlay_plane(output.crtc)
            # Make "fading" work by setting the correct blend mode
            self._plane.set_props(
                {"pixel blend mode": 1}
            )  # mode: 0=Premultiplied, 1=Coverage, 2=Pixel

        self._reset_pipeline(use_test_source=self._use_test_source)

        self._cfg = {
            SlotFlag.FULL_ALPHA_AT_START: True,
            SlotFlag.FADE_IN_TIME_SECONDS: cfg_auto_fade_time,
            SlotFlag.FADE_OUT_TIME_SECONDS: cfg_auto_fade_time,
            SlotFlag.LOOPING: False,
        }

        if self.is_auto_faded:
            self._alpha = 0.0

    @property
    def id(self) -> int:
        return self._id

    @property
    def output(self):
        return self._output

    @property
    def plane(self):
        return self._plane

    @property
    def state(self) -> SlotState:
        return self._state

    @property
    def is_uninitialized(self) -> bool:
        return self._state == SlotState.UNINITIALIZED

    @property
    def is_active(self) -> bool:
        return self._state in (
            SlotState.ACTIVATING,
            SlotState.ACTIVE,
            SlotState.DEACTIVATING,
            SlotState.PAUSED,
        )

    @property
    def is_inactive(self) -> bool:
        return self._state in (SlotState.DEACTIVATED, SlotState.UNINITIALIZED)

    @property
    def is_paused(self) -> bool:
        return self._state in (SlotState.PAUSED,)

    @property
    def is_auto_faded(self) -> bool:
        return self._cfg[SlotFlag.FADE_IN_TIME_SECONDS] > 0.0

    @property
    def current_file_path(self) -> Path:
        return self._file_path

    def _reset_pipeline(self, use_test_source: bool = False):
        if self._pipeline is not None and not self.is_inactive:
            self._pipeline.stop_immediately()
        self._pipeline = None
        del self._pipeline
        if use_test_source:
            self._pipeline = None  # VideoPipelineTestSrc(self)
        else:
            self._pipeline = VideoPipelinePlaybin3(self)
            self._pipeline.set_source_file(self._file_path)

    def on_pipeline_eos_enter(self) -> bool:
        if not self._cfg[SlotFlag.LOOPING]:
            self.blank()
        else:
            self._pipeline.rewind()
            return False
        return True

    def on_pipeline_eos_done(self):
        if self._cfg[SlotFlag.LOOPING]:
            logger.debug("%s Starting playback again due to active looping" % self)
            self._pipeline.roll()
            # self.unblank()
            return
        self._state = SlotState.DEACTIVATED

    def on_pipeline_error(self):
        self._state = SlotState.DEACTIVATED

    def set_file_path(self, file_path: Path) -> Result[None, str]:
        if not file_path.is_absolute():
            msg = f"File {file_path} is not absolute. Cannot create slot {self.id} on output {self.output.connector_name}"
            logger.error(msg)
            return Failure(msg)

        if not file_path.exists():
            msg = f"File {file_path} does not exists. Cannot create slot {self.id} on output {self.output.connector_name}"
            logger.error(msg)
            return Failure(msg)

        logger.debug(
            f"Set {file_path} to be played out on slot {self.id} on output {self.output.connector_name}"
        )
        self._file_path = file_path
        self._use_test_source = False
        self._reset_pipeline()

        self._state = SlotState.DEACTIVATED

        return Success(None)

    def play(self) -> Result[None, str]:
        if self.is_uninitialized:
            return Failure("Slot uninitialized. Ignoring play command.")
        self.set_z_pos(2)

        if not self.is_auto_faded and self._cfg[SlotFlag.FULL_ALPHA_AT_START]:
            self._alpha = 1.0

        self._state = SlotState.ACTIVATING
        self._pipeline.roll()
        self.unblank()
        return Success(None)

    def play_test(self) -> Result[None, str]:
        self.set_z_pos(2)

        if not self.is_auto_faded:
            self._alpha = 1.0

        self._reset_pipeline(use_test_source=True)

        self._state = SlotState.ACTIVATING
        self._pipeline.roll()
        self.unblank()
        return Success(None)

    def pause(self) -> Result[None, str]:
        """Stop playback, but don't blank or rewind."""
        if self.is_uninitialized:
            return Failure("Slot uninitialized. Ignoring play command.")
        self._pipeline.pause()
        self._state = SlotState.PAUSED
        return Success(None)

    def stop(self) -> Result[None, str]:
        """Stop playback, blank and rewind the stream."""
        if self.is_uninitialized:
            return Failure("Slot uninitialized. Ignoring stop command.")

        if self._state not in (
            SlotState.ACTIVE,
            SlotState.ACTIVATING,
            SlotState.PAUSED,
        ):
            return Failure("Slot not active. Ignoring stop command.")

        self._state = SlotState.DEACTIVATING

        return Success(None)

    def set_alpha(self, alpha: float):
        if self.is_uninitialized:
            return
        if self._plane is None:
            return

        logger.debug(f"{self}: Setting alpha to {alpha}")

        self._alpha = min(1.0, max(0.0, alpha))
        if self.blanked:
            # Only store desired alpha if blanked, but do not actually set the alpha on the plane
            return
        value = int(self._alpha * 65232.0)
        self._plane.set_props({"alpha": value})

    def set_config(self, slot_flag: SlotFlag, *args) -> Result[None, str]:
        logger.debug(f"{self}: Setting flag {slot_flag.name} to {args}")

        if slot_flag not in self._cfg:
            return Failure(
                f"Config flag {slot_flag.name} not available on slot {self.id} on output {self.output.id}."
            )

        if len(args) == 0:
            return Failure(
                f"Mo arguments given for config flag {slot_flag.name} on slot {self.id} on output {self.output.id}."
            )

        if len(args) == 1:
            self._cfg[slot_flag] = args[0]
            return Success(None)

        self._cfg[slot_flag] = args
        return Success(None)

    def blank(self):
        if self.is_uninitialized:
            return
        if self._plane is None:
            return
        self._plane.set_props({"alpha": 0})
        self.blanked = True

    def unblank(self):
        if self.is_uninitialized:
            return
        if self._plane is None:
            return
        logger.debug(f"{self}: Unblank")
        self.blanked = False
        self.set_alpha(self._alpha)

    def set_z_pos(self, zPos):
        if self.is_uninitialized:
            return
        if self._plane is None:
            return
        self._plane.set_props({"zpos": zPos})

    def update(self, dt):
        if self.is_uninitialized:
            return
        old_state = self._state

        match self._state:
            case SlotState.DEACTIVATED:
                self.blank()

            case SlotState.DEACTIVATING:
                # TODO: Calculate slope by actual config value self.set_config(SlotFlag.FADE_OUT_TIME_SECONDS)
                alpha = self._alpha - (dt * 4.0)
                if self.is_auto_faded and alpha > 0.0:
                    self.set_alpha(alpha)
                    logger.debug("alpha DN: %s", self._alpha)
                else:
                    self.blank()
                    if self._pipeline is not None:
                        self._pipeline.stop()
                    self._state = SlotState.DEACTIVATED

            case SlotState.ACTIVATING:
                if self.is_auto_faded:
                    # TODO: Calculate slope by actual config value self.set_config(SlotFlag.FADE_IN_TIME_SECONDS)
                    alpha = self._alpha + (dt * 4.0)
                    if alpha < 1.0:
                        self.set_alpha(alpha)
                    else:
                        self.set_alpha(1.0)
                        self._state = SlotState.ACTIVE
                    logger.debug("alpha UP: %s", self._alpha)
                else:
                    self._state = SlotState.ACTIVE

            case SlotState.ACTIVE:
                pass

        if self._state != old_state:
            logger.debug(self)

    def __repr__(self):
        return (
            f"VideoSlot {self._output.connector_name}/{self._id} ({self._state.name})"
        )
