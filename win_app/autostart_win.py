"""Start at logon, owned by the app: the scheduled task is the setting, so there is no config
field to disagree with it.

A scheduled task rather than a Run key or a Startup shortcut: Beamer.exe is manifested
requireAdministrator, and Explorer starts such an exe from either of those with a UAC prompt on
every logon. A task with the highest run level starts it elevated and silently. The app is
already elevated when it writes the task, so no prompt appears here either.

Registered from XML, not `schtasks /create /sc onlogon`: that form cannot set a working directory
and gives every task a 72-hour execution limit, which would stop Beamer three days after logon.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from typing import Callable, Optional
from xml.sax.saxutils import escape

TASK_NAME = "Beamer"
CREATE_NO_WINDOW = 0x08000000
NAME_SAM_COMPATIBLE = 2

Runner = Callable[[list], "subprocess.CompletedProcess"]


def _run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)


def current_user() -> str:
    """DOMAIN\\user as Windows maps it, not USERDOMAIN, which reads WORKGROUP in some sessions and
    maps to no account."""
    size = ctypes.c_ulong(0)
    secur32 = ctypes.windll.secur32
    secur32.GetUserNameExW(NAME_SAM_COMPATIBLE, None, ctypes.byref(size))
    buffer = ctypes.create_unicode_buffer(size.value)
    if not secur32.GetUserNameExW(NAME_SAM_COMPATIBLE, buffer, ctypes.byref(size)):
        raise OSError("could not read the signed-in account name")
    return buffer.value


def installed_exe() -> Optional[str]:
    """The exe a task can start, or None when running from source, where there is none."""
    return sys.executable if getattr(sys, "frozen", False) else None


def task_xml(exe: str, user: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>--hidden</Arguments>
      <WorkingDirectory>{escape(os.path.dirname(exe))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def is_enabled(run: Runner = _run) -> bool:
    return run(["schtasks", "/query", "/tn", TASK_NAME]).returncode == 0


def set_enabled(enabled: bool, exe: str, user: Optional[str] = None, run: Runner = _run) -> None:
    """Raises OSError with schtasks' own words when Windows refuses."""
    if not enabled:
        if not is_enabled(run):
            return
        result = run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
    else:
        fd, path = tempfile.mkstemp(suffix=".xml")
        try:
            with os.fdopen(fd, "w", encoding="utf-16") as handle:
                handle.write(task_xml(exe, user or current_user()))
            result = run(["schtasks", "/create", "/tn", TASK_NAME, "/xml", path, "/f"])
        finally:
            os.unlink(path)
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout or "schtasks failed").strip())
