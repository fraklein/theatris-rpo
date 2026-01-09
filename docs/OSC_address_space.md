OSC API
========

Work in progress

An asterisk (\*) marks containers/methods that are already implemented

Sending
--------

- */heartbeat
- /outputX
- /outputX/is_connected
- /outputX/slotX
- /outputX/state
- /outputX/is_initialized
- /outputX/is_playing
- /outputX/is_loop_active
- /outputX/is_pushing_other_slots
- /outputX/current_source
- /outputX/curent_fade_time
- /outputX/current_elapsed_time

Note to self:

```python
# query the current position of the stream
ret, current = self.playbin.query_position(
    Gst.Format.TIME)
if not ret:
    print("ERROR: Could not query current position")
```

Receiving
---------

- */outputX
- */stop_all
- */outputX/slotX
- */outputX/slotX/play_by_number(number:int, restart_when_already_playing: bool)
- */outputX/slotX/stop
- */outputX/slotX/set_alpha
- */outputX/slotX/play_test
- */outputX/slotX/pause
- */outputX/slotX/cfg_set_full_alpha_at_start(On_Off:bool)
- */outputX/slotX/cfg_set_loop(On_Off:bool)
- /outputX/slotX/cfg_set_fade_time(seconds: float) # maybe two times: in and out?
- /outputX/slotX/cfg_set_push_other_slots(On_Off:bool)  # When this slot starts, stop (and possibly fade out) all other
  playing slots on
  this output
- /outputX/slotX/seek(time:?)
- /outputX/slotX/play # play already initialized pipeline. This might be required for speed.
- */outputX/slotX/stop_all
