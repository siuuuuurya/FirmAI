#!/usr/bin/env bash
# Runs every scenario against the currently built firmware and prints PASS/FAIL.
# Needs: wokwi-cli installed and WOKWI_CLI_TOKEN set.
pass=0; fail=0
for f in scenarios/*.test.yaml; do
  if wokwi-cli . --scenario "$f" --timeout 8000 --serial-log-file "build/$(basename $f).log" >/dev/null 2>&1; then
    echo "PASS  $f"; pass=$((pass+1))
  else
    echo "FAIL  $f   (see build/$(basename $f).log)"; fail=$((fail+1))
  fi
done
echo "----  $pass passed, $fail failed"
