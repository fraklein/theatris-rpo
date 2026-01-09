import enum
from typing import Any


class Conf(enum.Enum):
    IS_RASPI_5 = enum.auto()
    OUTPUT0_WIDTH = enum.auto()
    OUTPUT0_HEIGHT = enum.auto()
    OUTPUT1_WIDTH = enum.auto()
    OUTPUT1_HEIGHT = enum.auto()


class Config:
    def __init__(self):
        self._values = {
            Conf.IS_RASPI_5: False,
            Conf.OUTPUT0_WIDTH: 800,
            Conf.OUTPUT0_HEIGHT: 480,
            Conf.OUTPUT1_WIDTH: 800,
            Conf.OUTPUT1_HEIGHT: 480,
        }

    @property
    def config(self) -> dict[Conf, Any]:
        return self._values


config = Config().config
