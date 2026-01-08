import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theatris_rpo.video_machine import VideoMachine


class BaseInterface(abc.ABC):
    def __init__(self, vm: "VideoMachine"):
        self._vm = vm

    def stop(self):
        pass

    @abc.abstractmethod
    def send_heartbeat(self, beat_state: bool):
        pass


class SyncOscInterfaceMixin(abc.ABC):
    @abc.abstractmethod
    def sync_start(self):
        pass


class AsyncOscInterfaceMixin(abc.ABC):
    @abc.abstractmethod
    async def async_start(self):
        pass
