import logging
from pathlib import Path
from typing import Iterator

import gi

gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GstPbutils  # noqa: E402

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s.%(msecs)03d][%(name)s] [%(levelname)8s] - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


LOG_MESSAGES = {
    "file_does_not_start_with_integer": "File name must start with an integer number. Ignoring file %s",
    "file_number_twice": "File number at least present twice. Ignoring file %s",
    "file_format_invalid": "File format is invalid. Ignoring file %s",
}


class MediaRegistry:
    def __init__(self, base_dir: Path):
        self._base_dir: Path = base_dir
        self._files_by_number = dict()
        self._valid: bool = False

    @property
    def valid(self) -> bool:
        return self._valid

    @property
    def files_by_number(self) -> dict:
        return self._files_by_number

    def file_path(self, number: int) -> Path | None:
        try:
            return self._files_by_number[number]
        except KeyError:
            logger.error(f"No file with number {number}")

    def scan_files(self):
        if not self._base_dir.exists():
            logger.error(f"Base directory {self._base_dir} does not exist")
            return

        if not self._base_dir.is_dir():
            logger.error(f"Base directory {self._base_dir} is not a directory")
            return

        Gst.init(None)

        for path in self._iterdir_recursive(self._base_dir):
            if not path.is_file():
                continue

            parts = path.stem.split("_")

            if not parts[0].isdigit():
                logger.warning(LOG_MESSAGES["file_does_not_start_with_integer"] % path)
                continue

            number = int(parts[0])

            if number in self._files_by_number.keys():
                logger.warning(LOG_MESSAGES["file_number_twice"] % path)
                continue

            if not self._check_media_format(path):
                logger.warning(LOG_MESSAGES["file_format_invalid"] % path)
                continue

            self._files_by_number[number] = path

        self._valid = True

    def _iterdir_recursive(self, path: Path) -> Iterator[Path]:
        if not path.is_dir():
            return
        for p in path.iterdir():
            if p.is_dir():
                yield from self._iterdir_recursive(p)
            else:
                yield p

    @staticmethod
    def _check_media_format(path: Path) -> bool:
        discoverer = GstPbutils.Discoverer()
        logger.info(f"File {path} discovered data:")
        try:
            info = discoverer.discover_uri("file://" + str(path))
        except Exception as e:
            logger.error(e)
            return False

        video_present = False

        # video info
        logger.info(" # video")
        for vinfo in info.get_video_streams():
            logger.info(f"    {vinfo.get_caps().to_string().replace(', ', '\n\t')}")
            video_present = True

        # audio info
        logger.info(" # audio")
        for ainfo in info.get_audio_streams():
            logger.info(f"    {ainfo.get_caps().to_string().replace(', ', '\n\t')}")

        # For now, if we can parse the media, and it has any video, let's assume it can be played. This might need more
        # detailed type checking.
        return video_present


# Todo
# Check for valid format

# via osc:
# play given filenumber on given slot
# -> Check if setting the filesrc is enough to change the file and HOW FAST THIS IS


# 99_O1_S1_P1_name
# 99_O1_S1_P1_name
