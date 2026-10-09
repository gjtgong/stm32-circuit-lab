#!/usr/bin/env python3
"""Local STM32F103ZET6 compile-and-run backend.

The server compiles submitted C into an ARM ELF, starts a local Renode
process, and uses Renode's external-control protocol to collect real GPIO
state-change events and virtual timestamps. It intentionally has no software
fallback: when Renode or the ARM toolchain is unavailable, status is false and
run requests return a useful error.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass, field
import json
import mimetypes
import os
from pathlib import Path
import posixpath
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import re
from typing import Any, Optional
from urllib.parse import unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from runtime.external_control import ExternalControlClient, ExternalControlError


ROOT = Path(__file__).resolve().parent
FIRMWARE = ROOT / "firmware"
RUNTIME = ROOT / "runtime"
EXAMPLES = ROOT / "examples"
STATIC = ROOT / "static"

def load_pcb_report() -> dict:
    """Serve only a locally generated report still matching its source inputs."""
    report = json.loads((ROOT / 'reports/gerber-check.json').read_text())
    hashes = report.get('inputHashes', {})
    required = {'references/open-board/EasyEDA_F103ZET6.Pcb.api.json',
                'references/open-board/gerber/Gerber_TopLayer.GTL',
                'references/open-board/gerber/Gerber_BottomLayer.GBL'}
    if set(hashes) != required:
        raise ValueError('报告缺少来源校验，请重新运行 python3 tools/gerber_check.py')
    for relative, expected in hashes.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError('PCB 来源已变化，请重新生成检查报告')
    return report


HOST = os.environ.get("STM32_LAB_HOST", "127.0.0.1")
PORT = int(os.environ.get("STM32_LAB_PORT", "8765"))
VIRTUAL_RUN_MS = 2000
WALL_TIMEOUT_S = 15.0
COMPILE_TIMEOUT_S = 12.0
MAX_SOURCE_BYTES = 128 * 1024
MAX_PROJECT_FILES = 32
MAX_PROJECT_BYTES = 512 * 1024
MAX_IMPORTED_ELF_BYTES = 512 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
GPIO_PORTS = tuple("ABCDEFG")

FLASH_START = 0x08000000
FLASH_SIZE = 512 * 1024
FLASH_END = FLASH_START + FLASH_SIZE
RAM_START = 0x20000000
RAM_SIZE = 64 * 1024
RAM_END = RAM_START + RAM_SIZE

ELF32_HEADER = struct.Struct("<16sHHIIIIIHHHHHH")
ELF32_PROGRAM_HEADER = struct.Struct("<IIIIIIII")
ELF_MAGIC = b"\x7fELF"
ELF_CLASS_32 = 1
ELF_DATA_LITTLE = 1
ELF_VERSION_CURRENT = 1
ELF_TYPE_EXEC = 2
ELF_MACHINE_ARM = 40
ELF_PT_LOAD = 1

LIMITATIONS = [
    "Renode models STM32F1 GPIO ports A-G, USART1, NVIC/SysTick, RCC/AFIO storage, 512 KiB flash, and 64 KiB SRAM.",
    "ADC, USB, CAN, SDIO, SPI, I2C sensor devices, DMA, hardware PWM/advanced timers, and the full RCC/AFIO clock tree are outside this MVP; GPIO bit-bang pulses are traceable.",
    "Each run advances at most 2000 ms of virtual time and 15 seconds of wall time.",
    "The ELF flash image is linked at 0x08000000 and the same 512 KiB object is also visible through the Cortex-M reset alias at 0x00000000; peripheral register addresses retain STM32F1 values.",
    "Multi-file imports are limited to 32 UTF-8 .c/.h files and 512 KiB total; imported ELF files must be validated ARM ELF32 little-endian images within the local flash/RAM map.",
]


def _find_toolchain() -> Optional[str]:
    configured = os.environ.get("ARM_NONE_EABI_GCC")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("arm-none-eabi-gcc")


def _find_renode() -> Optional[str]:
    configured = os.environ.get("STM32_LAB_RENODE") or os.environ.get("RENODE_BIN")
    candidates: list[Path] = []
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_dir():
            candidates.extend((configured_path / "renode", configured_path / "renode.exe"))
        else:
            candidates.append(configured_path)

    candidates.extend(
        [
            RUNTIME / "renode" / "renode",
            RUNTIME / "renode" / "renode.exe",
            RUNTIME / "renode" / "Renode",
            Path("/opt/renode/renode"),
        ]
    )
    path_command = shutil.which("renode")
    if path_command:
        candidates.append(Path(path_command))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    # The portable archive may have a versioned top-level directory. Keep the
    # search local and shallow so a missing/incomplete extraction is cheap.
    renode_root = RUNTIME / "renode"
    if renode_root.is_dir():
        for candidate in sorted(renode_root.glob("*/renode")):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _status() -> dict[str, Any]:
    compiler = _find_toolchain()
    renode = _find_renode()
    limitations = list(LIMITATIONS)
    if compiler is None:
        limitations.append("arm-none-eabi-gcc is unavailable on the local host.")
    if renode is None:
        limitations.append("Renode portable runtime is unavailable; set RENODE_BIN or extract it under runtime/renode/.")
    return {
        "ready": compiler is not None and renode is not None,
        "engine": "renode" if renode is not None else "unavailable",
        "uartSupported": renode is not None,
        "limitations": limitations,
    }


def _run_command(command: list[str], *, cwd: Path, timeout: float) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return completed.returncode, completed.stdout or ""
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return 124, f"command timed out after {timeout:.1f}s\n{output}"
    except OSError as exc:
        return 127, f"could not start {command[0]}: {exc}"


def _safe_project_path(name: Any) -> tuple[Optional[str], Optional[str]]:
    """Validate one imported project path without touching the filesystem."""
    if not isinstance(name, str) or not name:
        return None, "file names must be non-empty strings"
    if "\x00" in name:
        return None, "file names may not contain NUL bytes"
    # The compiler runs on Linux, but rejecting backslashes and drive prefixes
    # also prevents a Windows-style absolute path from being accepted here.
    if "\\" in name or re.match(r"^[A-Za-z]:", name):
        return None, f"unsafe project path {name!r}; use relative POSIX paths"
    if name.startswith("/") or posixpath.isabs(name):
        return None, f"unsafe project path {name!r}; absolute paths are not allowed"
    components = name.split("/")
    if any(component == ".." for component in components):
        return None, f"unsafe project path {name!r}; '..' components are not allowed"
    if any(component == "" for component in components):
        return None, f"unsafe project path {name!r}; empty path components are not allowed"
    normalized = posixpath.normpath(name)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None, f"unsafe project path {name!r}"
    if Path(normalized).suffix.lower() not in {".c", ".h"}:
        return None, f"unsupported project file {name!r}; only .c and .h files are accepted"
    return normalized, None


def _validate_project_files(files: Any) -> tuple[Optional[dict[str, str]], Optional[str]]:
    """Validate and normalize the bounded ``files`` request variant."""
    if not isinstance(files, dict):
        return None, "files must be an object mapping relative .c/.h paths to text"
    if not files:
        return None, "files must contain at least one .c or .h file"
    if len(files) > MAX_PROJECT_FILES:
        return None, f"files exceeds the {MAX_PROJECT_FILES}-file limit"

    normalized: dict[str, str] = {}
    total_bytes = 0
    for raw_name, text in files.items():
        name, error = _safe_project_path(raw_name)
        if error:
            return None, error
        if not isinstance(text, str):
            return None, f"files.{raw_name} must be UTF-8 text"
        assert name is not None
        if name in normalized:
            return None, f"duplicate project path after normalization: {name}"
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > MAX_PROJECT_BYTES:
            return None, f"project files exceed the {MAX_PROJECT_BYTES}-byte limit"
        normalized[name] = text

    if not any(Path(name).suffix.lower() == ".c" for name in normalized):
        return None, "project files must contain at least one .c source file"
    return normalized, None


def _compile_files(files: dict[str, str], workdir: Path, compiler: str) -> tuple[Optional[Path], str]:
    validated, validation_error = _validate_project_files(files)
    if validation_error:
        return None, "project files invalid: " + validation_error
    assert validated is not None

    startup_object = workdir / "startup.o"
    elf_path = workdir / "firmware.elf"
    map_path = workdir / "firmware.map"

    source_paths: list[tuple[str, Path]] = []
    for index, (name, text) in enumerate(validated.items()):
        path = workdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if path.suffix.lower() == ".c":
            source_paths.append((name, path))

    common = [
        compiler,
        "-mcpu=cortex-m3",
        "-mthumb",
        "-mfloat-abi=soft",
        "-ffreestanding",
        "-fno-builtin",
        "-fdata-sections",
        "-ffunction-sections",
        "-Os",
        "-Wall",
        "-Wextra",
        "-Wno-unused-parameter",
        "-I",
        str(workdir),
        "-I",
        str(FIRMWARE),
    ]
    log_parts: list[str] = []
    return_code, output = _run_command(common + ["-c", str(FIRMWARE / "startup.c"), "-o", str(startup_object)], cwd=ROOT, timeout=COMPILE_TIMEOUT_S)
    if output:
        log_parts.append(output)
    if return_code != 0:
        return None, "startup compile failed:\n" + "".join(log_parts).strip()

    app_objects: list[Path] = []
    for index, (name, source_path) in enumerate(source_paths):
        app_object = workdir / f"project_{index}.o"
        return_code, output = _run_command(
            common + ["-c", str(source_path), "-o", str(app_object)],
            cwd=ROOT,
            timeout=COMPILE_TIMEOUT_S,
        )
        if output:
            log_parts.append(output)
        if return_code != 0:
            prefix = "user code compile failed" if len(source_paths) == 1 and name == "main.c" else f"project file {name} compile failed"
            return None, prefix + ":\n" + "".join(log_parts).strip()
        app_objects.append(app_object)

    link_command = [
        compiler,
        "-mcpu=cortex-m3",
        "-mthumb",
        "-mfloat-abi=soft",
        "-nostartfiles",
        "-Wl,--gc-sections",
        "-Wl,-Map=" + str(map_path),
        "-T",
        str(FIRMWARE / "linker.ld"),
        str(startup_object),
        *[str(app_object) for app_object in app_objects],
        "-lgcc",
        "-o",
        str(elf_path),
    ]
    return_code, output = _run_command(link_command, cwd=ROOT, timeout=COMPILE_TIMEOUT_S)
    if output:
        log_parts.append(output)
    if return_code != 0:
        return None, "link failed:\n" + "".join(log_parts).strip()
    return elf_path, "".join(log_parts).strip()


def _compile_source(source: str, workdir: Path, compiler: str) -> tuple[Optional[Path], str]:
    """Compatibility wrapper for the original single-file ``code`` API."""
    if not isinstance(source, str):
        return None, "user code must be a string"
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return None, f"code exceeds {MAX_SOURCE_BYTES} bytes"
    return _compile_files({"main.c": source}, workdir, compiler)


def _range_within(start: int, size: int, lower: int, upper: int) -> bool:
    """Return whether an unsigned address range is fully inside a map."""
    if size < 0 or start < lower:
        return False
    end = start + size
    return end >= start and end <= upper


def _elf_bytes_at(
    elf: bytes,
    segments: list[tuple[int, int, int, int, int, int, int, int]],
    address: int,
    size: int,
) -> Optional[bytes]:
    """Read bytes at a load address from one of the validated PT_LOAD ranges."""
    for _type, offset, vaddr, paddr, filesz, _memsz, _flags, _align in segments:
        if size < 0 or address < 0:
            continue
        for base in (vaddr, paddr):
            if base <= address and _range_within(address - base, size, 0, filesz):
                file_offset = offset + (address - base)
                end = file_offset + size
                if 0 <= file_offset <= end <= len(elf):
                    return elf[file_offset:end]
    return None


def _validate_imported_elf(elf: Any) -> Optional[str]:
    """Validate an externally-built ARM ELF against the local memory map.

    The local Renode machine consumes ELF PT_LOAD segments directly.  Keep
    this check deliberately strict: only ELF32 little-endian ARM ET_EXEC
    images with a physical flash vector table and load ranges contained in the
    board's 512 KiB flash / 64 KiB SRAM maps are accepted.
    """
    if not isinstance(elf, (bytes, bytearray, memoryview)):
        return "elfBase64 must decode to bytes"
    elf_bytes = bytes(elf)
    if not elf_bytes:
        return "imported ELF is empty"
    if len(elf_bytes) > MAX_IMPORTED_ELF_BYTES:
        return f"imported ELF exceeds the {MAX_IMPORTED_ELF_BYTES}-byte limit"
    if len(elf_bytes) < ELF32_HEADER.size:
        return "imported ELF is truncated"
    if elf_bytes[:4] != ELF_MAGIC:
        return "imported file is not an ELF image"
    ident = elf_bytes[:16]
    if ident[4] != ELF_CLASS_32:
        return "imported ELF must be ELF32"
    if ident[5] != ELF_DATA_LITTLE:
        return "imported ELF must use little-endian byte order"
    if ident[6] != ELF_VERSION_CURRENT:
        return "imported ELF has an unsupported identification version"

    (
        _ident,
        elf_type,
        machine,
        version,
        entry,
        phoff,
        _shoff,
        _flags,
        ehsize,
        phentsize,
        phnum,
        _shentsize,
        _shnum,
        _shstrndx,
    ) = ELF32_HEADER.unpack_from(elf_bytes, 0)
    if elf_type != ELF_TYPE_EXEC:
        return "imported ELF must be an executable ET_EXEC image"
    if machine != ELF_MACHINE_ARM:
        return "imported ELF machine must be ARM (EM_ARM)"
    if version != ELF_VERSION_CURRENT:
        return "imported ELF has an unsupported version"
    if ehsize != ELF32_HEADER.size or phentsize != ELF32_PROGRAM_HEADER.size:
        return "imported ELF has unsupported ELF/program-header sizes"
    if phnum == 0 or phnum > 128:
        return "imported ELF has no usable program headers"
    ph_table_end = phoff + phnum * phentsize
    if phoff < ELF32_HEADER.size or ph_table_end < phoff or ph_table_end > len(elf_bytes):
        return "imported ELF program-header table is outside the file"

    segments: list[tuple[int, int, int, int, int, int, int, int]] = []
    for index in range(phnum):
        start = phoff + index * phentsize
        segment = ELF32_PROGRAM_HEADER.unpack_from(elf_bytes, start)
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = segment
        if p_type != ELF_PT_LOAD:
            continue
        if p_filesz > p_memsz:
            return f"imported ELF PT_LOAD {index} has filesz larger than memsz"
        if p_offset + p_filesz < p_offset or p_offset + p_filesz > len(elf_bytes):
            return f"imported ELF PT_LOAD {index} extends past the file"
        if p_memsz == 0 and not (
            FLASH_START <= p_vaddr <= FLASH_END or RAM_START <= p_vaddr <= RAM_END
        ):
            return f"imported ELF PT_LOAD {index} starts outside local flash/RAM"
        if p_memsz and not (
            _range_within(p_vaddr, p_memsz, FLASH_START, FLASH_END)
            or _range_within(p_vaddr, p_memsz, RAM_START, RAM_END)
        ):
            return f"imported ELF PT_LOAD {index} maps outside local flash/RAM"
        # A few external ARM linkers leave p_paddr zero and use the virtual
        # load address as the physical address.  Treat that conventional
        # zero as an omitted field; any non-zero physical address is checked
        # strictly against the local map.
        physical_address = p_paddr if p_paddr != 0 else p_vaddr
        if p_filesz == 0 and p_paddr != 0 and not (
            FLASH_START <= p_paddr <= FLASH_END or RAM_START <= p_paddr <= RAM_END
        ):
            return f"imported ELF PT_LOAD {index} has unsupported physical address"
        if p_filesz and not (
            _range_within(physical_address, p_filesz, FLASH_START, FLASH_END)
            or _range_within(physical_address, p_filesz, RAM_START, RAM_END)
        ):
            return f"imported ELF PT_LOAD {index} has unsupported physical address"
        if p_vaddr + p_memsz > 0x100000000 or p_vaddr + p_memsz < p_vaddr:
            return f"imported ELF PT_LOAD {index} has an overflowing virtual address"
        segments.append(segment)

    if not segments:
        return "imported ELF has no PT_LOAD segments"
    if not (FLASH_START <= (entry & ~1) < FLASH_END) or (entry & 1) == 0:
        return "imported ELF entry point must be a Thumb address in physical flash"

    vector = _elf_bytes_at(elf_bytes, segments, FLASH_START, 8)
    if vector is None:
        return "imported ELF must provide a vector table at 0x08000000"
    initial_sp, reset_vector = struct.unpack_from("<II", vector, 0)
    if initial_sp % 4 != 0 or not (RAM_START <= initial_sp <= RAM_END):
        return "imported ELF initial stack pointer is outside the 64 KiB SRAM map"
    if (reset_vector & 1) == 0 or not (FLASH_START <= (reset_vector & ~1) < FLASH_END):
        return "imported ELF reset vector must be a Thumb address in physical flash"
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _resc_path(path: Path) -> str:
    # All generated files are under /tmp, so the compact @path form avoids
    # Renode's monitor parser treating path characters as separate arguments.
    return "@" + str(path)


def _write_resc(workdir: Path, elf: Path, serial: Path, repl: Path, control_port: int) -> Path:
    script = workdir / "run.resc"
    script.write_text(
        "\n".join(
            [
                # Level 2 keeps the Renode console quiet enough for a local
                # HTTP request while retaining errors in the run log.
                "logLevel 2",
                'mach create "stm32-lab"',
                f"machine LoadPlatformDescription {_resc_path(repl)}",
                # Busy-loop delays in beginner firmware otherwise make a
                # two-second virtual run needlessly expensive on the host.
                "cpu PerformanceInMips 1000",
                f"sysbus LoadELF {_resc_path(elf)}",
                f"usart1 CreateFileBackend {_resc_path(serial)}",
                f'emulation CreateExternalControlServer "api" {control_port}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return script


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _clean_log(value: str) -> str:
    """Keep Renode diagnostics readable when returned through JSON."""
    return _ANSI_ESCAPE.sub("", value).strip()


@dataclass
class _RunState:
    process: Optional[subprocess.Popen[str]] = None
    stop_requested: threading.Event = field(default_factory=threading.Event)


_run_lock = threading.Lock()
_state_lock = threading.Lock()
_active_state: Optional[_RunState] = None


def _terminate_process(process: Optional[subprocess.Popen[str]]) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass


def stop_active_run() -> bool:
    with _state_lock:
        state = _active_state
        if state is None:
            return False
        state.stop_requested.set()
        process = state.process
    _terminate_process(process)
    return True


def _finish_renode(process: subprocess.Popen[str], log_path: Path, *, send_quit: bool) -> str:
    if send_quit and process.poll() is None:
        try:
            if process.stdin is not None:
                process.stdin.write("q\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
    try:
        process.communicate(timeout=3.0)
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        try:
            process.communicate(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        return log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    except OSError:
        return ""


def _run_simulation(
    source: Optional[str],
    inputs: dict[str, Any],
    *,
    files: Optional[dict[str, str]] = None,
    elf_bytes: Optional[bytes] = None,
    external_elf: Optional[bytes] = None,
) -> dict[str, Any]:
    """Compile or load one bounded firmware input, then run the same Renode path.

    ``source`` remains the original positional single-file API.  ``files``
    supplies a validated multi-file project and ``elf_bytes``/``external_elf``
    supplies an externally built ARM ELF.  Exactly one input form is accepted.
    """
    compiler = _find_toolchain()
    renode = _find_renode()
    if external_elf is not None:
        if elf_bytes is not None:
            return {"ok": False, "log": "specify only one imported ELF value"}
        elf_bytes = external_elf
    selected_inputs = int(source is not None) + int(files is not None) + int(elf_bytes is not None)
    if selected_inputs != 1:
        return {"ok": False, "log": "provide exactly one of code, files, or elfBase64"}

    if files is not None:
        files, file_error = _validate_project_files(files)
        if file_error:
            return {"ok": False, "log": "project files invalid: " + file_error}
    if source is not None and not isinstance(source, str):
        return {"ok": False, "log": "code must be a string"}
    if source is not None and len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return {"ok": False, "log": f"code exceeds {MAX_SOURCE_BYTES} bytes"}
    if elf_bytes is not None:
        elf_error = _validate_imported_elf(elf_bytes)
        if elf_error:
            return {"ok": False, "log": "imported ELF invalid: " + elf_error}

    if renode is None or (compiler is None and elf_bytes is None):
        missing = []
        if compiler is None and elf_bytes is None:
            missing.append("arm-none-eabi-gcc")
        if renode is None:
            missing.append("Renode portable runtime")
        return {"ok": False, "log": "backend unavailable: " + ", ".join(missing)}

    if not isinstance(inputs, dict):
        return {"ok": False, "log": "inputs must be an object"}
    input_states: dict[tuple[str, int], int] = {}
    for pin_name, raw_value in inputs.items():
        match = re.fullmatch(r"P([A-G])(?:([0-9]|1[0-5]))", str(pin_name))
        if match is None:
            return {"ok": False, "log": f"unsupported input pin {pin_name}; use PA0..PG15"}
        value = int(raw_value) if isinstance(raw_value, bool) else raw_value
        if not isinstance(value, int) or value not in (0, 1):
            return {"ok": False, "log": f"inputs.{pin_name} must be 0 or 1"}
        input_states[(match.group(1), int(match.group(2)))] = value

    with tempfile.TemporaryDirectory(prefix="stm32-lab-") as temp_dir:
        workdir = Path(temp_dir)
        compile_log = ""
        if elf_bytes is not None:
            elf = workdir / "firmware.elf"
            try:
                elf.write_bytes(bytes(elf_bytes))
            except OSError as exc:
                return {"ok": False, "log": f"could not stage imported ELF: {exc}"}
        elif files is not None:
            assert compiler is not None
            elf, compile_log = _compile_files(files, workdir, compiler)
            if elf is None:
                return {"ok": False, "log": compile_log}
        else:
            assert source is not None and compiler is not None
            elf, compile_log = _compile_source(source, workdir, compiler)
            if elf is None:
                return {"ok": False, "log": compile_log}

        serial_path = workdir / "usart1.log"
        repl_path = workdir / "stm32f103.repl"
        shutil.copyfile(RUNTIME / "stm32f103.repl", repl_path)
        control_port = _free_port()
        resc = _write_resc(workdir, elf, serial_path, repl_path, control_port)
        renode_log_path = workdir / "renode.log"
        renode_log = renode_log_path.open("w", encoding="utf-8", errors="replace")
        try:
            process = subprocess.Popen(
                [renode, "--disable-gui", "--console", str(resc)],
                cwd=str(ROOT),
                stdin=subprocess.PIPE,
                stdout=renode_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            renode_log.close()
            return {"ok": False, "log": f"could not start Renode: {exc}"}

        state = _RunState(process=process)
        with _state_lock:
            global _active_state
            _active_state = state

        output = ""
        client: Optional[ExternalControlClient] = None
        try:
            client = ExternalControlClient("127.0.0.1", control_port, timeout=WALL_TIMEOUT_S)
            client.connect(deadline=time.monotonic() + 7.0)
            machine_id = client.get_machine("stm32-lab")
            gpio_instances: dict[str, int] = {}
            for port, _pin in input_states:
                gpio_instances.setdefault(port, client._get_gpio_instance(machine_id, f"gpioPort{port}"))
            for (port, pin), value in input_states.items():
                client.set_gpio_state(gpio_instances[port], pin, bool(value))
            client.register_port_events(machine_id, GPIO_PORTS)
            client.run_for(VIRTUAL_RUN_MS)
            virtual_duration_ns = client.get_time_ns()
            events = [
                {"timeMs": round(event.time_ns / 1_000_000.0, 6), "pin": f"P{event.port}{event.pin}", "value": event.value}
                for event in sorted(client.events, key=lambda item: (item.time_ns, item.port, item.pin))
            ]
            client.close()
            output = _finish_renode(process, renode_log_path, send_quit=True)
            try:
                serial = serial_path.read_text(encoding="utf-8", errors="replace") if serial_path.exists() else ""
            except OSError as exc:
                serial = f"[USART1 capture unavailable: {exc}]"
            log = _clean_log(output)
            if compile_log:
                log = _clean_log(compile_log + "\n" + log)
            return {
                "ok": True,
                "events": events,
                "serial": serial,
                "log": log,
                "durationMs": round(virtual_duration_ns / 1_000_000.0, 3),
            }
        except (ExternalControlError, OSError, subprocess.TimeoutExpired) as exc:
            if client is not None:
                client.close()
            if state.stop_requested.is_set():
                detail = "simulation stopped by request"
            else:
                detail = str(exc)
            output = _finish_renode(process, renode_log_path, send_quit=False)
            log = _clean_log(detail + ("\n" + output if output else ""))
            return {"ok": False, "log": log}
        finally:
            if client is not None:
                client.close()
            if process.poll() is None:
                _terminate_process(process)
            renode_log.close()
            with _state_lock:
                if _active_state is state:
                    _active_state = None
    # Unreachable, retained to make type checkers happy.
    return {"ok": False, "log": "simulation did not produce a result"}


def _decode_run_firmware(request: Any) -> tuple[Optional[str], Optional[dict[str, str]], Optional[bytes], Optional[str]]:
    """Decode exactly one firmware input variant from an ``/api/run`` body."""
    if not isinstance(request, dict):
        return None, None, None, "request must be a JSON object"

    field_names = ("code", "files", "elfBase64")
    present = [name for name in field_names if name in request]
    if len(present) != 1:
        return None, None, None, "provide exactly one of code, files, or elfBase64"

    selected = present[0]
    if selected == "code":
        source = request["code"]
        if not isinstance(source, str):
            return None, None, None, "code must be a string"
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            return None, None, None, f"code exceeds {MAX_SOURCE_BYTES} bytes"
        return source, None, None, None

    if selected == "files":
        files, error = _validate_project_files(request["files"])
        if error:
            return None, None, None, "project files invalid: " + error
        assert files is not None
        return None, files, None, None

    encoded = request["elfBase64"]
    if not isinstance(encoded, str):
        return None, None, None, "elfBase64 must be a base64 string"
    max_encoded = ((MAX_IMPORTED_ELF_BYTES + 2) // 3) * 4
    if len(encoded) > max_encoded:
        return None, None, None, f"elfBase64 exceeds the {MAX_IMPORTED_ELF_BYTES}-byte ELF limit"
    try:
        elf = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        return None, None, None, "elfBase64 is not valid strict base64"
    elf_error = _validate_imported_elf(elf)
    if elf_error:
        return None, None, None, "imported ELF invalid: " + elf_error
    return None, None, elf, None


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _local_host_header(value: str) -> bool:
    """Accept only loopback Host values for the local compiler service."""
    try:
        parsed = urlparse("//" + value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port or 80
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"} and port == PORT


def _allowed_origin(value: str) -> bool:
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and host in {"127.0.0.1", "localhost", "::1"} and port == PORT


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep browser polling from filling the terminal; errors remain in API
        # responses and Renode's own output is returned from /api/run.
        if self.path.startswith("/api/") and self.command == "POST":
            super().log_message(format, *args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin")
        if origin and _allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _require_local_request(self) -> bool:
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        if (host and not _local_host_header(host)) or (origin and not _allowed_origin(origin)):
            self._send_json({"ok": False, "log": "local backend accepts loopback requests only"}, 403)
            return False
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if not self._require_local_request():
            return
        self.send_response(204)
        origin = self.headers.get("Origin")
        if origin and _allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._require_local_request():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json(_status())
            return
        if parsed.path == "/api/pcb-check":
            try:
                self._send_json(load_pcb_report())
            except (OSError, ValueError) as exc:
                self._send_json({"error": str(exc), "hint": "运行 python3 tools/gerber_check.py 后刷新检查"}, 409)
            return
        if parsed.path == "/api/example":
            example = EXAMPLES / "blink.c"
            try:
                code = example.read_text(encoding="utf-8")
            except OSError as exc:
                self._send_json({"error": str(exc)}, 500)
                return
            if parsed.query == "raw=1":
                payload = code.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                origin = self.headers.get("Origin")
                if origin and _allowed_origin(origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.end_headers()
                self.wfile.write(payload)
            else:
                self._send_json({"code": code, "name": "PB0 blink"})
            return
        self._serve_static(parsed.path)

    def _serve_static(self, path: str) -> None:
        if not STATIC.is_dir():
            self._send_json({"error": "static/ is not available yet"}, 404)
            return
        relative = unquote(path).lstrip("/") or "index.html"
        candidate = (STATIC / relative).resolve()
        try:
            candidate.relative_to(STATIC.resolve())
        except ValueError:
            self._send_json({"error": "invalid path"}, 400)
            return
        if not candidate.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        try:
            payload = candidate.read_bytes()
        except OSError as exc:
            self._send_json({"error": str(exc)}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(candidate))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        origin = self.headers.get("Origin")
        if origin and _allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_local_request():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/stop":
            self._send_json({"ok": True, "stopped": stop_active_run()})
            return
        if parsed.path != "/api/run":
            self._send_json({"ok": False, "log": "unknown API endpoint"}, 404)
            return

        content_length = self.headers.get("Content-Length")
        try:
            length = int(content_length or "0")
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._send_json({"ok": False, "log": "request body is too large"}, 413)
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json({"ok": False, "log": f"invalid JSON: {exc}"}, 400)
            return
        source, files, elf_bytes, firmware_error = _decode_run_firmware(request)
        if firmware_error:
            self._send_json({"ok": False, "log": firmware_error}, 400)
            return
        assert request is not None
        inputs = request.get("inputs") or {}
        if not isinstance(inputs, dict):
            self._send_json({"ok": False, "log": "inputs must be an object"}, 400)
            return
        if not _run_lock.acquire(blocking=False):
            self._send_json({"ok": False, "log": "another simulation is already running"}, 409)
            return
        try:
            self._send_json(_run_simulation(source, inputs, files=files, elf_bytes=elf_bytes))
        finally:
            _run_lock.release()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"STM32 lab backend listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_active_run()
        server.server_close()


if __name__ == "__main__":
    main()
