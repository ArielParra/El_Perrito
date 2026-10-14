#!/usr/bin/env python3
"""Punto de entrada rápido para El perrito."""

import sys
from pathlib import Path

# Asegurar que 'src' esté en el path cuando se ejecuta directamente el archivo
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from perrito.cli import main

if __name__ == "__main__":
    # Si se invoca sin subcomandos pero con argumentos antiguos como --out, redirigir a 'download'
    args = sys.argv[1:]
    if args and not any(sub in args[0] for sub in ["download", "ocr", "build", "info", "-h", "--help"]):
        args = ["download"] + args
    elif not args:
        args = ["--help"]
    sys.exit(main(args))
