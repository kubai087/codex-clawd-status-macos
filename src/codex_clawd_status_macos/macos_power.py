from __future__ import annotations

import ctypes
import sys
from typing import Callable


K_IO_MESSAGE_CAN_SYSTEM_SLEEP = 0xE0000270
K_IO_MESSAGE_SYSTEM_WILL_SLEEP = 0xE0000280
K_IO_MESSAGE_SYSTEM_HAS_POWERED_ON = 0xE0000300
K_IO_MESSAGE_SYSTEM_WILL_POWER_ON = 0xE0000320

IOKIT_PATH = "/System/Library/Frameworks/IOKit.framework/IOKit"
CORE_FOUNDATION_PATH = (
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)


def dispatch_power_message(
    message_type: int,
    notification_id: int,
    allow_power_change: Callable[[int], object],
    on_sleep: Callable[[], object],
    on_wake: Callable[[], object],
) -> None:
    if message_type == K_IO_MESSAGE_CAN_SYSTEM_SLEEP:
        allow_power_change(notification_id)
    elif message_type == K_IO_MESSAGE_SYSTEM_WILL_SLEEP:
        try:
            on_sleep()
        finally:
            allow_power_change(notification_id)
    elif message_type == K_IO_MESSAGE_SYSTEM_HAS_POWERED_ON:
        on_wake()


def run_power_monitor(
    on_sleep: Callable[[], object],
    on_wake: Callable[[], object],
) -> bool:
    if sys.platform != "darwin":
        return False

    try:
        io_kit = ctypes.CDLL(IOKIT_PATH)
        core_foundation = ctypes.CDLL(CORE_FOUNDATION_PATH)
    except OSError:
        return False

    callback_type = ctypes.CFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    io_kit.IORegisterForSystemPower.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        callback_type,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    io_kit.IORegisterForSystemPower.restype = ctypes.c_uint32
    io_kit.IONotificationPortGetRunLoopSource.argtypes = [ctypes.c_void_p]
    io_kit.IONotificationPortGetRunLoopSource.restype = ctypes.c_void_p
    io_kit.IOAllowPowerChange.argtypes = [ctypes.c_uint32, ctypes.c_ssize_t]
    io_kit.IOAllowPowerChange.restype = ctypes.c_int32
    io_kit.IODeregisterForSystemPower.argtypes = [
        ctypes.POINTER(ctypes.c_uint32)
    ]
    io_kit.IODeregisterForSystemPower.restype = ctypes.c_int32
    io_kit.IONotificationPortDestroy.argtypes = [ctypes.c_void_p]
    io_kit.IONotificationPortDestroy.restype = None
    io_kit.IOServiceClose.argtypes = [ctypes.c_uint32]
    io_kit.IOServiceClose.restype = ctypes.c_int32

    core_foundation.CFRunLoopGetCurrent.argtypes = []
    core_foundation.CFRunLoopGetCurrent.restype = ctypes.c_void_p
    core_foundation.CFRunLoopAddSource.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    core_foundation.CFRunLoopAddSource.restype = None
    core_foundation.CFRunLoopRun.argtypes = []
    core_foundation.CFRunLoopRun.restype = None

    notification_port = ctypes.c_void_p()
    notifier = ctypes.c_uint32()
    root_port = ctypes.c_uint32()

    def allow_power_change(notification_id: int) -> None:
        io_kit.IOAllowPowerChange(root_port.value, notification_id)

    @callback_type
    def power_callback(
        _refcon: int,
        _service: int,
        message_type: int,
        message_argument: int,
    ) -> None:
        notification_id = int(
            ctypes.cast(message_argument, ctypes.c_void_p).value or 0
        )
        try:
            dispatch_power_message(
                message_type,
                notification_id,
                allow_power_change,
                on_sleep,
                on_wake,
            )
        except Exception:
            # Exceptions cannot cross a ctypes callback boundary. Will-sleep is
            # still acknowledged by dispatch_power_message's finally block.
            pass

    root_port.value = io_kit.IORegisterForSystemPower(
        None,
        ctypes.byref(notification_port),
        power_callback,
        ctypes.byref(notifier),
    )
    if not root_port.value:
        if notification_port.value:
            io_kit.IONotificationPortDestroy(notification_port)
        return False

    try:
        source = io_kit.IONotificationPortGetRunLoopSource(notification_port)
        if not source:
            return False
        run_loop = core_foundation.CFRunLoopGetCurrent()
        common_modes = ctypes.c_void_p.in_dll(
            core_foundation, "kCFRunLoopCommonModes"
        )
        core_foundation.CFRunLoopAddSource(run_loop, source, common_modes)
        core_foundation.CFRunLoopRun()
        return True
    finally:
        io_kit.IODeregisterForSystemPower(ctypes.byref(notifier))
        io_kit.IONotificationPortDestroy(notification_port)
        io_kit.IOServiceClose(root_port.value)
