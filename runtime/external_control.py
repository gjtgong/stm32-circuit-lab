"""Small Python client for Renode 1.16's External Control socket.

The portable runtime shipped with this lab uses the original ``RE`` framed
protocol implemented by Renode's ``tools/external_control_client`` library.
Keeping this client in Python avoids a host compiler dependency while GPIO
events still carry Renode's own virtual timestamps directly to the API.
"""
from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
import time
from typing import Dict, Iterable, Optional


CMD_RUN_FOR = 1
CMD_GET_TIME = 2
CMD_GET_MACHINE = 3
CMD_GPIO = 5

RETURN_COMMAND_FAILED = 0
RETURN_FATAL_ERROR = 1
RETURN_INVALID_COMMAND = 2
RETURN_SUCCESS_WITH_DATA = 3
RETURN_SUCCESS_WITHOUT_DATA = 4
RETURN_SUCCESS_HANDSHAKE = 5
RETURN_ASYNC_EVENT = 6

_REQUEST_HEADER = struct.Struct("<2sBI")
_GPIO_HEADER = struct.Struct("<iBi")


class ExternalControlError(RuntimeError):
    """A protocol or Renode-side error with a user-facing message."""


@dataclass(frozen=True)
class GPIOEvent:
    """One output transition reported by Renode."""

    port: str
    pin: int
    time_ns: int
    value: int


class ExternalControlClient:
    """Drive one Renode machine and collect GPIO output events."""

    def __init__(self, host: str, port: int, *, timeout: float = 15.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.socket: Optional[socket.socket] = None
        self._callbacks: Dict[int, tuple[str, int]] = {}
        self.events: list[GPIOEvent] = []
        self._event_callback_id = 0

    def connect(self, *, deadline: Optional[float] = None) -> None:
        end = deadline if deadline is not None else time.monotonic() + self.timeout
        last_error: Optional[BaseException] = None
        while time.monotonic() < end:
            try:
                self.socket = socket.create_connection((self.host, self.port), timeout=0.5)
                self.socket.settimeout(0.5)
                self._handshake(end)
                return
            except (OSError, ExternalControlError) as exc:
                last_error = exc
                self.close()
                time.sleep(0.03)
        message = f"could not connect to Renode external-control server on {self.host}:{self.port}"
        if last_error:
            message += f": {last_error}"
        raise ExternalControlError(message)

    def close(self) -> None:
        sock, self.socket = self.socket, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def __enter__(self) -> "ExternalControlClient":
        self.connect()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def get_machine(self, name: str) -> int:
        encoded = name.encode("utf-8")
        response = self._request(CMD_GET_MACHINE, struct.pack("<I", len(encoded)) + encoded)
        if len(response) != 4:
            raise ExternalControlError("Renode returned an invalid machine descriptor")
        return struct.unpack("<i", response)[0]

    def _get_gpio_instance(self, machine_id: int, name: str) -> int:
        encoded = name.encode("utf-8")
        # -1 asks Renode to register a new instance; the resulting descriptor
        # is local to this external-control connection.
        data = struct.pack("<iii", -1, machine_id, len(encoded)) + encoded
        response = self._request(CMD_GPIO, data)
        if len(response) != 4:
            raise ExternalControlError(f"Renode returned an invalid GPIO descriptor for {name}")
        return struct.unpack("<i", response)[0]

    def get_gpio_state(self, gpio_id: int, pin: int) -> bool:
        response = self._request(CMD_GPIO, _GPIO_HEADER.pack(gpio_id, 0, int(pin)))
        if len(response) != 1:
            raise ExternalControlError("Renode returned an invalid GPIO state")
        return bool(response[0])

    def set_gpio_state(self, gpio_id: int, pin: int, state: bool) -> None:
        self._request(CMD_GPIO, _GPIO_HEADER.pack(gpio_id, 1, int(pin)) + bytes([int(bool(state))]))

    def register_gpio_event(self, gpio_id: int, port: str, pin: int) -> None:
        event_id = self._event_callback_id
        self._event_callback_id += 1
        self._callbacks[event_id] = (port, int(pin))
        self._request(CMD_GPIO, _GPIO_HEADER.pack(gpio_id, 2, int(pin)) + struct.pack("<I", event_id))

    def register_port_events(self, machine_id: int, ports: Iterable[str], *, pins: int = 16) -> None:
        for port in ports:
            gpio_id = self._get_gpio_instance(machine_id, f"gpioPort{port}")
            for pin in range(pins):
                self.register_gpio_event(gpio_id, port, pin)

    def run_for(self, milliseconds: int) -> None:
        if milliseconds < 0:
            raise ValueError("duration cannot be negative")
        # Renode 1.16's API uses microseconds for RunFor.
        self._request(CMD_RUN_FOR, struct.pack("<Q", int(milliseconds) * 1_000))

    def get_time_ns(self) -> int:
        response = self._request(CMD_GET_TIME, b"")
        if len(response) != 8:
            raise ExternalControlError("Renode returned an invalid virtual time")
        return struct.unpack("<Q", response)[0] * 1_000

    def _handshake(self, deadline: float) -> None:
        # The first uint16 is the number of command-version pairs that follow;
        # the reserved pair occupies the first two bytes of the array.
        versions = bytearray(14)
        struct.pack_into("<H", versions, 0, 6)
        for index, pair in enumerate(((1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (6, 0))):
            struct.pack_into("<BB", versions, 2 + index * 2, *pair)
        self._send_raw(bytes(versions))
        response = self._read_exact(1, deadline)[0]
        if response != RETURN_SUCCESS_HANDSHAKE:
            raise ExternalControlError(f"Renode external-control handshake failed (return code {response})")

    def _request(self, command: int, data: bytes, *, deadline: Optional[float] = None) -> bytes:
        if self.socket is None:
            raise ExternalControlError("Renode external-control socket is closed")
        end = deadline if deadline is not None else time.monotonic() + self.timeout
        self._send(command, data)
        while True:
            if time.monotonic() >= end:
                raise ExternalControlError("timed out waiting for Renode external-control response")
            return_code, response_command, response_data = self._receive(end)
            if return_code == RETURN_ASYNC_EVENT:
                self._handle_event(response_command, response_data)
                continue
            if return_code in (RETURN_SUCCESS_WITH_DATA, RETURN_SUCCESS_WITHOUT_DATA) and response_command != command:
                raise ExternalControlError(f"Renode returned command {response_command} while waiting for {command}")
            if return_code == RETURN_SUCCESS_WITH_DATA:
                return response_data
            if return_code == RETURN_SUCCESS_WITHOUT_DATA:
                return b""
            if return_code in (RETURN_COMMAND_FAILED, RETURN_FATAL_ERROR):
                detail = response_data.decode("utf-8", "replace")
                raise ExternalControlError(detail or "Renode external-control command failed")
            if return_code == RETURN_INVALID_COMMAND:
                raise ExternalControlError(f"Renode does not support external-control command {command}")
            raise ExternalControlError(f"Renode returned unknown response type {return_code}")

    def _send(self, command: int, data: bytes) -> None:
        self._send_raw(_REQUEST_HEADER.pack(b"RE", int(command), len(data)) + data)

    def _send_raw(self, packet: bytes) -> None:
        sock = self.socket
        if sock is None:
            raise ExternalControlError("Renode external-control socket is closed")
        try:
            sock.sendall(packet)
        except OSError as exc:
            raise ExternalControlError(f"external-control send failed: {exc}") from exc

    def _receive(self, deadline: float) -> tuple[int, int, bytes]:
        return_code = self._read_exact(1, deadline)[0]
        if return_code == RETURN_ASYNC_EVENT:
            command = self._read_exact(1, deadline)[0]
            callback_id = struct.unpack("<I", self._read_exact(4, deadline))[0]
            size = struct.unpack("<I", self._read_exact(4, deadline))[0]
            if size > 16 * 1024 * 1024:
                raise ExternalControlError(f"invalid event payload size {size}")
            data = struct.pack("<I", callback_id) + self._read_exact(size, deadline)
            return return_code, command, data
        command = 0
        if return_code in (RETURN_COMMAND_FAILED, RETURN_INVALID_COMMAND, RETURN_SUCCESS_WITH_DATA, RETURN_SUCCESS_WITHOUT_DATA):
            command = self._read_exact(1, deadline)[0]
        if return_code in (RETURN_COMMAND_FAILED, RETURN_FATAL_ERROR):
            size = struct.unpack("<I", self._read_exact(4, deadline))[0]
            if size > 16 * 1024 * 1024:
                raise ExternalControlError(f"invalid error payload size {size}")
            data = self._read_exact(size, deadline)
        elif return_code == RETURN_SUCCESS_WITH_DATA:
            size = struct.unpack("<I", self._read_exact(4, deadline))[0]
            if size > 16 * 1024 * 1024:
                raise ExternalControlError(f"invalid response payload size {size}")
            data = self._read_exact(size, deadline)
        elif return_code in (RETURN_INVALID_COMMAND, RETURN_SUCCESS_WITHOUT_DATA):
            data = b""
        else:
            raise ExternalControlError(f"Renode returned unknown response type {return_code}")
        return return_code, command, data

    def _handle_event(self, command: int, data: bytes) -> None:
        if command != CMD_GPIO or len(data) < 4:
            return
        event_id = struct.unpack_from("<I", data, 0)[0]
        event_data = data[4:]
        if len(event_data) < 9:
            raise ExternalControlError("Renode returned a truncated GPIO event")
        timestamp_us = struct.unpack_from("<Q", event_data, 0)[0]
        state = 1 if event_data[8] else 0
        location = self._callbacks.get(event_id)
        if location is not None:
            port, pin = location
            self.events.append(GPIOEvent(port, pin, timestamp_us * 1_000, state))

    def _read_exact(self, count: int, deadline: float) -> bytes:
        sock = self.socket
        if sock is None:
            raise ExternalControlError("Renode external-control socket is closed")
        result = bytearray()
        while len(result) < count:
            timeout = max(0.01, min(0.5, deadline - time.monotonic()))
            if timeout <= 0:
                raise ExternalControlError("timed out reading Renode external-control response")
            sock.settimeout(timeout)
            try:
                chunk = sock.recv(count - len(result))
            except socket.timeout:
                continue
            except OSError as exc:
                raise ExternalControlError(f"external-control receive failed: {exc}") from exc
            if not chunk:
                raise ExternalControlError("Renode closed the external-control socket")
            result.extend(chunk)
        return bytes(result)


__all__ = ["ExternalControlClient", "ExternalControlError", "GPIOEvent"]
