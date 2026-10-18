from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
from ctypes import wintypes


class CredentialError(RuntimeError):
    pass


_ORGANIZATION = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_ERROR_NOT_FOUND = 1168
_SECRET_TIMEOUT_SECONDS = 5


def target(organization: str) -> str:
    if not _ORGANIZATION.fullmatch(organization):
        raise CredentialError("invalid personal Azure DevOps organization")
    return f"tj-agents:personal-ado:{organization}"


def _secret_tool(
    arguments: list[str], value: str | None = None
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("secret-tool")
    if executable is None:
        raise CredentialError(
            "secret-tool is unavailable; install libsecret before using "
            "personal Azure work items"
        )
    try:
        return subprocess.run(
            [executable, *arguments],
            input=value,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SECRET_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise CredentialError(
            "secret-tool timed out while accessing the system credential store"
        ) from error
    except OSError as error:
        raise CredentialError(
            "secret-tool could not access the system credential store"
        ) from error


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _windows_api() -> ctypes.CDLL:
    if os.name != "nt":
        raise CredentialError("Windows Credential Manager is unavailable")
    try:
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    except (AttributeError, OSError) as error:
        raise CredentialError("Windows Credential Manager is unavailable") from error
    pointer = ctypes.POINTER(_Credential)
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(pointer),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def _windows_error(action: str) -> CredentialError:
    return CredentialError(
        f"Windows Credential Manager could not {action} "
        f"(error {ctypes.get_last_error()})"
    )


def _windows_get(name: str) -> str | None:
    api = _windows_api()
    credential = ctypes.POINTER(_Credential)()
    if not api.CredReadW(name, 1, 0, ctypes.byref(credential)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return None
        raise _windows_error("read the personal Azure token")
    try:
        size = credential.contents.CredentialBlobSize
        return (
            ctypes.string_at(credential.contents.CredentialBlob, size).decode(
                "utf-16-le"
            )
            if size
            else None
        )
    except UnicodeDecodeError as error:
        raise CredentialError(
            "Windows Credential Manager returned an invalid personal Azure token"
        ) from error
    finally:
        api.CredFree(credential)


def _windows_store(name: str, token: str) -> None:
    api = _windows_api()
    encoded = token.encode("utf-16-le")
    blob = (ctypes.c_byte * len(encoded)).from_buffer_copy(encoded)
    credential = _Credential(
        0,
        1,
        name,
        None,
        wintypes.FILETIME(),
        len(encoded),
        blob,
        2,
        0,
        None,
        None,
        "personal-ado",
    )
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise _windows_error("save the personal Azure token")


def _windows_delete(name: str) -> None:
    api = _windows_api()
    if not api.CredDeleteW(name, 1, 0):
        raise _windows_error("delete the personal Azure token")


def get_pat(organization: str) -> str:
    name = target(organization)
    if os.name == "nt":
        token = _windows_get(name)
    elif os.name == "posix":
        result = _secret_tool(["lookup", "service", "tj-agents", "target", name])
        if result.returncode == 0:
            token = result.stdout.rstrip("\r\n")
        elif result.returncode == 1:
            token = None
        else:
            raise CredentialError("secret-tool could not read the personal Azure token")
    else:
        raise CredentialError(
            "personal Azure work items support Windows and Linux credential stores"
        )
    if not token:
        raise CredentialError(
            "no personal Azure token is stored; run the personal work-item "
            "credential setup"
        )
    return token


def store_pat(organization: str, token: str) -> None:
    if not isinstance(token, str) or not token:
        raise CredentialError("personal Azure token cannot be empty")
    name = target(organization)
    if os.name == "nt":
        _windows_store(name, token)
    elif os.name == "posix":
        result = _secret_tool(
            [
                "store",
                "--label",
                "tj-agents personal Azure DevOps",
                "service",
                "tj-agents",
                "target",
                name,
            ],
            token,
        )
        if result.returncode:
            raise CredentialError("secret-tool could not save the personal Azure token")
    else:
        raise CredentialError(
            "personal Azure work items support Windows and Linux credential stores"
        )


def delete_pat(organization: str) -> None:
    name = target(organization)
    if os.name == "nt":
        _windows_delete(name)
    elif os.name == "posix":
        result = _secret_tool(["clear", "service", "tj-agents", "target", name])
        if result.returncode:
            raise CredentialError(
                "secret-tool could not delete the personal Azure token"
            )
    else:
        raise CredentialError(
            "personal Azure work items support Windows and Linux credential stores"
        )
