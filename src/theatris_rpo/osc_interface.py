import asyncio
import time
from typing import TYPE_CHECKING, Any

import pythonoscquery.pythonosc_callback_wrapper
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonoscquery.osc_query_service import OSCQueryService
from pythonoscquery.shared.osc_access import OSCAccess
from pythonoscquery.shared.osc_address_space import OSCAddressSpace
from pythonoscquery.shared.osc_path_node import OSCPathNode
from pythonoscquery.shared.oscquery_spec import OSCQueryAttribute
from returns.result import Success, Failure

from log import logger
from theatris_rpo.base_interface import BaseInterface, AsyncOscInterfaceMixin
from theatris_rpo.slot_flag import SlotFlag

if TYPE_CHECKING:
    from video_machine import VideoMachine


class OscInterface(BaseInterface, AsyncOscInterfaceMixin):
    def __init__(self, ip_address, port, video_machine: "VideoMachine"):
        super().__init__(video_machine)
        self._video_machine = video_machine

        self._ip = ip_address
        self._port = port

        self._transport = None
        self._protocol = None

        self._address_space = OSCAddressSpace()

        self._dispatcher = Dispatcher()

        #####
        ## Sending
        #####
        self._address_space.add_node(
            OSCPathNode(
                "/heartbeat",
                access=OSCAccess.READONLY_VALUE,
                description="Heartbeat. Changes every second if the server is alive",
                value=[True],
            )
        )

        #####
        ## Receiving
        #####

        # /stop_all
        pythonoscquery.pythonosc_callback_wrapper.map_node(
            OSCPathNode(
                f"/stop_all",
                access=OSCAccess.NO_VALUE,
                description=f"Stop all playing slots on all outputs",
            ),
            self._dispatcher,
            self._handler_stop,
            self._address_space,
        )

        # /outputX/stop_all
        for output in self._video_machine.outputs.values():
            pythonoscquery.pythonosc_callback_wrapper.map_node(
                OSCPathNode(
                    f"/output{output.id}/stop_all",
                    access=OSCAccess.NO_VALUE,
                    description=f"Stop all playing slots on output {output.id}",
                ),
                self._dispatcher,
                self._handler_stop,
                self._address_space,
                output.id,
            )

        # /outputX/slotY/stop
        for output in self._video_machine.outputs.values():
            for slot in output.video_slots:
                pythonoscquery.pythonosc_callback_wrapper.map_node(
                    OSCPathNode(
                        f"/output{output.id}/slot{slot.id}/stop",
                        access=OSCAccess.NO_VALUE,
                        description=f"Stop video on slot {slot.id} on output {output.id}",
                    ),
                    self._dispatcher,
                    self._handler_stop,
                    self._address_space,
                    output.id,
                    slot.id,
                )

        # /outputX/slotY/play_by_number
        for output in self._video_machine.outputs.values():
            for slot in output.video_slots:
                pythonoscquery.pythonosc_callback_wrapper.map_node(
                    OSCPathNode(
                        f"/output{output.id}/slot{slot.id}/play_by_number",
                        access=OSCAccess.WRITEONLY_VALUE,
                        description=f"Play file by its number on slot {slot.id} on output {output.id}",
                        value=[
                            1,
                            False,
                        ],  # number of file, restart when this file is already playing
                    ),
                    self._dispatcher,
                    self._handler_play_by_number,
                    self._address_space,
                    output.id,
                    slot.id,
                )

        # /outputX/slotY/play_test
        for output in self._video_machine.outputs.values():
            for slot in output.video_slots:
                pythonoscquery.pythonosc_callback_wrapper.map_node(
                    OSCPathNode(
                        f"/output{output.id}/slot{slot.id}/play_test",
                        access=OSCAccess.NO_VALUE,
                        description=f"Play a test sequence on slot {slot.id} on output {output.id}",
                    ),
                    self._dispatcher,
                    self._handler_play_test,
                    self._address_space,
                    output.id,
                    slot.id,
                )

        # /outputX/slotY/set_alpha
        for output in self._video_machine.outputs.values():
            for slot in output.video_slots:
                pythonoscquery.pythonosc_callback_wrapper.map_node(
                    OSCPathNode(
                        f"/output{output.id}/slot{slot.id}/set_alpha",
                        access=OSCAccess.WRITEONLY_VALUE,
                        description=f"Set alpha value on slot {slot.id} on output {output.id}",
                        value=100.0,
                    ),
                    self._dispatcher,
                    self._handler_set_alpha,
                    self._address_space,
                    output.id,
                    slot.id,
                )

        # /outputX/slotY/pause
        for output in self._video_machine.outputs.values():
            for slot in output.video_slots:
                pythonoscquery.pythonosc_callback_wrapper.map_node(
                    OSCPathNode(
                        f"/output{output.id}/slot{slot.id}/pause",
                        access=OSCAccess.NO_VALUE,
                        description=f"Play a test sequence on slot {slot.id} on output {output.id}",
                    ),
                    self._dispatcher,
                    self._handler_pause,
                    self._address_space,
                    output.id,
                    slot.id,
                )

        # /outputX/slotY/cfg_set_full_alpha_when_starting
        for output in self._video_machine.outputs.values():
            for slot in output.video_slots:
                pythonoscquery.pythonosc_callback_wrapper.map_node(
                    OSCPathNode(
                        f"/output{output.id}/slot{slot.id}/cfg_set_full_alpha_when_starting",
                        access=OSCAccess.WRITEONLY_VALUE,
                        description=f"Set alpha value to 1.0 when starting playback on slot {slot.id} on output {output.id}",
                        value=False,
                    ),
                    self._dispatcher,
                    self._handler_cfg_set_alpha_to_full_at_start,
                    self._address_space,
                    output.id,
                    slot.id,
                )

        # /outputX/slotY/cfg_set_loop
        for output in self._video_machine.outputs.values():
            for slot in output.video_slots:
                pythonoscquery.pythonosc_callback_wrapper.map_node(
                    OSCPathNode(
                        f"/output{output.id}/slot{slot.id}/cfg_set_loop",
                        access=OSCAccess.WRITEONLY_VALUE,
                        description=f"Set alpha value to 1.0 when starting playback on slot {slot.id} on output {output.id}",
                        value=False,
                    ),
                    self._dispatcher,
                    self._handler_cfg_set_looping,
                    self._address_space,
                    output.id,
                    slot.id,
                )

        self._dispatcher.set_default_handler(self._handler_default)

        self._oscquery_server = None

    async def async_start(self):
        server = AsyncIOOSCUDPServer(
            (self._ip, self._port),
            self._dispatcher,
            asyncio.get_event_loop(),  # type: ignore
        )
        self._transport, self._protocol = await server.create_serve_endpoint()

        logger.info("Started OSC server")

    def sync_start(self):
        self._oscquery_server = OSCQueryService(
            self._address_space, "theatris_rpo", self._port, self._port, self._ip
        )
        logger.info("Started OSCquery server")

    def stop(self):
        self._transport.close()

    def send_heartbeat(self, beat_state: bool):
        hbn = self._address_space.find_node("/heartbeat")
        if hbn:
            hbn.attributes[OSCQueryAttribute.VALUE] = [
                beat_state
            ]  # TODO: Once python-oscquery supports updating of node values, change this

    def _handler_default(self, address, *args):
        logger.debug(f"{address}: {args}")
        return "/", f"{args} at {time.ctime()} from {self._video_machine}"

    def _handler_play(self, address, *args):
        """Play already initialized slot.
        This might be required for speed (instant playback), but at the moment
        it looks like setting the file source each time playback is started is also
        fast enough."""
        logger.debug(f"{address}: {args}")
        self._video_machine.play_video(args[0], args[1])

    def _handler_play_by_number(
        self, address, args: list[int], number: int, restart_if_already_playing: bool
    ):
        output: int | None = self._assign_fixed_arg(0, args)
        slot: int | None = self._assign_fixed_arg(1, args)

        match self._video_machine.play_video(
            output, slot, number, restart_if_already_playing
        ):
            case Success():
                return None
            case Failure(msg):
                return address, msg
        return None

    def _handler_play_test(self, address, args: list[int]):
        output: int | None = self._assign_fixed_arg(0, args)
        slot: int | None = self._assign_fixed_arg(1, args)

        match self._video_machine.play_test(output, slot):
            case Success():
                return None
            case Failure(msg):
                return address, msg
        return None

    def _handler_stop(self, address, args: list[int] = None):
        output: int | None = self._assign_fixed_arg(0, args)
        slot: int | None = self._assign_fixed_arg(1, args)

        match self._video_machine.stop_playout(output, slot):
            case Success():
                return None
            case Failure(msg):
                return address, msg
        return None

    def _handler_set_alpha(self, address, args: list[int], alpha_value: float):
        output: int | None = self._assign_fixed_arg(0, args)
        slot: int | None = self._assign_fixed_arg(1, args)

        match self._video_machine.set_alpha(output, slot, alpha_value):
            case Success():
                return None
            case Failure(msg):
                return address, msg
        return None

    def _handler_pause(self, address, args: list[int]):
        output: int | None = self._assign_fixed_arg(0, args)
        slot: int | None = self._assign_fixed_arg(1, args)

        match self._video_machine.pause_video(output, slot):
            case Success():
                return None
            case Failure(msg):
                return address, msg
        return None

    def _handler_cfg_set_alpha_to_full_at_start(
        self, address, args: list[int], on_off: bool
    ):
        output: int | None = self._assign_fixed_arg(0, args)
        slot: int | None = self._assign_fixed_arg(1, args)

        match self._video_machine.set_slot_config(
            output, slot, SlotFlag.FULL_ALPHA_AT_START, on_off
        ):
            case Success():
                return None
            case Failure(msg):
                return address, msg
        return None

    def _handler_cfg_set_looping(self, address, args: list[int], on_off: bool):
        output: int | None = self._assign_fixed_arg(0, args)
        slot: int | None = self._assign_fixed_arg(1, args)

        match self._video_machine.set_slot_config(
            output, slot, SlotFlag.LOOPING, on_off
        ):
            case Success():
                return None
            case Failure(msg):
                return address, msg
        return None

    @staticmethod
    def _assign_fixed_arg(pos: int, args: list[Any]) -> Any | None:
        try:
            return args[pos]
        except (IndexError, TypeError):
            return None
