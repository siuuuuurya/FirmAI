# Fan Controller Demo (Hardware / Simulation Part)

Files
- sketches/fan_buggy/   firmware WITH 2 planted bugs (the agent should find them)
- sketches/fan_fixed/   corrected firmware
- spec.txt              what the firmware SHOULD do
- diagram.json          the virtual circuit (Arduino Uno, NTC sensor, 2 LEDs, 2 fault buttons)
- wokwi.toml            tells Wokwi which firmware to load
- scenarios/*.yaml      5 hand-written tests (later, your AI agent will generate these)
- build.sh / run_tests.sh   compile + run all tests

See the chat instructions for setup. Quick run:
  ./build.sh fan_buggy && ./run_tests.sh     # expect T02 and T05 to FAIL
  ./build.sh fan_fixed && ./run_tests.sh     # expect all PASS
