import enum
import logging
import os
import platform
import sys
from abc import abstractmethod
from typing import Any, Dict, List, Optional

import gi
from attrs import define

gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
gi.require_version("Gst", "1.0")

from gi.repository import GLib, GObject, Gst

logging.basicConfig(level=logging.DEBUG, format="[%(name)s] [%(levelname)8s] - %(message)s")
logger = logging.getLogger(__name__)


class BaseOutput:
    def __init__(self, py_kms_resource_manager: Optional[Any], file_descriptor: Optional[Any], connector_name):
        self._connector_name = connector_name
        self._res = py_kms_resource_manager
        if self._res:
            self._conn = self._res.reserve_connector(connector_name)
            self._crtc = self._res.reserve_crtc(self._conn)
        else:
            self._conn = None
            self._crtc = None
        if file_descriptor:
            self._fd = file_descriptor
        else:
            self._fd = None

        self._plane = None
        self._video_slots: List[VideoSlot] = []

    @property
    def video_slots(self) -> List["VideoSlot"]:
        return self._video_slots

    @abstractmethod
    def addVideoSlot(self):
        pass

    def onSlotActivated(self, slot: "VideoSlot"):
        slots_to_deactivate = [VideoSlot]
        found = False
        for p in self._video_slots:
            if p == slot:
                p.state = SlotState.ACTIVATING
                found = True
            else:
                slots_to_deactivate.append(p)

        if not found:
            slots_to_deactivate.clear()
            for p in self._video_slots:
                if p == slot:
                    p.state = SlotState.ACTIVATING
                    found = True
                else:
                    slots_to_deactivate.append(p)

        if found:
            for p in slots_to_deactivate:
                p.state = SlotState.DEACTIVATING

    def play_video(self, file_name: str):
        for video_slot in self._video_slots:
            if video_slot._state == SlotState.DEACTIVATED:
                video_slot.play(file_name)
                break

    def update(self, dt):
        for slot in self._video_slots:
            slot.update(dt)


class TestOutput(BaseOutput):
    def __init__(self, connector_name):
        super().__init__(None, None, connector_name)

        logger.debug("Initialized test output %s", connector_name)

    def addVideoSlot(self):
        video_slot = VideoSlot(self, useHwDecoder=True)
        self._video_slots.append(video_slot)

    def __repr__(self):
        return f"HDMIOutput {self._connector_name} ({self._conn.id})"


class HDMIOutput(BaseOutput):
    def __init__(self, py_kms_resource_manager, file_descriptor, connector_name):
        super().__init__(py_kms_resource_manager, file_descriptor, connector_name)

        logger.debug("Initialized output %s with connector ID %s", connector_name, self._conn.id)

    def addVideoSlot(self):
        plane = self._res.reserve_overlay_plane(self._crtc)
        self._plane = plane
        video_slot = VideoSlot(self, useHwDecoder=True)
        self._video_slots.append(video_slot)

    def __repr__(self):
        return f"HDMIOutput {self._connector_name} ({self._conn.id})"


class VideoMachine:
    def __init__(self, use_test_environment: Optional[bool] = False):

        self._outputs: Dict[int, BaseOutput] = {}

        self._outputs[1] = TestOutput("Test Output 1")
        self._outputs[2] = TestOutput("Test Output 2")

        if not use_test_environment:
            # Create actual KMS outputs on raspi
            self._card = pykms.Card()
            self._res = pykms.ResourceManager(self._card)
            self._fd = self._card.fd
            logger.debug("File Descriptor: %s", self._fd)

            self._outputs[1] = HDMIOutput(self._res, self._fd, "HDMI-A-1")
            self._outputs[2] = HDMIOutput(self._res, self._fd, "HDMI-A-2")

            self._card.disable_planes()

        # Initialize Gstreamer
        Gst.init(sys.argv[1:])
        logger.debug("Gstreamer Version: %s", Gst.version())

        # Create video slots on outputs
        for _ in range(2):
            self._outputs[1].addVideoSlot()

        self._mainloop = GLib.MainLoop()

    @property
    def outputs(self) -> Dict[int, BaseOutput]:
        return self._outputs

    def start(self):
        self.update()
        self._mainloop.run()

    def play_video(self, output_number: int, file_name: str):
        try:
            output = self.outputs[output_number]
            output.play_video(file_name)

        except KeyError:
            logger.error("No output with number %s present. Active outputs are %s", output_number, self.outputs)

    def update(self):
        dt = 0.016
        for output in self.outputs.values():
            output.update(dt)

        GLib.timeout_add(int(dt * 1000.0), self.update)


class BasePipeline:
    def __init__(self, slot: "VideoSlot"):
        self._slot = slot

        self._plane = slot._output._plane
        self._pipeline = Gst.Pipeline.new()
        self._sink = None

        if not (slot._output._fd and slot._output._conn and slot._output._plane):
            # this is not a system with KMS, use test sink
            self._sink = Gst.ElementFactory.make("autovideosink")
        else:
            self._sink = Gst.ElementFactory.make("kmssink")
            self._sink.set_property("skip-vsync", "true")

            self._sink.set_property("fd", slot._output._fd)
            self._sink.set_property("connector-id", slot._output._conn.id)
            self._sink.set_property("plane-id", slot._output._plane.id)

        # Create bus and connect several handlers
        self._bus = self._pipeline.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message::state-changed", self._onStateChanged)
        self._bus.connect("message::eos", self._onEos)
        self._bus.connect("message::error", self._onError)

    def _onEos(self, bus, msg):
        logger.debug("on_eos")
        self._pipeline.set_state(Gst.State.NULL)

    def _onError(self, bus, msg):
        error = msg.parse_error()
        logger.error(error[1])
        self._pipeline.set_state(Gst.State.NULL)

    def _onStateChanged(self, bus, msg):
        oldState, newState, pendingState = msg.parse_state_changed()
        logger.debug(
            "Pipeline %s state changed from %s to %s (pending %s)",
            self,
            oldState.value_nick,
            newState.value_nick,
            pendingState.value_nick,
        )
        # if newState == Gst.State.NULL:
        #    logger.debug("State is NULL")
        #    #self.pipeline.set_state(Gst.State.READY)

    def _setPlaying(self):
        self._pipeline.set_state(Gst.State.PLAYING)

    def start(self):
        self._pipeline.set_state(Gst.State.READY)
        GLib.timeout_add(100, self._setPlaying)

    def stop(self):
        self._pipeline.set_state(Gst.State.NULL)

    def setSourceFile(self, srcFileName):
        self._source.set_property("location", srcFileName)


class VideoPipelineDecodebin(BasePipeline):
    def __init__(self, slot: "VideoSlot"):
        super().__init__(slot)
        self._source = Gst.ElementFactory.make("filesrc")
        self._decode = Gst.ElementFactory.make("decodebin")
        self._sink = None
        self._kmssink_fd = None
        if not (slot._output._fd and slot._output._conn and slot._output._plane):
            self._sink = Gst.ElementFactory.make("autovideosink")
        else:
            self._sink = Gst.ElementFactory.make("kmssink")
            self._sink.set_property("skip-vsync", "true")

        self._pipeline.add(self._source)
        self._pipeline.add(self._decode)
        self._pipeline.add(self._sink)

        if not self._source.link(self._decode):
            logger.error("Link Error: source -> decode")

        self._decode.connect("pad-added", self._onPadAdded)

    def _onPadAdded(self, dbin, pad):
        self._decode.link(self._sink)


class VideoPipelineH264(BasePipeline):
    def __init__(self, slot: "VideoSlot"):
        super().__init__(slot)
        self._source = Gst.ElementFactory.make("filesrc")
        self._demux = Gst.ElementFactory.make("qtdemux")
        self._parse = Gst.ElementFactory.make("h264parse")
        self._decode = Gst.ElementFactory.make("avdec_h264")
        self._sink = None
        self._kmssink_fd = None

        if not (slot._output._fd and slot._output._conn and slot._output._plane):
            # this is not a system with KMS, use test sink
            self._sink = Gst.ElementFactory.make("autovideosink")
        else:
            self._sink = Gst.ElementFactory.make("kmssink")
            self._sink.set_property("skip-vsync", "true")

        self._pipeline.add(self._source)
        self._pipeline.add(self._demux)
        self._pipeline.add(self._parse)
        self._pipeline.add(self._decode)
        self._pipeline.add(self._sink)

        if not self._source.link(self._demux):
            logger.error("Link Error: source -> demux")

        if not self._decode.link(self._sink):
            logger.error("Link Error: source -> sink")

        self._demux.connect("pad-added", self._onDemuxPadAdded)

    def _onDemuxPadAdded(self, dbin, pad):
        if pad.name == "video_0":
            self._demux.link(self._decode)


class SlotState(enum.Enum):
    PREROLL = enum.auto()
    ACTIVATING = enum.auto()
    ACTIVE = enum.auto()
    DEACTIVATING = enum.auto()
    DEACTIVATED = enum.auto()


class VideoSlot:
    def __init__(self, output: BaseOutput, useHwDecoder: bool):
        self._output = output
        self._pipeline: BasePipeline = None
        self._state = SlotState.DEACTIVATED
        self._alpha = 0.0

        self._useHwDecoder = useHwDecoder
        self.fading = True

    def _resetPipeline(self):
        if self._pipeline != None:
            self._pipeline.stop()
            del self._pipeline
        if self._useHwDecoder:
            self._pipeline = VideoPipelineDecodebin(self)
        else:
            self._pipeline = VideoPipelineH264(self)

    def play(self, fileName):
        self.setAlpha(0.0)
        self._resetPipeline()
        self._pipeline.setSourceFile(fileName)
        self._pipeline.start()
        self._output.onSlotActivated(self)

    def stop(self):
        self._pipeline.stop()

    def setAlpha(self, alpha):
        if self._output._plane is None:
            logger.warning("Fading not suppored, no KMS plane present.")
            return

        self._alpha = min(1.0, max(0.0, alpha))
        gstStruct = Gst.Structure("s")
        value = int(self._alpha * 64000.0)
        self._output._plane.set_props({"alpha": value})

    def setZPos(self, zPos):
        if self.output._plane is None:
            return

        self._output._plane.set_props({"zpos": zPos})

    def update(self, dt):
        if self._state == SlotState.DEACTIVATED:
            pass
        elif self._state == SlotState.DEACTIVATING:
            if self.fading:
                alpha = self._alpha - (dt * 4.0)
                if alpha > 0.0:
                    self.setAlpha(alpha)
                else:
                    self.setZPos(1)
                    self._state = SlotState.DEACTIVATED
            else:
                self.setAlpha(0.0)
                if self._pipeline != None:
                    self._pipeline.stop()
                    del self._pipeline
                    self._pipeline = None
                self._state = SlotState.DEACTIVATED
        elif self._state == SlotState.ACTIVATING:
            if self.fading:
                alpha = self._alpha + (dt * 4.0)
                logger.debug("alpha: %s", alpha)
                if alpha < 1.0:
                    self.setAlpha(alpha)
                else:
                    self.setZPos(2)
                    self._state = SlotState.ACTIVE
            else:
                self.setAlpha(1.0)
                self._state = SlotState.ACTIVE
        elif self._state == SlotState.ACTIVE:
            pass


def switchVideos():
    global index

    fileName0 = fileNames0[index]
    vmOne.play_video(output_number=1, file_name=fileName0)

    GLib.timeout_add_seconds(3, switchVideos)
    index = index + 1
    index = index % len(fileNames0)


if __name__ == "__main__":
    is_raspi_5 = False
    try:
        # https://raspberrypi.stackexchange.com/questions/5100/detect-that-a-python-program-is-running-on-the-pi
        with open("/sys/firmware/devicetree/base/model") as model:
            RPi_model = model.read()
            logger.debug("firmware model string: %s ", RPi_model)
            if RPi_model.startswith("Raspberry Pi 5"):
                logger.info("This seems to be a raspberry pi 5, using KMS and activate both HDMI outputs")
                is_raspi_5 = True

    except FileNotFoundError:
        logger.info("This seems to be not a raspberry pi, using test environment")

    if is_raspi_5:
        import pykms  # type: ignore

    index = 0
    videoElements = []
    vmOne = VideoMachine(use_test_environment=not is_raspi_5)
    fileNames0 = ["/home/gordon/test/butterfly.mp4", "/home/gordon/test/bird.mp4"]

    switchVideos()
    vmOne.start()
