"""Apply the reviewed two-byte NTB fix to the updated 10.0.26100.9711 image."""
import importlib.util
from pathlib import Path

directory = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("patch_usbncm", directory.parent / "patch_usbncm.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)
patch.SOURCE = Path(
    r"C:\Windows\System32\DriverStore\FileRepository"
    r"\usbncm.inf_amd64_70d658347632acad\UsbNcm.sys"
)
patch.SOURCE_SHA256 = "f34630163c88948e6fb272bd60f84d588ec2907cf228faa52ff698f3df0f0b79"
patch.DRIVER_VERSION = "10.0.26100.9711"
patch.PDB_ID = "EBC3AC7CFC0377E1EFED4DD78D50716D1"
patch.OUTPUT = directory
patch.PATCHES = (
    (0xA23E, "NTB16", bytes.fromhex("41 8d 43 01"), bytes.fromhex("41 8d 43 02")),
    (0xA38A, "NTB32", bytes.fromhex("41 8d 43 01"), bytes.fromhex("41 8d 43 02")),
)
patch.main()
