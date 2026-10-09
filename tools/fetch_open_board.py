#!/usr/bin/env python3
"""Acquire third-party board data locally; review its terms before reuse."""
from pathlib import Path
import hashlib
import urllib.request
import zipfile
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "references/open-board"
FILES = {
 "EasyEDA_F103ZET6.Pcb.api.json": "https://lceda.cn/api/documents/907173c2f4454257912bca00dd03fb97",
 "Gerber_F103ZET6.Pcb.zip": "https://image.lceda.cn/attachments/2020/10/Prt1H39DksJuqZcLZs3Q1P6nza6MfBJSmyEBZpXE.zip",
}
def main():
 print("Third-party board: PE.JADO / GPL label with platform reuse notice. Review references/OPEN-BOARD-SOURCE.md before use.")
 DEST.mkdir(parents=True, exist_ok=True)
 for name, url in FILES.items():
  payload = urllib.request.urlopen(url, timeout=60).read()
  if name.endswith(".zip") and hashlib.md5(payload).hexdigest() != "8d81f1cf507da2b0e486c2140381c648":
   raise ValueError("Gerber checksum differs from the verified attachment")
  (DEST/name).write_bytes(payload)
 with zipfile.ZipFile(DEST/"Gerber_F103ZET6.Pcb.zip") as archive:
  for entry in archive.infolist():
   # Only expected fabrication layers, never arbitrary zip paths.
   if entry.is_dir(): continue
   name = Path(entry.filename).name
   if name.startswith("Gerber_") and name.endswith((".GKO", ".GTL", ".GBL", ".GTO", ".GBO", ".GTS", ".GBS", ".GTP", ".GBP", ".DRL")):
    target = DEST/"gerber"/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(archive.read(entry))
 subprocess.run([sys.executable,str(ROOT/"tools/import_open_board.py"),"--summary"],check=True)
if __name__ == "__main__": main()
