#!/usr/bin/env bash
# build.sh — compile the vendored Uxn toolchain (uxnasm + uxncli) for THIS platform, then
# (optionally) reassemble paramgen.tal -> paramgen.rom.
#
# The emulator is per-platform C (~26KB); the ROM it runs is portable and byte-identical
# everywhere a Uxn emulator exists. Run this once per machine (dev box, CI runner, ...).
#   ./build.sh          -> bin/uxnasm, bin/uxncli
#   ./build.sh --rom    -> also re-assemble paramgen.tal -> paramgen.rom
set -eu
cd "$(dirname "$0")"
CC="${CC:-cc}"
mkdir -p bin
$CC -std=c89 -O2 -DNDEBUG -o bin/uxnasm src/uxnasm.c
$CC -std=c89 -O2 -DNDEBUG -o bin/uxncli \
    src/uxncli.c src/uxn.c src/devices/system.c src/devices/file.c src/devices/datetime.c
echo "built bin/uxnasm ($(wc -c <bin/uxnasm)b) bin/uxncli ($(wc -c <bin/uxncli)b)"
if [ "${1:-}" = --rom ]; then
  ./bin/uxnasm paramgen.tal paramgen.rom
fi
