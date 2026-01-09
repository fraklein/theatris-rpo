# theatris-rpo

Remotely OSC-controlled video player for the Raspberry Pi 5

![Python Version >=3.12](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Ffraklein%2Ftheatris-rpo%2Frefs%2Fheads%2Fmain%2Fpyproject.toml)

Headless video player that is controlled via [Open Sound Control (OSC)](https://opensoundcontrol.stanford.edu) and runs
headless on a Raspberry Pi 5. No display server (e.g. X11) is required, the player directly uses
[DRM](https://en.wikipedia.org/wiki/Direct_Rendering_Manager)/[KMS](https://en.wikipedia.org/wiki/Direct_Rendering_Manager#Kernel_mode_setting)
and is started on the console.

The project was created due to the need of a small drama group with no budget to play videos on multiple screens that
are far apart from each other and the control booth.

This project was inspired by the [VM1](https://github.com/zwodev/vm1-video-mixer) project, which python test scripts put
me in the right direction of how to use GStreamer on a headless Raspberry Pi.

## Status

- Nota bene: This has beta status at max.
- Only tested on a Raspberry Pi 5 with Raspberry Pi OS 5 Trixie (13.2)
- Only tested with mp4 container format with H.264 video format
- Files that contain no audio are not working, even when the audio is not used at the moment
- Connect and power up your displays before booting the Raspberry Pi, otherwise playback might fail.

## Features

- Runs on a headless raspberry pi 5
- Controllable via [OSC](https://opensoundcontrol.stanford.edu)
- Features advertised with [OSCQuery](https://github.com/Vidvox/OSCQueryProposal) for easy integration e.g.
  into [Chataigne](https://benjamin.kuperberg.fr/chataigne/en)
- Utilizes both HDMI outputs of the Raspberry Pi 5
- Multiple video slots per output are possible which can be played independently of each other
- Alpha value can be set per slot via OSC. This makes fading between multiple videos that are playing simultaneously
  possible
- Feedback is sent back via OSC

## Installation / Usage

At the moment, just clone this repository and run via uv:

```bash
> git clone git@github.com:fraklein/theatris-rpo.git 
> cd theatris-rpo/
> uv run src/theatris_rpo/__main__.py /full/path/to/directory/where/video_files/are/located
```

### File name conventions

At startup, the given directory is scanned for media files. All files that should be considered for playback must start
with a number, e.g. ```123_test_video.mp4```.
This number is used to refer to specific files when sending the ```play_by_number``` command via OSC.

### Play a file

To play a file, send an OSC message to the desired output and slot number, with the file number as argument.
For each output, two slots are created at startup.
For example, to play file number 123 on the first HDMI output on the second slot, send to OSC address
```/output0/slot/play_by_number``` with and integer argument of ```123```

## Further development

A lot is left to do:

- Stabilize the GStreamer pipelines to work more reliably with all kinds of formats
- Make the kmssink work if a display is connected at runtime
- Add more OSC commands / status feedback
- Create "auto-fading" functionality to fade between slots
- Make an installable package