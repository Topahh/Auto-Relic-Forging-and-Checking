#!/usr/bin/env /usr/bin/python3

import os
import sys
import time
import secrets

import cv2
import numpy as np
import dbus
from dbus.mainloop.glib import DBusGMainLoop
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gst, GLib

DBusGMainLoop(set_as_default=True)
Gst.init(None)


class PersistentScreenCast:
    def __init__(self):
        self.bus = dbus.SessionBus()
        self.portal = self.bus.get_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        self.sc = dbus.Interface(self.portal, "org.freedesktop.portal.ScreenCast")
        self.session_iface = dbus.Interface(self.portal, "org.freedesktop.portal.Session")
        self.session_handle = None
        self.pw_node_id = None
        self.error = None
        self.pipeline = None
        self.sink = None
        self.restore_token = None
        self.stream_info = None
        self._loop = None

    def _run_request(self, request_path, callback, timeout_s=30):
        loop = GLib.MainLoop()
        result = {"done": False}
        timeout_id = None

        def finish():
            if result["done"]:
                return
            result["done"] = True
            try:
                if timeout_id is not None:
                    GLib.source_remove(timeout_id)
            except Exception:
                pass
            try:
                loop.quit()
            except Exception:
                pass

        def wrapped(response, results):
            callback(response, results)
            finish()

        req_obj = self.bus.get_object("org.freedesktop.portal.Desktop", request_path)
        req = dbus.Interface(req_obj, "org.freedesktop.portal.Request")
        req.connect_to_signal("Response", wrapped)

        timeout_id = GLib.timeout_add_seconds(
            timeout_s,
            lambda: self._fail(f"Portal timeout after {timeout_s}s") or finish() or False,
        )
        self._loop = loop
        loop.run()
        self._loop = None

    def _fail(self, msg):
        self.error = msg
        try:
            if self._loop is not None:
                self._loop.quit()
        except Exception:
            pass

    def create_session(self):
        token = secrets.token_hex(8)
        options = dbus.Dictionary(
            {
                "session_handle_token": dbus.String(f"session_{token}"),
                "handle_token": dbus.String(f"req_{token}"),
            },
            signature="sv",
        )
        request_path = self.sc.CreateSession(options)
        self._run_request(request_path, self._on_create_session)
        if self.error:
            raise RuntimeError(self.error)

    def _on_create_session(self, response, results):
        if response != 0:
            self._fail(f"CreateSession failed: response={response}")
            return
        self.session_handle = str(results["session_handle"])

    def select_sources(self):
        token = secrets.token_hex(8)
        options = dbus.Dictionary(
            {
                "types": dbus.UInt32(1),
                "multiple": dbus.Boolean(False),
                "cursor_mode": dbus.UInt32(2),
                "persist_mode": dbus.UInt32(2),
                "handle_token": dbus.String(f"req_{token}"),
            },
            signature="sv",
        )
        request_path = self.sc.SelectSources(self.session_handle, options)
        self._run_request(request_path, self._on_select_sources)
        if self.error:
            raise RuntimeError(self.error)

    def _on_select_sources(self, response, results):
        if response != 0:
            self._fail(f"SelectSources failed: response={response}")

    def start(self):
        token = secrets.token_hex(8)
        options = {"handle_token": dbus.String(f"req_{token}")}
        if self.restore_token:
            options["restore_token"] = dbus.String(self.restore_token)
        request_path = self.sc.Start(
            self.session_handle,
            "",
            dbus.Dictionary(options, signature="sv"),
        )
        self._run_request(request_path, self._on_start)
        if self.error:
            raise RuntimeError(self.error)

    def _on_start(self, response, results):
        if response != 0:
            self._fail(f"Start failed: response={response}")
            return

        streams = results.get("streams")
        if not streams:
            self._fail("No streams returned")
            return

        self.restore_token = str(results.get("restore_token", "")) or None
        self.stream_info = dict(streams[0][1]) if len(streams[0]) > 1 else {}
        self.pw_node_id = int(streams[0][0])

    def init_session(self):
        self.create_session()
        self.select_sources()
        self.start()
        if not self.pw_node_id:
            raise RuntimeError("No PipeWire node id received")

    def init_pipeline(self):
        pipeline_desc = (
            f"pipewiresrc path={self.pw_node_id} do-timestamp=true keepalive-time=1000 ! "
            "queue max-size-buffers=1 leaky=downstream ! "
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink name=sink emit-signals=false sync=false max-buffers=1 drop=true"
        )

        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.sink = self.pipeline.get_by_name("sink")
        if self.sink is None:
            raise RuntimeError("Unable to get appsink")

        self.sink.set_property("max-buffers", 1)
        self.sink.set_property("drop", True)
        self.sink.set_property("sync", False)

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start GStreamer pipeline")

        bus = self.pipeline.get_bus()
        msg = bus.timed_pop_filtered(
            5 * Gst.SECOND,
            Gst.MessageType.ERROR | Gst.MessageType.ASYNC_DONE | Gst.MessageType.STATE_CHANGED,
        )
        if msg and msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            raise RuntimeError(f"Pipeline error: {err}; {debug}")

    def capture_frame(self, retries=5, timeout_s=3):
        if self.sink is None:
            raise RuntimeError("Pipeline not initialized")

        for attempt in range(1, retries + 1):
            sample = self.sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
            if sample is None:
                if attempt < retries:
                    time.sleep(0.2)
                    continue
                raise RuntimeError("No sample received from PipeWire")

            buf = sample.get_buffer()
            caps = sample.get_caps()
            if caps is None:
                if attempt < retries:
                    time.sleep(0.1)
                    continue
                raise RuntimeError("No caps on sample")

            s = caps.get_structure(0)
            width = int(s.get_value("width"))
            height = int(s.get_value("height"))
            fmt = str(s.get_value("format"))

            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if not ok:
                if attempt < retries:
                    time.sleep(0.1)
                    continue
                raise RuntimeError("Buffer map failed")

            try:
                arr = np.frombuffer(mapinfo.data, dtype=np.uint8)
                expected_bgr = width * height * 3
                expected_bgrx = width * height * 4

                if fmt == "BGR" and arr.size >= expected_bgr:
                    frame = arr[:expected_bgr].reshape((height, width, 3))
                elif fmt in {"BGRx", "BGRA", "xRGB", "ARGB", "RGBx", "RGBA"} and arr.size >= expected_bgrx:
                    frame = arr[:expected_bgrx].reshape((height, width, 4))[:, :, :3]
                else:
                    raise RuntimeError(f"Unexpected format or buffer size: fmt={fmt}, size={arr.size}")

                if frame.size == 0:
                    raise RuntimeError("Empty frame")

                if np.mean(frame) < 2:
                    if attempt < retries:
                        time.sleep(0.2)
                        continue

                return frame.copy()
            finally:
                buf.unmap(mapinfo)

        raise RuntimeError("Frame capture failed")

    def close(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.sink = None
        if self.session_handle is not None:
            try:
                self.session_iface.Close(self.session_handle)
            except Exception:
                pass
            self.session_handle = None


def main():
    sc = PersistentScreenCast()

    try:
        sc.init_session()
        sc.init_pipeline()
        print("READY", flush=True)

        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            if line == "QUIT":
                print("BYE", flush=True)
                break

            if line.startswith("CAPTURE "):
                out_path = line[len("CAPTURE "):].strip()
                try:
                    out_path = os.path.abspath(out_path)
                    frame = sc.capture_frame(retries=5, timeout_s=3)
                    ok = cv2.imwrite(out_path, frame)
                    if not ok:
                        print(f"ERR Failed to write PNG: {out_path}", flush=True)
                    else:
                        print(f"OK {out_path}", flush=True)
                except Exception as e:
                    print(f"ERR {e}", flush=True)
                continue

            print(f"ERR Unknown command: {line}", flush=True)

    except Exception as e:
        print(f"FATAL {e}", flush=True)
        sys.exit(1)
    finally:
        sc.close()


if __name__ == "__main__":
    main()