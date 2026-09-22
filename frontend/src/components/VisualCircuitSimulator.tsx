import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Fan,
  FileCode,
  Gauge,
  Info,
  Layers,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Sliders,
  Sparkles,
  Terminal,
  Thermometer,
  Tv,
  XCircle,
  Zap,
} from 'lucide-react';
import type { AnalysisResult, Firmware, TestResult, TestRun, TestSuite } from '../types';

interface VisualCircuitSimulatorProps {
  firmware: Firmware | null;
  analysis: AnalysisResult | null;
  currentRun: TestRun | null;
  currentSuite: TestSuite | null;
  onNavigateToFailures?: () => void;
  onNavigateToTestGen?: () => void;
}

// Built-in reference sketches for instant live comparison
const FAN_BUGGY_CODE = `// Cooling fan controller (BUGGY VERSION - contains 2 planted bugs)
// Sensor: NTC thermistor on A0 | Fan LED: pin 9 | Error LED: pin 8

const int NTC_PIN     = A0;
const int FAN_PIN     = 9;
const int ERR_LED_PIN = 8;
const float BETA      = 3950.0;   // thermistor constant
const int THRESHOLD_C = 30;       // fan turns on at this temperature

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(ERR_LED_PIN, OUTPUT);
}

void loop() {
  int adc = analogRead(NTC_PIN);      // 0..1023
  bool fanOn = false;
  bool error = false;
  int tempC = 0;

  if (adc == 0) {                     // BUG 2: does not check adc == 1023
    error = true;
  } else {
    float t = 1.0 / (log(1.0 / (1023.0 / adc - 1.0)) / BETA + 1.0 / 298.15) - 273.15;
    tempC = (int)(t + 0.5);           // round to nearest degree
    if (tempC > THRESHOLD_C) {        // BUG 1: should be >= (spec: ON at 30C)
      fanOn = true;
    }
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(ERR_LED_PIN, error ? HIGH : LOW);

  Serial.print("TEMP=");
  Serial.print(tempC);
  Serial.print(" FAN=");
  Serial.print(fanOn ? "ON" : "OFF");
  Serial.print(" STATE=");
  Serial.println(error ? "ERROR" : "NORMAL");

  delay(500);
}`;

const FAN_FIXED_CODE = `// Cooling fan controller (FIXED VERSION)
// Sensor: NTC thermistor on A0 | Fan LED: pin 9 | Error LED: pin 8

const int NTC_PIN     = A0;
const int FAN_PIN     = 9;
const int ERR_LED_PIN = 8;
const float BETA      = 3950.0;   // thermistor constant
const int THRESHOLD_C = 30;       // fan turns on at this temperature

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(ERR_LED_PIN, OUTPUT);
}

void loop() {
  int adc = analogRead(NTC_PIN);      // 0..1023
  bool fanOn = false;
  bool error = false;
  int tempC = 0;

  if (adc <= 0 || adc >= 1023) {      // sensor fault: shorted (0) or open (1023)
    error = true;
  } else {
    float t = 1.0 / (log(1.0 / (1023.0 / adc - 1.0)) / BETA + 1.0 / 298.15) - 273.15;
    tempC = (int)(t + 0.5);           // round to nearest degree
    if (tempC >= THRESHOLD_C) {       // spec: ON at 30C and above
      fanOn = true;
    }
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(ERR_LED_PIN, error ? HIGH : LOW);

  Serial.print("TEMP=");
  Serial.print(tempC);
  Serial.print(" FAN=");
  Serial.print(fanOn ? "ON" : "OFF");
  Serial.print(" STATE=");
  Serial.println(error ? "ERROR" : "NORMAL");

  delay(500);
}`;

export const VisualCircuitSimulator: React.FC<VisualCircuitSimulatorProps> = ({
  firmware,
  analysis,
  currentRun,
  currentSuite,
  onNavigateToFailures,
  onNavigateToTestGen,
}) => {
  // Mode selection: 'interactive' (live sliders) vs 'replay' (test cases from run)
  const [mode, setMode] = useState<'interactive' | 'replay'>(
    currentRun && currentRun.results.length > 0 ? 'replay' : 'interactive'
  );

  // Firmware variant selector: 'active' (user uploaded/selected), 'buggy_sample', 'fixed_sample'
  const [firmwareVariant, setFirmwareVariant] = useState<'active' | 'buggy_sample' | 'fixed_sample'>('active');

  // Interactive controls state
  const [temperature, setTemperature] = useState<number>(25.0);
  const [faultShort, setFaultShort] = useState<boolean>(false);
  const [faultOpen, setFaultOpen] = useState<boolean>(false);

  // Auto-play test suite state
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [isPlayingSuite, setIsPlayingSuite] = useState<boolean>(false);
  const [playSpeedMs, setPlaySpeedMs] = useState<number>(2200);

  // Serial console state
  const [serialLogs, setSerialLogs] = useState<string[]>([
    '[BOOT] ATmega328P initialized @ 16 MHz',
    '[UART] 9600 baud serial connection open',
    '[HARDWARE] Pins configured: FAN_PIN=9, ERR_LED=8, TEMP_PIN=A0',
  ]);
  const consoleEndRef = useRef<HTMLDivElement>(null);

  // Logic analyzer waveform history
  const [waveformHistory, setWaveformHistory] = useState<Array<{ fan: number; err: number; voltage: number }>>([]);

  // Determine active source code
  const activeSource = useMemo(() => {
    if (firmwareVariant === 'buggy_sample') return FAN_BUGGY_CODE;
    if (firmwareVariant === 'fixed_sample') return FAN_FIXED_CODE;
    return firmware?.source_code || FAN_BUGGY_CODE;
  }, [firmwareVariant, firmware]);

  // Analyze sketch characteristics dynamically
  const sketchInfo = useMemo(() => {
    const src = activeSource;
    const isBetaNtc = src.includes('BETA') || src.includes('log(1.0 / (1023.0');
    const isLinear = src.includes('TEMP_LSB_C') || src.includes('0.25');

    // Pin assignments
    const fanPinMatch = src.match(/(?:FAN_PIN|fanPin|PIN_FAN)\s*=\s*(\d+)/);
    const errPinMatch = src.match(/(?:ERR_LED_PIN|errLedPin|PIN_ERR)\s*=\s*(\d+)/);
    const tempPinMatch = src.match(/(?:TEMP_SENSOR_PIN|NTC_PIN|tempPin)\s*=\s*(?:A(\d)|(\d+))/);

    const fanPin = fanPinMatch ? parseInt(fanPinMatch[1], 10) : 9;
    const errPin = errPinMatch ? parseInt(errPinMatch[1], 10) : 8;
    const tempPin = 'A0';

    // Condition checks
    const hasStrictInequalityBug = />\s*THRESHOLD_C|>=\s*35|> \s*30(?:\.0)?/.test(src);
    const hasOpenFaultCheck = src.includes('1023') && (src.includes('>= 1023') || src.includes('>= 1010') || src.includes('== 1023') || src.includes('|| adc >='));

    return {
      isBetaNtc,
      isLinear,
      fanPin,
      errPin,
      tempPin,
      hasStrictInequalityBug,
      hasOpenFaultCheck,
      filename:
        firmwareVariant === 'buggy_sample'
          ? 'fan_buggy.ino (Planted Bugs)'
          : firmwareVariant === 'fixed_sample'
          ? 'fan_fixed.ino (Golden Reference)'
          : firmware?.filename || 'user_firmware.ino',
    };
  }, [activeSource, firmwareVariant, firmware]);

  // Physical conversion: Temperature (°C) -> ADC count (0..1023)
  const calculateAdc = (tC: number, isShort: boolean, isOpen: boolean): { adc: number; voltage: number } => {
    if (isShort) return { adc: 0, voltage: 0.0 };
    if (isOpen) return { adc: 1023, voltage: 5.0 };

    if (sketchInfo.isBetaNtc) {
      // Beta-parameter inverse formula for B=3950, T0=25°C (298.15K), R0=10k, Pullup=10k:
      // ADC = 1023 / (1 + exp(B * (1/T_K - 1/T0_K)))
      const tk = tC + 273.15;
      if (tk <= 0) return { adc: 0, voltage: 0.0 };
      const beta = 3950.0;
      const t0 = 298.15;
      try {
        const ratio = Math.exp(-beta * (1.0 / tk - 1.0 / t0));
        const raw = 1023.0 / (1.0 + ratio);
        const adc = Math.max(0, Math.min(1023, Math.round(raw)));
        const voltage = (adc * 5.0) / 1023.0;
        return { adc, voltage };
      } catch {
        return { adc: 512, voltage: 2.5 };
      }
    } else {
      // Linear sensor: T = raw * 0.25 - 50.0 => raw = (T + 50) / 0.25
      const raw = (tC + 50.0) / 0.25;
      const adc = Math.max(0, Math.min(1023, Math.round(raw)));
      const voltage = (adc * 5.0) / 1023.0;
      return { adc, voltage };
    }
  };

  // Evaluate firmware control logic for current stimulus
  const simulatedHardware = useMemo(() => {
    const { adc, voltage } = calculateAdc(temperature, faultShort, faultOpen);

    let isFault = false;
    let fanOn = false;
    let tempCalculated = temperature;
    let defectAlert: string | null = null;

    if (sketchInfo.isBetaNtc) {
      // Firmware logic for fan_buggy vs fan_fixed
      if (adc === 0) {
        isFault = true;
      } else if (adc >= 1023 && !sketchInfo.hasOpenFaultCheck) {
        // Buggy sketch fails to flag open circuit!
        isFault = false;
        defectAlert = 'Defect 2 Triggered: ADC is 1023 (Open Circuit), but firmware does NOT check adc >= 1023! Error LED is not set.';
      } else if (adc >= 1023 && sketchInfo.hasOpenFaultCheck) {
        isFault = true;
      } else {
        // Compute temp in integer degrees like sketch: tempC = (int)(t + 0.5)
        const t = 1.0 / (Math.log(1.0 / (1023.0 / adc - 1.0)) / 3950.0 + 1.0 / 298.15) - 273.15;
        tempCalculated = Math.round(t);

        if (sketchInfo.hasStrictInequalityBug) {
          // Buggy: tempC > 30
          fanOn = tempCalculated > 30;
          if (tempCalculated === 30) {
            defectAlert = 'Defect 1 Triggered: Temperature is 30°C. Spec requires Fan=ON, but firmware uses strict inequality (tempC > 30), leaving Fan=OFF!';
          }
        } else {
          // Fixed: tempC >= 30
          fanOn = tempCalculated >= 30;
        }
      }
    } else {
      // Linear temperature controller logic
      if (adc <= 10 || adc >= 1013) {
        isFault = true;
      } else {
        if (temperature >= 35.0) {
          fanOn = true;
        } else if (temperature >= 30.0 && !sketchInfo.hasStrictInequalityBug) {
          fanOn = true;
        } else if (temperature === 30.0 && sketchInfo.hasStrictInequalityBug) {
          fanOn = false;
          defectAlert = 'Boundary Defect: Temperature is 30°C. Spec expects cooling fan active, but condition failed.';
        }
      }
    }

    if (isFault) {
      fanOn = false;
    }

    const state = isFault ? 'ERROR' : fanOn ? 'COOLING' : 'NORMAL';

    return {
      adc,
      voltage,
      tempCalculated,
      fanOn,
      errorLed: isFault,
      state,
      defectAlert,
      fanPinState: fanOn ? 1 : 0,
      errPinState: isFault ? 1 : 0,
    };
  }, [temperature, faultShort, faultOpen, sketchInfo]);

  // Selected test result from test suite run (when in replay mode)
  const activeTestResult: TestResult | null = useMemo(() => {
    if (!currentRun || currentRun.results.length === 0) return null;
    if (selectedResultId) {
      return currentRun.results.find(r => r.id === selectedResultId) || currentRun.results[0];
    }
    return currentRun.results[0];
  }, [currentRun, selectedResultId]);

  // Synchronize when test result changes in Replay mode
  useEffect(() => {
    if (mode === 'replay' && activeTestResult) {
      const stim = activeTestResult.stimulus;
      const ev = stim?.events?.[0];
      if (ev) {
        if (ev.unit === 'C' || ev.channel === 'temperature') {
          setTemperature(ev.value);
          setFaultShort(false);
          setFaultOpen(false);
        } else if (ev.value === 0) {
          setFaultShort(true);
          setFaultOpen(false);
          setTemperature(0);
        } else if (ev.value >= 1023) {
          setFaultShort(false);
          setFaultOpen(true);
          setTemperature(80);
        }
      }
    }
  }, [mode, activeTestResult]);

  // Add serial log entry when hardware state updates
  useEffect(() => {
    const newLog = `TEMP=${simulatedHardware.tempCalculated} FAN=${
      simulatedHardware.fanOn ? 'ON' : 'OFF'
    } STATE=${simulatedHardware.state} [A0=${simulatedHardware.adc} | ${simulatedHardware.voltage.toFixed(2)}V]`;
    setSerialLogs(prev => [...prev.slice(-40), newLog]);

    setWaveformHistory(prev => [
      ...prev.slice(-25),
      {
        fan: simulatedHardware.fanOn ? 1 : 0,
        err: simulatedHardware.errorLed ? 1 : 0,
        voltage: simulatedHardware.voltage,
      },
    ]);
  }, [simulatedHardware.adc, simulatedHardware.fanOn, simulatedHardware.errorLed, simulatedHardware.state]);

  // Auto-scroll serial terminal
  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [serialLogs]);

  // Auto-play through test cases in replay mode
  useEffect(() => {
    if (!isPlayingSuite || !currentRun || currentRun.results.length === 0) return;

    const results = currentRun.results;
    const interval = setInterval(() => {
      setSelectedResultId(prev => {
        const currIdx = results.findIndex(r => r.id === prev);
        const nextIdx = (currIdx + 1) % results.length;
        return results[nextIdx].id;
      });
    }, playSpeedMs);

    return () => clearInterval(interval);
  }, [isPlayingSuite, currentRun, playSpeedMs]);

  // Quick preset helper
  const handleApplyPreset = (tC: number, isShort = false, isOpen = false) => {
    setMode('interactive');
    setTemperature(tC);
    setFaultShort(isShort);
    setFaultOpen(isOpen);
  };

  // Reset simulator
  const handleResetMcu = () => {
    setTemperature(25.0);
    setFaultShort(false);
    setFaultOpen(false);
    setSerialLogs(prev => [
      ...prev,
      '----------------------------------------',
      '[RESET] Hardware RESET button pressed on Arduino Uno',
      '[BOOT] Resetting registers: PIN 9=LOW, PIN 8=LOW, A0 settled',
    ]);
  };

  return (
    <div className="space-y-8 animate-fadeIn pb-12">
      {/* Top Banner & Control Bar */}
      <div className="glass-panel p-6 rounded-2xl border border-sky-500/20 bg-gradient-to-r from-sky-950/40 via-slate-900/60 to-indigo-950/30 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30 flex items-center gap-1.5">
              <Tv className="w-3.5 h-3.5 text-sky-400" />
              Interactive Hardware Simulator
            </span>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
              Target MCU: ATmega328P @ 16 MHz
            </span>
            {simulatedHardware.defectAlert && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse flex items-center gap-1">
                <AlertTriangle className="w-3 h-3 text-rose-400" />
                Defect Tripped
              </span>
            )}
          </div>

          <h2 className="text-2xl font-extrabold text-white tracking-tight">
            Virtual Circuit Bench for <span className="text-sky-400 font-mono">{sketchInfo.filename}</span>
          </h2>
          <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
            Real-time visual simulation of Arduino Uno Rev3, NTC thermistor transfer curve, rotating cooling fan actuator, and fault pushbuttons matching physical Wokwi / hardware behavior.
          </p>
        </div>

        {/* Mode & Firmware Selectors */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 shrink-0">
          {/* Mode Switcher */}
          <div className="flex rounded-xl bg-slate-900/90 p-1 border border-slate-700/80">
            <button
              onClick={() => setMode('interactive')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                mode === 'interactive'
                  ? 'bg-sky-500 text-white shadow-md shadow-sky-500/25'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Sliders className="w-3.5 h-3.5" />
              Live Playground
            </button>
            <button
              onClick={() => setMode('replay')}
              disabled={!currentRun || currentRun.results.length === 0}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                mode === 'replay'
                  ? 'bg-sky-500 text-white shadow-md shadow-sky-500/25'
                  : 'text-slate-400 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              Test Suite Replay
            </button>
          </div>

          {/* Firmware Baseline Switcher */}
          <div className="flex items-center gap-2">
            <select
              value={firmwareVariant}
              onChange={e => setFirmwareVariant(e.target.value as any)}
              className="px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs font-mono text-sky-300 focus:outline-none focus:border-sky-500"
            >
              <option value="active">Active: {firmware?.filename || 'User Firmware'}</option>
              <option value="buggy_sample">fan_buggy.ino (Buggy Baseline)</option>
              <option value="fixed_sample">fan_fixed.ino (Golden Reference)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Test Case Replay Selector Bar (When in Replay Mode) */}
      {mode === 'replay' && currentRun && currentRun.results.length > 0 && (
        <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Synthesized Test Scenarios ({currentRun.results.length})
              </span>
              <span className="font-mono text-xs text-sky-400">
                • Current: {activeTestResult?.test_id} ({activeTestResult?.name})
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setIsPlayingSuite(!isPlayingSuite)}
                className={`flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-bold border transition-all ${
                  isPlayingSuite
                    ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                    : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 hover:bg-emerald-500/30'
                }`}
              >
                {isPlayingSuite ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                {isPlayingSuite ? 'Pause Auto-Play' : 'Auto-Play All Tests'}
              </button>

              <select
                value={playSpeedMs}
                onChange={e => setPlaySpeedMs(Number(e.target.value))}
                className="px-2 py-1 rounded-lg bg-slate-900 border border-slate-700 text-[11px] text-slate-300 font-mono"
              >
                <option value={3000}>Speed: 0.5x (3s)</option>
                <option value={2000}>Speed: 1.0x (2s)</option>
                <option value={1000}>Speed: 2.0x (1s)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
            {currentRun.results.map(r => {
              const isSelected = activeTestResult?.id === r.id;
              const isPass = r.status === 'PASS';

              return (
                <button
                  key={r.id}
                  onClick={() => {
                    setIsPlayingSuite(false);
                    setSelectedResultId(r.id);
                  }}
                  className={`p-2.5 rounded-xl border text-left transition-all ${
                    isSelected
                      ? isPass
                        ? 'bg-emerald-500/15 border-emerald-500 shadow-md shadow-emerald-500/15'
                        : 'bg-rose-500/15 border-rose-500 shadow-md shadow-rose-500/15'
                      : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px] mb-1">
                    <span className="font-mono font-bold text-slate-200">{r.test_id}</span>
                    <span className={`font-bold flex items-center gap-1 ${isPass ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isPass ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                      {r.status}
                    </span>
                  </div>
                  <div className="text-[11px] font-semibold text-slate-300 truncate">{r.name}</div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Main Simulation Arena: 2-Column Split Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT / CENTER: Virtual Hardware Bench (Arduino, Fan, LEDs, Wiring) */}
        <div className="lg:col-span-8 space-y-6">
          <div className="glass-panel p-6 rounded-2xl border border-slate-800 relative overflow-hidden bg-gradient-to-b from-slate-900/80 via-slate-950 to-slate-950">
            {/* Header / Circuit Status Badges */}
            <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-slate-800">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-xs font-bold text-slate-200">5.0V VCC RAIL ACTIVE</span>
                </div>
                <span className="text-xs text-slate-500 font-mono">•</span>
                <span className="text-xs font-mono text-slate-400">
                  MCU VIRTUAL CLOCK: <strong className="text-sky-400">16.00 MHz</strong>
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleResetMcu}
                  title="Press physical Arduino RESET button"
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold border border-slate-700 transition-all"
                >
                  <RotateCcw className="w-3 h-3 text-amber-400" />
                  Reset Board
                </button>
              </div>
            </div>

            {/* Circuit Bench Visual Layout */}
            <div className="relative py-6 px-2 sm:px-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
                {/* 1. Arduino Uno Rev3 Board Visual Representation */}
                <div className="relative bg-[#008184] rounded-2xl p-4 shadow-2xl border-2 border-[#00979d] select-none text-white font-mono min-h-[380px] flex flex-col justify-between">
                  {/* Silk Screen Branding & Markings */}
                  <div className="flex justify-between items-start border-b border-white/20 pb-2">
                    <div>
                      <div className="text-xs font-black tracking-widest text-white/90">ARDUINO</div>
                      <div className="text-[10px] text-white/70">UNO R3 • VIRTUAL MCU</div>
                    </div>
                    <div className="text-right">
                      <div className="text-[9px] text-white/60">MADE IN ITALY</div>
                      <div className="text-[9px] text-white/80 font-bold">ATmega328P</div>
                    </div>
                  </div>

                  {/* Top Digital Pin Header */}
                  <div className="my-2 bg-slate-900/90 rounded-lg p-1.5 border border-white/20">
                    <div className="text-[8px] text-sky-200 font-bold text-center mb-1">
                      DIGITAL PINS (PWM ~)
                    </div>
                    <div className="grid grid-cols-10 gap-1 text-center text-[9px]">
                      {/* D13 */}
                      <div className="p-1 rounded bg-slate-800 text-slate-400">D13</div>
                      {/* D12 */}
                      <div className="p-1 rounded bg-slate-800 text-slate-400">D12</div>
                      {/* D11 */}
                      <div className="p-1 rounded bg-slate-800 text-slate-400">D11</div>
                      {/* D10 */}
                      <div className="p-1 rounded bg-slate-800 text-slate-400">D10</div>
                      {/* D9 - Fan Pin */}
                      <div
                        className={`p-1 rounded font-bold transition-all ${
                          simulatedHardware.fanPinState === 1
                            ? 'bg-cyan-500 text-white led-glow-cyan font-black scale-105'
                            : 'bg-slate-800 text-cyan-300'
                        }`}
                      >
                        ~D9
                        <div className="text-[7px]">FAN</div>
                      </div>
                      {/* D8 - Error Pin */}
                      <div
                        className={`p-1 rounded font-bold transition-all ${
                          simulatedHardware.errPinState === 1
                            ? 'bg-rose-500 text-white led-glow-red laser-alert font-black scale-105'
                            : 'bg-slate-800 text-rose-300'
                        }`}
                      >
                        D8
                        <div className="text-[7px]">ERR</div>
                      </div>
                      {/* D7 */}
                      <div className="p-1 rounded bg-slate-800 text-slate-400">D7</div>
                      {/* D6 */}
                      <div className="p-1 rounded bg-slate-800 text-slate-400">D6</div>
                      {/* D5 */}
                      <div className="p-1 rounded bg-slate-800 text-slate-400">D5</div>
                      {/* GND */}
                      <div className="p-1 rounded bg-slate-800 text-emerald-400 font-bold">GND</div>
                    </div>
                  </div>

                  {/* Microcontroller ATmega328P DIP Chip & Status LEDs */}
                  <div className="my-3 flex items-center justify-between gap-4 px-2">
                    {/* USB-B connector simulation */}
                    <div className="w-12 h-14 bg-slate-300 rounded-sm border-2 border-slate-400 flex items-center justify-center shadow-inner">
                      <span className="text-[8px] text-slate-700 font-bold rotate-90">USB-B</span>
                    </div>

                    {/* DIP-28 Microcontroller IC */}
                    <div className="flex-1 bg-slate-900 border border-slate-700 rounded-md py-2 px-3 shadow-lg relative flex items-center justify-between">
                      <div className="w-2 h-2 rounded-full border border-slate-600 bg-slate-800 absolute -top-1 left-2" />
                      <div className="space-y-0.5">
                        <div className="text-[10px] font-bold text-slate-200 tracking-wider">ATMEGA328P-PU</div>
                        <div className="text-[8px] text-slate-400">16MHz • 32KB FLASH • AVR</div>
                      </div>
                      <div className="text-[9px] font-mono font-bold text-sky-400">
                        {simulatedHardware.state}
                      </div>
                    </div>

                    {/* Power & TX/RX LEDs */}
                    <div className="flex flex-col gap-1.5 items-center">
                      <div className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 led-glow-green" />
                        <span className="text-[8px] text-white/80">ON</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span
                          className={`w-2 h-2 rounded-full transition-all ${
                            simulatedHardware.fanPinState === 1
                              ? 'bg-amber-400 led-glow-amber'
                              : 'bg-slate-700'
                          }`}
                        />
                        <span className="text-[8px] text-white/80">TX</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span
                          className={`w-2 h-2 rounded-full transition-all ${
                            simulatedHardware.fanPinState === 1
                              ? 'bg-amber-400 led-glow-amber'
                              : 'bg-slate-700'
                          }`}
                        />
                        <span className="text-[8px] text-white/80">RX</span>
                      </div>
                    </div>
                  </div>

                  {/* Bottom Analog & Power Header */}
                  <div className="mt-2 bg-slate-900/90 rounded-lg p-1.5 border border-white/20">
                    <div className="text-[8px] text-emerald-200 font-bold text-center mb-1">
                      POWER & ANALOG INPUTS
                    </div>
                    <div className="grid grid-cols-8 gap-1 text-center text-[9px]">
                      <div className="p-1 rounded bg-slate-800 text-rose-400 font-bold">5V</div>
                      <div className="p-1 rounded bg-slate-800 text-amber-300">3.3V</div>
                      <div className="p-1 rounded bg-slate-800 text-emerald-400 font-bold">GND</div>
                      {/* A0 - Sensor Input */}
                      <div className="p-1 rounded bg-amber-500/30 text-amber-300 font-black border border-amber-500/50">
                        A0
                        <div className="text-[7px]">TEMP</div>
                      </div>
                      <div className="p-1 rounded bg-slate-800 text-slate-400">A1</div>
                      <div className="p-1 rounded bg-slate-800 text-slate-400">A2</div>
                      <div className="p-1 rounded bg-slate-800 text-slate-400">A3</div>
                      <div className="p-1 rounded bg-slate-800 text-slate-400">A4</div>
                    </div>
                  </div>

                  {/* Reset Button on PCB */}
                  <button
                    onClick={handleResetMcu}
                    className="absolute bottom-3 left-3 w-5 h-5 rounded-full bg-rose-600 border-2 border-white shadow-md active:scale-95 cursor-pointer"
                    title="Hardware Reset Switch"
                  />
                </div>

                {/* 2. Actuator & Peripheral Station (Cooling Fan + Optical LEDs) */}
                <div className="space-y-6">
                  {/* DC Axial Cooling Fan Unit */}
                  <div className="glass-panel p-5 rounded-2xl border border-slate-800 bg-slate-900/60 flex flex-col items-center justify-center text-center space-y-4 relative overflow-hidden">
                    {/* Fan Header Info */}
                    <div className="w-full flex justify-between items-center text-xs">
                      <span className="font-mono text-slate-400 flex items-center gap-1.5">
                        <Fan className="w-3.5 h-3.5 text-cyan-400" />
                        ACTUATOR: 12V BRUSHLESS DC FAN
                      </span>
                      <span
                        className={`font-mono font-bold text-xs px-2 py-0.5 rounded-full ${
                          simulatedHardware.fanOn
                            ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {simulatedHardware.fanOn ? '2,850 RPM (ACTIVE)' : '0 RPM (IDLE)'}
                      </span>
                    </div>

                    {/* Animated 7-Blade Industrial Fan SVG */}
                    <div className="relative w-44 h-44 flex items-center justify-center">
                      {/* Fan Shroud Housing */}
                      <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-slate-800 via-slate-900 to-slate-950 border-4 border-slate-700 shadow-2xl flex items-center justify-center">
                        {/* 4 Corner Screw Holes */}
                        <div className="absolute top-2 left-2 w-3 h-3 rounded-full bg-slate-950 border border-slate-600" />
                        <div className="absolute top-2 right-2 w-3 h-3 rounded-full bg-slate-950 border border-slate-600" />
                        <div className="absolute bottom-2 left-2 w-3 h-3 rounded-full bg-slate-950 border border-slate-600" />
                        <div className="absolute bottom-2 right-2 w-3 h-3 rounded-full bg-slate-950 border border-slate-600" />
                        {/* Circular Fan Duct Ring */}
                        <div className="w-36 h-36 rounded-full border-2 border-slate-600/80 bg-slate-950 flex items-center justify-center relative overflow-hidden">
                          {/* Radial Wind Turbulence Particles (Visible when ON) */}
                          {simulatedHardware.fanOn && (
                            <div className="absolute inset-0 fan-wind-active rounded-full bg-gradient-to-tr from-cyan-500/20 via-transparent to-sky-400/20 pointer-events-none" />
                          )}

                          {/* The Rotating Fan Blades */}
                          <svg
                            viewBox="0 0 100 100"
                            className={`w-32 h-32 ${simulatedHardware.fanOn ? 'fan-spinning' : 'transition-transform duration-1000'}`}
                          >
                            <g fill={simulatedHardware.fanOn ? '#06b6d4' : '#64748b'}>
                              {/* 7 Curved Aerodynamic Blades */}
                              {[0, 51.4, 102.8, 154.2, 205.7, 257.1, 308.5].map((angle, idx) => (
                                <path
                                  key={idx}
                                  d="M 50 50 C 45 35, 30 20, 50 5 C 65 15, 60 35, 50 50 Z"
                                  transform={`rotate(${angle} 50 50)`}
                                  opacity={simulatedHardware.fanOn ? 0.9 : 0.75}
                                />
                              ))}
                            </g>
                            {/* Central Rotor Hub */}
                            <circle cx="50" cy="50" r="14" fill="#0f172a" stroke="#38bdf8" strokeWidth="2.5" />
                            <circle cx="50" cy="50" r="5" fill="#38bdf8" />
                          </svg>
                        </div>
                      </div>
                    </div>

                    {/* Live Pin & Actuator Voltage */}
                    <div className="w-full grid grid-cols-2 gap-2 text-[11px] font-mono pt-1">
                      <div className="p-2 rounded-xl bg-slate-950 border border-slate-800 text-left">
                        <span className="text-slate-400">PIN 9 (FAN_PIN):</span>
                        <div className="font-bold text-slate-200">
                          {simulatedHardware.fanPinState === 1 ? (
                            <span className="text-cyan-400 font-black">HIGH (5.00 V)</span>
                          ) : (
                            <span className="text-slate-500">LOW (0.00 V)</span>
                          )}
                        </div>
                      </div>

                      <div className="p-2 rounded-xl bg-slate-950 border border-slate-800 text-left">
                        <span className="text-slate-400">FAN PWM DUTY:</span>
                        <div className="font-bold text-slate-200">
                          {simulatedHardware.fanOn ? (
                            <span className="text-emerald-400">100% (FULL SPEED)</span>
                          ) : (
                            <span className="text-slate-500">0% (OFF)</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Optical Hardware Indicator LEDs */}
                  <div className="glass-panel p-4 rounded-2xl border border-slate-800 grid grid-cols-2 gap-4">
                    {/* Blue Fan Indicator LED (Pin 9) */}
                    <div className="flex items-center gap-3 p-3 rounded-xl bg-slate-950 border border-slate-800">
                      <div
                        className={`w-6 h-6 rounded-full border-2 transition-all ${
                          simulatedHardware.fanPinState === 1
                            ? 'bg-cyan-400 border-cyan-300 led-glow-cyan scale-110'
                            : 'bg-slate-800 border-slate-700'
                        }`}
                      />
                      <div>
                        <div className="text-xs font-bold text-slate-200">FAN LED</div>
                        <div className="text-[10px] font-mono text-cyan-400">PIN 9 (PWM)</div>
                      </div>
                    </div>

                    {/* Red Error / Fault LED (Pin 8) */}
                    <div className="flex items-center gap-3 p-3 rounded-xl bg-slate-950 border border-slate-800">
                      <div
                        className={`w-6 h-6 rounded-full border-2 transition-all ${
                          simulatedHardware.errPinState === 1
                            ? 'bg-rose-500 border-rose-300 led-glow-red laser-alert scale-110'
                            : 'bg-slate-800 border-slate-700'
                        }`}
                      />
                      <div>
                        <div className="text-xs font-bold text-slate-200">ERROR LED</div>
                        <div className="text-[10px] font-mono text-rose-400">PIN 8 (FAULT)</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Defect Alert Notice (When active rule trips a bug) */}
            {simulatedHardware.defectAlert && (
              <div className="mt-4 p-4 rounded-xl bg-rose-500/10 border border-rose-500/40 flex items-start gap-3 text-xs text-rose-200 animate-fadeIn">
                <AlertOctagon className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <div className="font-bold text-rose-300 text-sm">Specification Violation Identified</div>
                  <p>{simulatedHardware.defectAlert}</p>
                </div>
              </div>
            )}
          </div>

          {/* Mini Logic Analyzer / Waveform Timeline */}
          <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
            <div className="flex items-center justify-between text-xs">
              <h4 className="font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <Activity className="w-4 h-4 text-indigo-400" />
                Peripheral Logic Waveform Analyzer (Last 25 Cycles)
              </h4>
              <span className="font-mono text-slate-500 text-[11px]">Sampling: 100ms / Tick</span>
            </div>

            {/* Waveform Channels */}
            <div className="space-y-2 p-3 rounded-xl bg-slate-950 border border-slate-800 font-mono text-[11px]">
              {/* Channel 1: FAN Pin 9 */}
              <div className="flex items-center gap-3">
                <span className="w-20 font-bold text-cyan-400 shrink-0">PIN 9 (FAN):</span>
                <div className="flex-1 flex items-center gap-0.5 h-6 overflow-hidden">
                  {waveformHistory.map((w, idx) => (
                    <div
                      key={idx}
                      className={`flex-1 h-full rounded-sm transition-all ${
                        w.fan === 1 ? 'bg-cyan-400 led-glow-cyan' : 'bg-slate-800'
                      }`}
                      title={`Tick ${idx}: Fan ${w.fan === 1 ? 'HIGH' : 'LOW'}`}
                    />
                  ))}
                </div>
                <span className="w-12 text-right font-bold text-slate-300">
                  {simulatedHardware.fanPinState === 1 ? 'HIGH' : 'LOW'}
                </span>
              </div>

              {/* Channel 2: ERR Pin 8 */}
              <div className="flex items-center gap-3">
                <span className="w-20 font-bold text-rose-400 shrink-0">PIN 8 (ERR):</span>
                <div className="flex-1 flex items-center gap-0.5 h-6 overflow-hidden">
                  {waveformHistory.map((w, idx) => (
                    <div
                      key={idx}
                      className={`flex-1 h-full rounded-sm transition-all ${
                        w.err === 1 ? 'bg-rose-500 led-glow-red' : 'bg-slate-800'
                      }`}
                      title={`Tick ${idx}: Error ${w.err === 1 ? 'HIGH' : 'LOW'}`}
                    />
                  ))}
                </div>
                <span className="w-12 text-right font-bold text-slate-300">
                  {simulatedHardware.errPinState === 1 ? 'HIGH' : 'LOW'}
                </span>
              </div>

              {/* Channel 3: Analog Voltage A0 */}
              <div className="flex items-center gap-3">
                <span className="w-20 font-bold text-amber-400 shrink-0">PIN A0 (V):</span>
                <div className="flex-1 flex items-end gap-0.5 h-6 overflow-hidden">
                  {waveformHistory.map((w, idx) => (
                    <div
                      key={idx}
                      style={{ height: `${Math.max(10, (w.voltage / 5.0) * 100)}%` }}
                      className="flex-1 bg-amber-400 rounded-sm transition-all"
                      title={`Tick ${idx}: ${w.voltage.toFixed(2)}V`}
                    />
                  ))}
                </div>
                <span className="w-12 text-right font-bold text-amber-300">
                  {simulatedHardware.voltage.toFixed(2)}V
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Interactive Sensor Controls, Fault Injection, UART Stream */}
        <div className="lg:col-span-4 space-y-6">
          {/* Temperature Sensor Controls & Presets */}
          <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-5">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Thermometer className="w-4 h-4 text-amber-400" />
                Sensor Stimulus (NTC A0)
              </h3>
              <span className="text-[11px] font-mono text-slate-400">Beta = 3950 K</span>
            </div>

            {/* Big Temperature Readout Card */}
            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-center space-y-1">
              <div className="text-3xl font-extrabold font-mono text-amber-400">
                {temperature.toFixed(1)} °C
                <span className="text-sm text-slate-500 font-normal ml-2">
                  ({((temperature * 9) / 5 + 32).toFixed(1)} °F)
                </span>
              </div>
              <div className="flex justify-center items-center gap-4 text-xs font-mono text-slate-400 pt-1">
                <span>ADC: <strong className="text-sky-300">{simulatedHardware.adc}</strong> / 1023</span>
                <span>•</span>
                <span>VOLTS: <strong className="text-emerald-300">{simulatedHardware.voltage.toFixed(2)}V</strong></span>
              </div>
            </div>

            {/* Slider Control */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-slate-400">
                <span>-20 °C</span>
                <span className="text-sky-400 font-bold">Threshold: 30 °C</span>
                <span>+80 °C</span>
              </div>
              <input
                type="range"
                min={-20}
                max={80}
                step={1}
                value={temperature}
                onChange={e => {
                  setMode('interactive');
                  setFaultShort(false);
                  setFaultOpen(false);
                  setTemperature(Number(e.target.value));
                }}
                className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-sky-400"
              />
            </div>

            {/* Scenario Presets */}
            <div className="space-y-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Scenario Presets
              </span>
              <div className="grid grid-cols-3 gap-2">
                <button
                  onClick={() => handleApplyPreset(25)}
                  className={`p-2 rounded-xl text-xs font-semibold border transition-all ${
                    temperature === 25 && !faultShort && !faultOpen
                      ? 'bg-sky-500 text-white border-sky-400 shadow-md'
                      : 'bg-slate-900 border-slate-800 text-slate-300 hover:border-slate-700'
                  }`}
                >
                  25°C Room
                </button>

                <button
                  onClick={() => handleApplyPreset(30)}
                  className={`p-2 rounded-xl text-xs font-bold border transition-all ${
                    temperature === 30 && !faultShort && !faultOpen
                      ? 'bg-amber-500 text-white border-amber-400 shadow-md'
                      : 'bg-amber-500/10 border-amber-500/30 text-amber-300 hover:border-amber-500/50'
                  }`}
                >
                  30°C Boundary
                </button>

                <button
                  onClick={() => handleApplyPreset(35)}
                  className={`p-2 rounded-xl text-xs font-semibold border transition-all ${
                    temperature === 35 && !faultShort && !faultOpen
                      ? 'bg-sky-500 text-white border-sky-400 shadow-md'
                      : 'bg-slate-900 border-slate-800 text-slate-300 hover:border-slate-700'
                  }`}
                >
                  35°C Hot
                </button>
              </div>
            </div>

            {/* Fault Injection Pushbuttons (Matching Wokwi diagram.json buttons) */}
            <div className="space-y-2 pt-2 border-t border-slate-800">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-rose-400" />
                Hardware Fault Injection (Buttons)
              </span>
              <div className="grid grid-cols-2 gap-2">
                {/* Short to GND Button */}
                <button
                  onClick={() => {
                    setMode('interactive');
                    setFaultShort(!faultShort);
                    setFaultOpen(false);
                  }}
                  className={`p-2.5 rounded-xl text-xs font-bold border flex flex-col items-center gap-1 transition-all ${
                    faultShort
                      ? 'bg-rose-500 text-white border-rose-400 led-glow-red'
                      : 'bg-slate-900 border-slate-800 text-rose-400 hover:border-rose-500/40'
                  }`}
                >
                  <span>⚡ Short to GND</span>
                  <span className="text-[10px] font-mono opacity-80">(btn_short: ADC=0)</span>
                </button>

                {/* Open Circuit Button */}
                <button
                  onClick={() => {
                    setMode('interactive');
                    setFaultOpen(!faultOpen);
                    setFaultShort(false);
                  }}
                  className={`p-2.5 rounded-xl text-xs font-bold border flex flex-col items-center gap-1 transition-all ${
                    faultOpen
                      ? 'bg-rose-500 text-white border-rose-400 led-glow-red'
                      : 'bg-slate-900 border-slate-800 text-rose-400 hover:border-rose-500/40'
                  }`}
                >
                  <span>⚡ Open Circuit</span>
                  <span className="text-[10px] font-mono opacity-80">(btn_open: ADC=1023)</span>
                </button>
              </div>
            </div>
          </div>

          {/* Virtual UART Serial Console */}
          <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <Terminal className="w-3.5 h-3.5 text-emerald-400" />
                Virtual UART Serial Log (9600 Baud)
              </h4>
              <button
                onClick={() => setSerialLogs(['[UART CLEARED]'])}
                className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
              >
                Clear
              </button>
            </div>

            <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 font-mono text-[11px] text-emerald-400 max-h-52 overflow-y-auto leading-relaxed space-y-1">
              {serialLogs.map((log, idx) => (
                <div
                  key={idx}
                  className={
                    log.includes('ERROR') || log.includes('Defect')
                      ? 'text-rose-400 font-bold'
                      : log.includes('RESET') || log.includes('BOOT')
                      ? 'text-sky-300'
                      : 'text-emerald-400'
                  }
                >
                  {log}
                </div>
              ))}
              <div ref={consoleEndRef} />
            </div>
          </div>

          {/* Source Code Snippet Inspector */}
          <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <FileCode className="w-3.5 h-3.5 text-sky-400" />
                Active Firmware Logic ({sketchInfo.filename})
              </span>
            </div>

            <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 max-h-40 overflow-y-auto leading-relaxed">
              <pre>
                {sketchInfo.hasStrictInequalityBug
                  ? `// PLANT 1: Strict inequality bug\nif (tempC > THRESHOLD_C) {\n  fanOn = true;\n}\n\n// PLANT 2: Open circuit defect\nif (adc == 0) {\n  error = true;\n}`
                  : `// Golden logic (compliant)\nif (adc <= 0 || adc >= 1023) {\n  error = true;\n} else if (tempC >= THRESHOLD_C) {\n  fanOn = true;\n}`}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
