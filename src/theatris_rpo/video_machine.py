import asyncio
import sys
from pathlib import Path

from gi.events import GLibEventLoopPolicy  # type: ignore
from gi.repository import GLib, Gst
from returns.pointfree import bind
from returns.result import Result, Failure, Success
from returns.pipeline import flow

from theatris_rpo.base_interface import BaseInterface
from theatris_rpo.media_registry.media_registry import MediaRegistry
from theatris_rpo.slot_flag import SlotFlag
from video_output import BaseOutput, TestOutput, HDMIOutput
from osc_interface import OscInterface
from log import logger


class VideoMachine:
    def __init__(self, media_file_path_str: str, use_test_environment: bool):
        self._outputs: list[BaseOutput] = []

        if not use_test_environment:
            # Create actual KMS outputs on raspberry pi
            import kms

            self._card = kms.Card()
            self._res = kms.ResourceManager(self._card)

            self._outputs = [
                HDMIOutput(self._res, self._card.fd, "HDMI-A-1"),
                HDMIOutput(self._res, self._card.fd, "HDMI-A-2"),
            ]
        else:
            self._outputs = [
                TestOutput("Test Output 1"),
                TestOutput("Test Output 2"),
            ]

        # Initialize Gstreamer
        Gst.init()
        logger.debug("Gstreamer Version: %s", Gst.version())

        self._media = MediaRegistry(Path(media_file_path_str))
        self._media.scan_files()

        if not self._media.valid:
            logger.fatal("Could not scan media files. Aborting.")
            sys.exit(1)

        # Create slots without loading a file. File can be set later.
        self._outputs[0].add_video_slot(None)
        self._outputs[0].add_video_slot(None)
        self._outputs[1].add_video_slot(None)
        self._outputs[1].add_video_slot(None)

        # set up asyncio
        policy = GLibEventLoopPolicy()
        asyncio.set_event_loop_policy(policy)
        self._asyncio_loop = policy.get_event_loop()

        self._mainloop = GLib.MainLoop()

        self._interfaces: list[BaseInterface] = []

        # set up OSC interface
        self._interfaces.append(OscInterface("0.0.0.0", 9000, self))

    @property
    def outputs(self) -> dict[int, BaseOutput]:
        return {o.id: o for o in self._outputs}

    def start(self):
        self._heartbeat()
        self._update()

        try:
            logger.debug("Starting interfaces")
            for interface in self._interfaces:
                if hasattr(interface, "async_start"):
                    self._asyncio_loop.create_task(interface.async_start())
                if hasattr(interface, "sync_start"):
                    interface.sync_start()
            logger.debug("Starting main loop")
            self._mainloop.run()

        except KeyboardInterrupt:
            for interface in self._interfaces:
                interface.stop()
            logger.info("Stopped by keyboard interrupt")

    def play_video(
        self,
        output_number: int,
        slot_number: int,
        file_number: int | None = None,
        restart_if_already_playing: bool = False,
    ) -> Result[None, str]:
        try:
            output = self.outputs[output_number]
        except KeyError:
            msg = f"No output with number {output_number} present. Active outputs are {self.outputs}"
            logger.error(msg)
            return Failure(msg)

        file_path = None
        if file_number is not None:
            try:
                file_path = self._media.files_by_number[file_number]
            except KeyError:
                msg = f"No file with number {file_number} present. Available files are {[(k, str(v)) for k, v in self._media.files_by_number.items()]}"  # fmt: skip
                logger.error(msg)
                return Failure(msg)

        return output.play_video(slot_number, file_path, restart_if_already_playing)

    def play_test(
        self,
        output_number: int,
        slot_number: int,
    ) -> Result[None, str]:
        return flow(
            self._get_output(output_number),
            bind(lambda output: output.play_test(slot_number)),
        )

    def stop_playout(
        self, output_number: int | None = None, slot_number: int | None = None
    ) -> Result[None, str]:
        if output_number is None:
            # Stop all outputs
            for output in self.outputs.values():
                return output.stop_all_video()
        try:
            output = self.outputs[output_number]
        except KeyError:
            msg = f"No output with number {output_number} present. Active outputs are {self.outputs}"
            logger.error(msg)
            return Failure(msg)

        if slot_number is None:
            return output.stop_all_video()

        return output.stop_video(slot_number)

    def set_alpha(
        self, output_number: int, slot_number: int, alpha: float
    ) -> Result[None, str]:
        return flow(
            self._get_output(output_number),
            bind(lambda output: output.set_alpha(slot_number, alpha)),
        )

    def pause_video(
        self,
        output_number: int,
        slot_number: int,
    ) -> Result[None, str]:
        return flow(
            self._get_output(output_number),
            bind(lambda output: output.pause(slot_number)),
        )

    def set_slot_config(
        self, output_number: int, slot_number: int, slot_flag: SlotFlag, *args
    ) -> Result[None, str]:
        return flow(
            self._get_output(output_number),
            bind(lambda output: output.set_slot_config(slot_number, slot_flag, *args)),
        )

    def _get_output(self, output_number: int) -> Result[BaseOutput, str]:
        try:
            return Success(self.outputs[output_number])
        except KeyError:
            msg = f"No output with number {output_number} present. Active outputs are {self.outputs}"
            logger.error(msg)
            return Failure(msg)

    def _update(self):
        dt = 0.016
        for output in self.outputs.values():
            output.update(dt)

        GLib.timeout_add(int(dt * 1000.0), self._update)

    def _heartbeat(self, beat_state: bool = False):
        logger.debug("Heart is beating, state %s", beat_state)
        for interface in self._interfaces:
            interface.send_heartbeat(beat_state)
        beat_state = not beat_state

        GLib.timeout_add(int(1.0 * 1000.0), self._heartbeat, beat_state)
