#!/usr/bin/env bash
# usage: ./build.sh fan_buggy   (or fan_fixed)
set -e
S=${1:-fan_buggy}
arduino-cli compile --fqbn arduino:avr:uno --output-dir build/$S sketches/$S
cp build/$S/$S.ino.hex build/firmware.hex
cp build/$S/$S.ino.elf build/firmware.elf
echo "Built $S -> build/firmware.hex"
