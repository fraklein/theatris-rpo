from pathlib import Path

import pytest
from pytest_mock import mocker

from theatris_rpo.media_registry.media_registry import MediaRegistry, LOG_MESSAGES


@pytest.fixture
def valid_base_dir_str():
    return "/home/user/video_files_for_playout"


@pytest.fixture
def media_registry(valid_base_dir_str):
    return MediaRegistry(Path(valid_base_dir_str))


@pytest.fixture
def fake_file_list(valid_base_dir_str):
    return [
        valid_base_dir_str + "/invalidfilenonumber.mp4",
        valid_base_dir_str + "/invalid_file_no_number.mp4",
        valid_base_dir_str + "/invalid_file_no_number_2.txt",
        valid_base_dir_str + "/1_valid_file_1.mp4",
        valid_base_dir_str + "/2_valid_file_2.mov",
        valid_base_dir_str + "/3_valid_file_3.avi",
        valid_base_dir_str + "/1_invalid_file_same_number.avi",
        valid_base_dir_str + "/subdir/999_valid_file_in_subdir_1.mp4",
        valid_base_dir_str + "/subdir/100_valid_file_in_subdir_2.mov",
        valid_base_dir_str + "/subdir2/100_invalid_file_in_subdir_same_number.mp4",
    ]


@pytest.fixture
def number_of_valid_files():
    return 5


@pytest.fixture
def create_fake_files(fs, fake_file_list):
    for f in fake_file_list:
        fs.create_file(f)


class TestMediaRegistry:
    def test_registry_scan_rejects_nonexisting_base_directory(self, media_registry):
        # Arrange

        # Act
        media_registry.scan_files()

        # Assert
        assert media_registry.valid is False

    def test_registry_scan_rejects_file_as_base_directory(self, fs, valid_base_dir_str):
        # Arrange
        file_name = valid_base_dir_str + "/filename"
        fs.create_file(file_name)
        sut = MediaRegistry(Path(file_name))

        # Act
        sut.scan_files()

        # Assert
        assert sut.valid is False

    def test_registry_rejects_files_not_starting_with_a_number(
        self,
        media_registry,
        fs,
        valid_base_dir_str,
        caplog,
    ):
        # Arrange
        f = valid_base_dir_str + "/invalid_file_no_number.mp4"
        fs.create_file(f)

        # Act
        media_registry.scan_files()

        # Assert
        assert len(media_registry.files_by_number) == 0
        assert any(
            [
                LOG_MESSAGES["file_does_not_start_with_integer"].format(f) == rt.msg
                for rt in caplog.records
            ]
        )

    def test_registry_rejects_files_not_with_duplicated_number(
        self,
        media_registry,
        fs,
        valid_base_dir_str,
        caplog,
    ):
        # Arrange
        f1 = valid_base_dir_str + "/123_valid.mp4"
        fs.create_file(f1)
        f2 = valid_base_dir_str + "/123_doublet.mp4"
        fs.create_file(f2)
        # Assume all files have valid format
        media_registry._check_media_format = lambda f: True

        # Act
        media_registry.scan_files()

        # Assert
        assert len(media_registry.files_by_number) == 1
        assert any(
            [
                LOG_MESSAGES["file_number_twice"].format(f2) == rt.msg
                for rt in caplog.records
            ]
        )
        assert str(media_registry.files_by_number[123]) == str(Path(f1))

    def test_registry_scans_existing_base_directory(
        self, media_registry, create_fake_files, number_of_valid_files
    ):
        # Arrange
        # Assume all files have valid format
        media_registry._check_media_format = lambda f: True

        # Act
        media_registry.scan_files()

        # Assert
        assert media_registry.valid is True
        assert len(media_registry.files_by_number) == number_of_valid_files

    def test_media_discovery(
        self,
        fs,
        caplog,
        request,
    ):
        # Arrange
        fs.add_real_directory(
            request.config.rootpath
        )  # / "test_videos/99_unittest_sample.mp4")
        media_registry = MediaRegistry(request.config.rootpath / "test_videos")

        # Act
        media_registry.scan_files()

        test_video_path = request.config.rootpath / "test_videos"
        for f in test_video_path.iterdir():
            media_registry._check_media_format(f)

        # Assert
        # assert media_registry.valid is True
        # assert len(media_registry.files_by_number) == number_of_valid_files
