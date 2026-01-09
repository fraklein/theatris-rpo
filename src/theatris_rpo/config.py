import enum
from typing import Any


class Conf(enum.Enum):
    IS_RASPI_5 = enum.auto()


class Config:
    def __init__(self):
        self._values = {
            Conf.IS_RASPI_5: False,
        }

    @property
    def config(self) -> dict[Conf, Any]:
        return self._values


config = Config().config
