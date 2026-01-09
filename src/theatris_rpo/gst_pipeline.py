import logging
import pathlib
import platform
import time
from abc import abstractmethod, ABC
from typing import TYPE_CHECKING, Callable

from gi.repository import Gst, GLib

from theatris_rpo.config import config, Conf

if TYPE_CHECKING:
    from theatris_rpo.video_slot import VideoSlot

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s.%(msecs)03d][%(name)s] [%(levelname)8s] - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class BasePipeline(ABC):
    def __init__(self, slot: "VideoSlot"):
        self._slot = slot
        self._pipeline = Gst.Pipeline.new()

        self._gst_state_current = None
        self._gst_state_new = None
        self._gst_state_pending = None

        self._sink = Gst.Bin.new("sink")
        if config[Conf.IS_RASPI_5]:
            self._kmssink = Gst.ElementFactory.make("kmssink", "kmssink")
            self._kmssink.set_property("skip-vsync", "true")
            self._kmssink.set_property("show-preroll-frame", "false")
            # self._kmssink.set_property("can-scale", "true")
            # self._kmssink.set_property("force-modesetting", "false")

            self._sink.add(self._kmssink)

            self._videoscale = Gst.ElementFactory.make("videoscale")
            self._sink.add(self._videoscale)
            self._capsfilter = Gst.ElementFactory.make("capsfilter", "filter")
            self._sink.add(self._capsfilter)

            if not self._videoscale.link(self._capsfilter):
                logger.error("Link Error: videoscale -> caps_filter")

            if not self._capsfilter.link(self._kmssink):
                logger.error("Link Error: caps_filter -> kmssink")

            # self.pad = self._kmssink.get_static_pad("sink")
            self.pad = self._videoscale.get_static_pad("sink")
            self.ghostpad = Gst.GhostPad.new("sink", self.pad)
            self.ghostpad.set_active(True)
            self._sink.add_pad(self.ghostpad)

        else:
            self._autovideosink = Gst.ElementFactory.make(
                "autovideosink", "autovideosink"
            )
            self._sink.add(self._autovideosink)

            self.pad = self._autovideosink.get_static_pad("sink")
            self.ghostpad = Gst.GhostPad.new("sink", self.pad)
            self.ghostpad.set_active(True)
            self._sink.add_pad(self.ghostpad)

        self._build_pipeline()

        # display-width and display-height properties of kmssink are only available in PAUSED or PLAYING.
        # But: Setting PAUSED here leads to issues when the playing should be started later.
        # Turns out: Setting READY here also returns the properties.
        # self._pipeline.set_state(Gst.State.READY)
        # time.sleep(1)

        try:
            display_width = self._kmssink.get_property("display-width")
            display_height = self._kmssink.get_property("display-height")
            logger.debug("display-width %s", display_width)
            logger.debug("display-height %s", display_height)

            display_width = 800
            display_height = 400

            caps = Gst.Caps.from_string(
                f"video/x-raw, width={display_width}, height={display_height}"
            )
            self._capsfilter.set_property("caps", caps)
            # Working test on cli: gst-launch-1.0 -v filesrc location=/home/gordon/test/butterfly.mp4 ! decodebin ! videoscale ! video/x-raw,width=800, height=400 ! kmssink
        except TypeError:
            pass

        if slot.output.fd:
            self._kmssink.set_property("fd", slot.output.fd)
        if slot.output.conn:
            self._kmssink.set_property("connector-id", slot.output.conn.id)
        if slot.plane:
            self._kmssink.set_property("plane-id", slot.plane.id)

        # Create bus and connect several handlers
        self._bus = self._pipeline.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message::state-changed", self._on_state_changed)
        self._bus.connect("message::eos", self._on_eos)
        self._bus.connect("message::error", self._on_error)

    @property
    def slot(self):
        return self._slot

    @abstractmethod
    def set_source_file(self, file_path: pathlib.Path):
        raise NotImplementedError

    def _on_eos(self, bus, msg):
        logger.debug("%s eos", self)

        if self._slot.on_pipeline_eos_enter():
            # Rewind the stream blanked so it can be started from the beginning again directly
            self._transition_to_paused(
                rewind=True, callback=self._slot.on_pipeline_eos_done
            )

    def _on_error(self, bus, msg):
        error = msg.parse_error()
        logger.error(f"{self} error: {error[1]}")
        self._pipeline.set_state(Gst.State.NULL)
        self._slot.on_pipeline_error()

    def _on_state_changed(self, bus, msg):
        if msg.src is not self._pipeline:
            # We're only interested in pipeline state changes
            return

        old_state, new_state, pending_state = msg.parse_state_changed()
        if (
            self._gst_state_current != old_state
            or self._gst_state_new != new_state
            or self._gst_state_pending != pending_state
        ):  # TODO: Now that we're filtering on pipeline state changes, this should be redundant. Or is it?
            pass
            if True:
                logger.debug(
                    "%s state changed from %s to %s (pending %s)",
                    self,
                    old_state.value_nick,
                    new_state.value_nick,
                    pending_state.value_nick,
                )
        self._gst_state_current, self._gst_state_new, self._gst_state_pending = (
            old_state,
            new_state,
            pending_state,
        )

    def _build_pipeline(self):
        pass

    def _transition_to_playing(self):
        """'Wait' (by polling) for the next required state to get the pipeline into playing state"""
        _, state, _ = self._pipeline.get_state(
            2000 * 1000 * 1000
        )  # or: Gst.CLOCK_TIME_NONE to wait (and block!) indefinitely
        match state:
            case Gst.State.READY:
                logger.debug("%s: (to playing) Setting to paused...", self)
                self._pipeline.set_state(Gst.State.PAUSED)
            case Gst.State.PAUSED:
                logger.debug("%s: (to playing) Setting to playing...", self)
                self._pipeline.set_state(Gst.State.PLAYING)
            case Gst.State.PLAYING:
                logger.debug("%s: (to playing) is playing.", self)
                return  # transition is finished
            case _:
                if self.slot.is_inactive:
                    # Prevent endless loop if playing can't be started for some reason
                    return
                logger.debug("%s: (to playing) Setting to ready...", self)
                self._pipeline.set_state(Gst.State.READY)
        GLib.timeout_add(20, self._transition_to_playing)

    def _transition_to_paused(
        self, rewind: bool = False, callback: Callable | None = None
    ):
        """'Wait' (by polling) for the next required state to get the pipeline into paused state.
        Rewind (seek to 0) if flag is set."""
        _, state, _ = self._pipeline.get_state(
            2000 * 1000 * 1000
        )  # or: Gst.CLOCK_TIME_NONE to wait (and block!) indefinitely
        match state:
            case Gst.State.PAUSED:
                logger.debug("%s: (to paused) is paused.", self)
                if rewind:
                    logger.debug("%s: (to paused)  rewinding....", self)
                    self.rewind()
                    # Transition finished, inform interested parties
                    if callback:
                        callback()
                return
            case _:
                if self.slot.is_inactive:
                    return
                logger.debug("%s: (to paused)  Setting to paused...", self)
                self._pipeline.set_state(Gst.State.PAUSED)

        GLib.timeout_add(20, self._transition_to_paused, rewind, callback)

    def roll(self):
        """Set the pipeline to playing via well-defined transitions.
        This *will not* retrigger an already playing pipeline."""
        self._transition_to_playing()

    def pause(self):
        """Stop playback, but don't blank or rewind."""
        self._transition_to_paused(rewind=False)

    def stop(self):
        """Stop playback and rewind the stream."""
        self._transition_to_paused(rewind=True)

    def stop_immediately(self):
        """Stop playback without transition."""
        self._pipeline.set_state(Gst.State.NULL)

    def rewind(self):
        """Seek to time 0, i.e. start of stream"""
        dest_seek = 0
        self._pipeline.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, dest_seek
        )

    def __repr__(self):
        return f"{self.__class__.__name__} (Slot{self._slot})"


class VideoPipelinePlaybin3(BasePipeline):
    def __init__(self, slot: "VideoSlot"):
        self._playbin = Gst.ElementFactory.make("playbin3", "playbin")
        super().__init__(slot)

    def _build_pipeline(self):
        self._pipeline.add(self._playbin)
        self._playbin.set_property("video-sink", self._sink)

    def set_source_file(self, srcFileName: pathlib.Path):
        file_name = "file://" + str(srcFileName)
        self._playbin.set_property("uri", file_name)


class VideoPipelineDecodebin(BasePipeline):
    def __init__(self, slot: "VideoSlot"):
        self._source = Gst.ElementFactory.make("filesrc")
        self._decode = Gst.ElementFactory.make("decodebin")
        super().__init__(slot)

    def _on_decode_pad_added(self, dbin, pad):
        self._decode.link(self._videoscale)

    def _build_pipeline(self):
        self._pipeline.add(self._source)
        self._pipeline.add(self._decode)
        self._pipeline.add(self._videoscale)
        self._pipeline.add(self._capsfilter)
        self._pipeline.add(self._sink)

        if not self._source.link(self._decode):
            logger.error("Link Error: source -> decode")

        # Delay decode -> scaler link until decodebin has created its bin
        self._decode.connect("pad-added", self._on_decode_pad_added)

        if not self._videoscale.link(self._capsfilter):
            logger.error("Link Error: videoscale -> caps_filter")

        if not self._capsfilter.link(self._sink):
            logger.error("Link Error: caps_filter -> sink")

    def set_source_file(self, srcFileName: pathlib.Path):
        self._source.set_property("location", str(srcFileName))


class VideoPipelineTestSrc(BasePipeline):
    def __init__(self, slot: "VideoSlot"):
        logger.debug("Using videotestsrc")
        self._source = Gst.ElementFactory.make("videotestsrc")
        self._source.set_property("pattern", 0)
        super().__init__(slot)

    def _build_pipeline(self):
        try:
            self._sink.set_property("force-modesetting", "true")
        except TypeError:
            logger.error(
                "gstreamer error when setting property force-modesetting on sink"
            )
            pass

        self._pipeline.add(self._source)
        self._pipeline.add(self._sink)

        if not self._source.link(self._sink):
            logger.error("Link Error: source -> sink")

    def set_source_file(self, file_path: pathlib.Path):
        pass
