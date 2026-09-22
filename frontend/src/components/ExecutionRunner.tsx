import React, { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock,
  Cpu,
  Play,
  RotateCcw,
  Terminal,
  Tv,
  XCircle,
} from 'lucide-react';
import { VisualCircuitSimulator } from './VisualCircuitSimulator';
import type { AnalysisResult, Firmware, TestResult, TestRun, TestSuite } from '../types';

interface ExecutionRunnerProps {
  currentRun: TestRun | null;
  currentSuite?: TestSuite | null;
  firmware?: Firmware | null;
  analysis?: AnalysisResult | null;
  onNavigateToFailures: () => void;
  onRerun: () => void;
  isRunning: boolean;
}

export const ExecutionRunner: React.FC<ExecutionRunnerProps> = ({
  currentRun,
  currentSuite = null,
  firmware = null,
  analysis = null,
  onNavigateToFailures,
  onRerun,
  isRunning,
}) => {
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'matrix' | 'bench'>('matrix');

  if (isRunning) {
    return (
      <div className="glass-panel p-16 rounded-2xl border border-sky-500/30 text-center space-y-6">
        <div className="w-14 h-14 border-4 border-sky-500/20 border-t-sky-400 rounded-full animate-spin mx-auto" />
        <div className="space-y-2">
          <h3 className="text-xl font-bold text-white">Running Virtual Hardware Simulation</h3>
          <p className="text-sm text-slate-300 max-w-md mx-auto">
            Stimulating sensor transfer functions, stepping deterministic peripheral clocks, and capturing UART telemetry...
          </p>
        </div>
      </div>
    );
  }

  if (!currentRun) {
    return (
      <div className="glass-panel p-16 rounded-2xl border border-slate-800 text-center space-y-3">
        <Cpu className="w-12 h-12 text-slate-600 mx-auto" />
        <h3 className="text-lg font-bold text-slate-200">No Active Simulation Run</h3>
        <p className="text-sm text-slate-400 max-w-md mx-auto">
          Generate a test suite or click "Run Demo Mode" from the Dashboard to execute virtual simulation tests.
        </p>
      </div>
    );
  }

  const selectedResult =
    currentRun.results.find(r => r.id === selectedResultId) || currentRun.results[0];

  const hasFailures = currentRun.failed > 0 || currentRun.errored > 0;

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Execution Summary Banner */}
      <div className="glass-panel p-6 rounded-2xl border border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span
              className={`px-3 py-1 rounded-full text-xs font-bold border ${
                currentRun.pass_rate === 100
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
              }`}
            >
              OVERALL: {currentRun.pass_rate === 100 ? 'ALL PASSED' : 'DEFECTS DETECTED'} ({currentRun.pass_rate}%)
            </span>
            <span className="font-mono text-xs text-slate-400">
              Run: {currentRun.id.slice(0, 8)} • Simulator: {currentRun.simulator_backend}
            </span>
          </div>

          <h2 className="text-2xl font-extrabold text-white">
            Simulation Results for <span className="text-sky-400 font-mono">{currentRun.firmware_filename || 'firmware.ino'}</span>
          </h2>
          <p className="text-xs text-slate-300">
            {currentRun.passed} Passed, {currentRun.failed} Failed, {currentRun.errored} Errored across {currentRun.total} test cases in {currentRun.duration_ms}ms.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* View Toggle */}
          <div className="flex rounded-xl bg-slate-900 p-1 border border-slate-700">
            <button
              onClick={() => setViewMode('matrix')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                viewMode === 'matrix'
                  ? 'bg-sky-500 text-white shadow-md shadow-sky-500/25'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              Test Matrix
            </button>
            <button
              onClick={() => setViewMode('bench')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                viewMode === 'bench'
                  ? 'bg-sky-500 text-white shadow-md shadow-sky-500/25'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Tv className="w-3.5 h-3.5" />
              Visual Circuit Bench
            </button>
          </div>

          {hasFailures && (
            <button
              onClick={onNavigateToFailures}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-rose-500 to-indigo-600 hover:from-rose-400 hover:to-indigo-500 text-white font-bold text-xs shadow-lg shadow-rose-500/20 transition-all"
            >
              <Bot className="w-4 h-4" />
              Inspect AI Causes
              <ArrowRight className="w-4 h-4" />
            </button>
          )}

          <button
            onClick={onRerun}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition-all"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Re-run Suite
          </button>
        </div>
      </div>

      {/* Render either the Visual Hardware Bench or the Test Matrix Inspector */}
      {viewMode === 'bench' ? (
        <VisualCircuitSimulator
          firmware={firmware}
          analysis={analysis}
          currentRun={currentRun}
          currentSuite={currentSuite}
          onNavigateToFailures={onNavigateToFailures}
        />
      ) : (
        /* Results Explorer Grid */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Results List */}
        <div className="space-y-2.5 max-h-[640px] overflow-y-auto pr-1">
          {currentRun.results.map(r => {
            const isSelected = selectedResult?.id === r.id;
            const isPass = r.status === 'PASS';

            return (
              <div
                key={r.id}
                onClick={() => setSelectedResultId(r.id)}
                className={`p-4 rounded-xl border cursor-pointer transition-all ${
                  isSelected
                    ? isPass
                      ? 'bg-emerald-500/10 border-emerald-500/50 shadow-md shadow-emerald-500/10'
                      : 'bg-rose-500/10 border-rose-500/50 shadow-md shadow-rose-500/10'
                    : 'glass-panel border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span className="font-mono font-bold text-slate-200">{r.test_id}</span>
                  <span
                    className={`flex items-center gap-1 font-bold text-[11px] ${
                      isPass ? 'text-emerald-400' : 'text-rose-400'
                    }`}
                  >
                    {isPass ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
                    {r.status}
                  </span>
                </div>
                <div className="text-xs font-semibold text-slate-100 truncate">{r.name}</div>
                <div className="flex justify-between items-center text-[10px] text-slate-400 mt-2 font-mono">
                  <span>{r.assertions?.length || 0} assertion(s)</span>
                  <span>{r.duration_ms}ms</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Test Result Inspector */}
        {selectedResult && (
          <div className="lg:col-span-2 space-y-6">
            {/* Verdict Card */}
            <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm text-sky-400">{selectedResult.test_id}</span>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-bold ${
                        selectedResult.status === 'PASS'
                          ? 'bg-emerald-500/20 text-emerald-400'
                          : 'bg-rose-500/20 text-rose-400'
                      }`}
                    >
                      {selectedResult.status}
                    </span>
                  </div>
                  <h3 className="text-lg font-bold text-white mt-1">{selectedResult.name}</h3>
                </div>
              </div>

              {/* Assertions Table */}
              <div className="space-y-2">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Deterministic Assertions Evaluated
                </h4>
                <div className="space-y-2">
                  {selectedResult.assertions?.map((ass, idx) => (
                    <div
                      key={idx}
                      className={`p-3 rounded-xl border text-xs flex items-start justify-between gap-3 ${
                        ass.outcome === 'PASS'
                          ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-300'
                          : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
                      }`}
                    >
                      <div className="space-y-1">
                        <div className="font-bold flex items-center gap-1.5">
                          {ass.outcome === 'PASS' ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          ) : (
                            <XCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                          )}
                          <span>Target: {ass.target}</span>
                        </div>
                        <p className="text-[11px] text-slate-300">{ass.message}</p>
                      </div>

                      <div className="text-right font-mono text-[11px] shrink-0">
                        <div>Exp: {String(ass.expected)}</div>
                        <div>Obs: {String(ass.actual)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* UART Serial Log Monitor */}
            <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                <Terminal className="w-3.5 h-3.5 text-sky-400" />
                Virtual UART Serial Output (Telemetry Stream)
              </h4>
              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs text-emerald-400 max-h-48 overflow-y-auto leading-relaxed">
                {selectedResult.serial_log ? (
                  <pre>{selectedResult.serial_log}</pre>
                ) : (
                  <span className="text-slate-600">No UART output emitted during this cycle.</span>
                )}
              </div>
            </div>
          </div>
        )}
        </div>
      )}
    </div>
  );
};

