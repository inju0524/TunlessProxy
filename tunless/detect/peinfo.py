"""PE 文件信息探测（架构 / 子系统 / .NET / 是否需要提权 / 文件描述）。

用 pefile；任何一项失败都只影响该项，不影响整体解析。
"""

from __future__ import annotations

import os
from typing import Any

MACHINE_MAP = {
    0x014C: "x86",
    0x8664: "x64",
    0xAA64: "arm64",
    0x01C0: "arm",
    0x01C4: "armv7",
    0x0200: "ia64",
}

SUBSYSTEM_MAP = {
    2: "gui",
    3: "cui",
}

RT_MANIFEST = 24


def _decode_manifest(raw: bytes) -> str:
    """清单可能是 UTF-8，也可能是带 BOM 的 UTF-16。"""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16", "replace") if b"\x00" in raw[:64] else raw.decode(
            "latin-1", "replace"
        )


def _read_manifest(pe: Any) -> str:
    """从资源段里取 RT_MANIFEST 内容。"""
    try:
        entries = pe.DIRECTORY_ENTRY_RESOURCE.entries
    except AttributeError:
        return ""
    for type_entry in entries:
        type_id = type_entry.id
        if type_id is None and type_entry.name is not None:
            type_id = getattr(type_entry.name, "struct", None)
        if type_id != RT_MANIFEST:
            continue
        for name_entry in getattr(type_entry, "directory", None).entries or []:
            for lang_entry in getattr(name_entry, "directory", None).entries or []:
                data = getattr(lang_entry, "data", None)
                if data is None:
                    continue
                try:
                    raw = pe.get_data(data.struct.OffsetToData, data.struct.Size)
                    return _decode_manifest(raw)
                except Exception:
                    continue
    return ""


def _description(pe: Any) -> str:
    try:
        for file_info in (pe.FileInfo or []):
            for entry in file_info:
                if getattr(entry, "Key", b"") != b"StringFileInfo":
                    continue
                for table in entry.StringTable:
                    for key, value in table.entries.items():
                        if key in (b"FileDescription", b"ProductName"):
                            text = value.decode("utf-8", "replace").strip()
                            if text:
                                return text
    except Exception:
        pass
    return ""


def analyze(path: str) -> dict[str, Any]:
    """返回 {arch, subsystem, dotnet, requires_elevation, description, is_pe}。"""
    result: dict[str, Any] = {
        "arch": "unknown",
        "subsystem": "unknown",
        "dotnet": False,
        "requires_elevation": False,
        "description": "",
        "is_pe": False,
    }
    if not path or not os.path.isfile(path):
        return result

    try:
        import pefile  # type: ignore
    except ImportError:
        return result

    try:
        pe = pefile.PE(path, fast_load=True)
    except Exception:
        return result

    try:
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR"],
            ]
        )
    except Exception:
        pass

    try:
        result["is_pe"] = True
        machine = pe.FILE_HEADER.Machine
        result["arch"] = MACHINE_MAP.get(machine, f"0x{machine:04x}")
        subsystem = pe.OPTIONAL_HEADER.Subsystem
        result["subsystem"] = SUBSYSTEM_MAP.get(subsystem, f"subsystem-{subsystem}")

        try:
            com = pe.OPTIONAL_HEADER.DATA_DIRECTORY[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR"]
            ]
            result["dotnet"] = bool(com.VirtualAddress)
        except Exception:
            pass

        manifest = _read_manifest(pe)
        if manifest:
            result["requires_elevation"] = "requireAdministrator" in manifest
        result["description"] = _description(pe)
    finally:
        try:
            pe.close()
        except Exception:
            pass

    return result


def arch_of_launcher() -> str:
    """当前 Python 解释器的位数，用于提示架构不匹配。"""
    import struct

    return "x64" if struct.calcsize("P") * 8 == 64 else "x86"
