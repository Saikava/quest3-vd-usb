"""Prepare an offline patch of one exact UsbNcm.sys build. Never install it."""

import ctypes
import hashlib
import json
from pathlib import Path
import struct


SOURCE = Path(
    r"C:\WINDOWS\system32\DriverStore\FileRepository"
    r"\usbncm.inf_amd64_55ca763394be2e25\UsbNcm.sys"
)
SOURCE_SHA256 = "af7fe114f83d5fd1b2fac12d78057630a33dd6c72b16dfb7c82eb9e24e9d50c0"
DRIVER_VERSION = "10.0.26100.9444"
PDB_ID = "99D732371DE0F0B07BBE99F6A117C2F01"
OUTPUT = Path(__file__).resolve().parent

# Microsoft PDB: UsbNcm.pdb / 99D732371DE0F0B07BBE99F6A117C2F01.
# The count in r11d excludes the incoming datagram. SetNdp also writes a
# terminating null entry. Reserve both before copying the incoming datagram.
# These .text RVAs equal file offsets in this exact image.
PATCHES = (
    (0xA15A, "NTB16", bytes.fromhex("41 8d 43 01"), bytes.fromhex("41 8d 43 02")),
    (0xA2A6, "NTB32", bytes.fromhex("41 8d 43 01"), bytes.fromhex("41 8d 43 02")),
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def checksum(data):
    imagehlp = ctypes.WinDLL("imagehlp")
    function = imagehlp.CheckSumMappedFile
    function.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    )
    function.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(bytes(data))
    stored, calculated = ctypes.c_uint32(), ctypes.c_uint32()
    if not function(buffer, len(data), ctypes.byref(stored), ctypes.byref(calculated)):
        raise RuntimeError("CheckSumMappedFile failed")
    return stored.value, calculated.value


def write_new_or_identical(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"Refusing to overwrite a different existing file: {path}")
        return
    with path.open("xb") as stream:
        stream.write(data)


def main():
    original = SOURCE.read_bytes()
    if sha256(original) != SOURCE_SHA256:
        raise RuntimeError("Installed driver has a different SHA-256; this patch does not apply")
    stored, calculated = checksum(original)
    if stored != calculated:
        raise RuntimeError("Original PE checksum does not match")

    modified = bytearray(original)
    manifest = {
        "source": str(SOURCE),
        "version_from_device": DRIVER_VERSION,
        "source_sha256": SOURCE_SHA256,
        "pdb_id": PDB_ID,
        "patches": [],
        "state": "Offline copy only; not test-signed and not installed",
    }
    expected_code_offsets = set()
    for offset, kind, before, after in PATCHES:
        if original[offset:offset + len(before)] != before:
            raise RuntimeError(f"Unexpected instruction at {offset:#x}")
        modified[offset:offset + len(after)] = after
        expected_code_offsets.add(offset + 3)
        manifest["patches"].append({
            "format": kind,
            "instruction_file_offset_and_rva": hex(offset),
            "changed_byte_file_offset": hex(offset + 3),
            "before": before.hex(" "),
            "after": after.hex(" "),
            "meaning": "lea eax, [r11 + 1] -> lea eax, [r11 + 2]",
        })

    pe_offset = struct.unpack_from("<I", original, 0x3C)[0]
    checksum_offset = pe_offset + 24 + 64
    patched_checksum = checksum(modified)[1]
    struct.pack_into("<I", modified, checksum_offset, patched_checksum)
    if checksum(modified) != (patched_checksum, patched_checksum):
        raise RuntimeError("Patched PE checksum does not match")
    differences = {i for i, (a, b) in enumerate(zip(original, modified)) if a != b}
    checksum_offsets = set(range(checksum_offset, checksum_offset + 4))
    if differences - checksum_offsets != expected_code_offsets:
        raise RuntimeError("Unexpected binary changes")

    manifest.update({
        "patched_sha256": sha256(modified),
        "pe_checksum_file_offset": hex(checksum_offset),
        "original_pe_checksum": hex(stored),
        "patched_pe_checksum": hex(patched_checksum),
        "all_changed_file_offsets": [hex(i) for i in sorted(differences)],
    })
    write_new_or_identical(OUTPUT / "UsbNcm.original.sys", original)
    write_new_or_identical(OUTPUT / "UsbNcm.patched.sys", bytes(modified))
    write_new_or_identical(
        OUTPUT / "manifest.json",
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
