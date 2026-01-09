import argparse

import gi

from log import logger
from theatris_rpo.config import config, Conf
from video_machine import VideoMachine

gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
gi.require_version("Gst", "1.0")


if __name__ == "__main__":
    is_raspi_5 = False
    try:
        # https://raspberrypi.stackexchange.com/questions/5100/detect-that-a-python-program-is-running-on-the-pi
        with open("/sys/firmware/devicetree/base/model") as model:
            RPi_model = model.read()
            logger.debug("firmware model string: %s ", RPi_model)
            if RPi_model.startswith("Raspberry Pi 5"):
                logger.info(
                    "This seems to be a raspberry pi 5, using KMS and activate both HDMI outputs"
                )
                is_raspi_5 = True

    except FileNotFoundError:
        logger.info("This seems not to be a raspberry pi, using test environment")

    config[Conf.IS_RASPI_5] = is_raspi_5

    def init_argparse() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="theatris_rpo",
            usage="%(prog)s [OPTION] [BASE_DIR]...",
            description="OSC-controlled video player for raspberry pi.",
        )

        parser.add_argument(
            "base_dir",
            help="Absolute file path to the directory where media files are located",
        )

        return parser

    parser = init_argparse()
    args = parser.parse_args()

    vm = VideoMachine(args.base_dir)
    vm.start()
