import React from 'react';
import {
  Activity,
  AlertOctagon,
  ArrowRight,
  CheckCircle2,
  Cpu,
  Layers,
  Sliders,
  Sparkles,
  Zap,
} from 'lucide-react';
import type { AnalysisResult, Firmware } from '../types';

interface AnalysisViewProps {
  analysis: AnalysisResult | null;
  firmware: Firmware | null;
  onProceedToTestGen: () => void;
  isLoading: boolean;
}

export const AnalysisView: React.FC<AnalysisViewProps> = ({
  analysis,
  firmware,
  onProceedToTestGen,
  isLoading,
}) => {
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 space-y-4">
        <div className="w-10 h-10 border-4 border-sky-500/30 border-t-sky-500 rounded-full animate-spin" />
        <p className="text-sm font-semibold text-slate-300">Extracting AST, GPIO Pins, & Thresholds...</p>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="glass-panel p-12 rounded-2xl border border-slate-800 text-center space-y-4">
        <Cpu className="w-12 h-12 text-slate-600 mx-auto" />
        <h3 className="text-lg font-bold text-slate-200">No Static Analysis Results Available</h3>
        <p className="text-sm text-slate-400 max-w-md mx-auto">
          Select or upload a firmware file to run the lexical and AST machine model extraction.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Header Banner */}
      <div className="glass-panel p-6 rounded-2xl border border-sky-500/20 bg-gradient-to-r from-sky-950/30 to-indigo-950/30 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30">
              AST Model v{analysis.analyzer_version}
            </span>
            <span className="text-xs text-slate-400 font-mono">
              Duration: {analysis.duration_ms}ms
            </span>
          </div>
          <h2 className="text-xl font-bold text-white">
            Extracted Machine Model for <span className="text-sky-400 font-mono">{firmware?.filename || 'firmware.ino'}</span>
          </h2>
          <p className="text-sm text-slate-300">{analysis.summary}</p>
        </div>

        <button
          onClick={onProceedToTestGen}
          className="flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-bold text-xs shadow-lg shadow-sky-500/25 transition-all self-start md:self-auto shrink-0"
        >
          <Sparkles className="w-4 h-4" />
          Generate Test Suite
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="glass-panel p-4 rounded-xl border border-slate-800">
          <div className="text-xs text-slate-400 font-semibold uppercase">Total Lines</div>
          <div className="text-2xl font-bold font-mono text-slate-200 mt-1">
            {analysis.metrics?.total_lines ?? 0}
          </div>
        </div>

        <div className="glass-panel p-4 rounded-xl border border-slate-800">
          <div className="text-xs text-slate-400 font-semibold uppercase">Cyclomatic Complexity</div>
          <div className="text-2xl font-bold font-mono text-indigo-400 mt-1">
            {analysis.metrics?.cyclomatic_complexity ?? 0}
          </div>
        </div>

        <div className="glass-panel p-4 rounded-xl border border-slate-800">
          <div className="text-xs text-slate-400 font-semibold uppercase">Branch Points</div>
          <div className="text-2xl font-bold font-mono text-sky-400 mt-1">
            {analysis.metrics?.branch_count ?? 0}
          </div>
        </div>

        <div className="glass-panel p-4 rounded-xl border border-slate-800">
          <div className="text-xs text-slate-400 font-semibold uppercase">Functions</div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
            {analysis.functions?.length ?? 0}
          </div>
        </div>
      </div>

      {/* Two Column Section: GPIO Signals & Recovered Thresholds */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* I/O Pin Map */}
        <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Cpu className="w-4 h-4 text-sky-400" />
            Recovered GPIO & Sensor Signal Map ({analysis.gpio_pins?.length || 0})
          </h3>

          <div className="space-y-2.5">
            {analysis.inputs?.map((inp, idx) => (
              <div
                key={`in-${idx}`}
                className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between text-xs"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
                  <div>
                    <span className="font-mono font-bold text-sky-300">{inp.symbol}</span>
                    <span className="text-slate-400 ml-2 text-[11px]">Pin {inp.pin} (Analog ADC)</span>
                  </div>
                </div>
                <div className="text-right">
                  <span className="px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 font-mono text-[11px]">
                    {inp.transfer_function?.unit || 'counts'} ({inp.range?.join('..')})
                  </span>
                </div>
              </div>
            ))}

            {analysis.outputs?.map((out, idx) => (
              <div
                key={`out-${idx}`}
                className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between text-xs"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-2 h-2 rounded-full bg-emerald-400" />
                  <div>
                    <span className="font-mono font-bold text-emerald-300">{out.symbol}</span>
                    <span className="text-slate-400 ml-2 text-[11px]">Pin {out.pin} (Digital Out)</span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px] uppercase font-semibold">
                  {out.role || 'actuator'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Thresholds & Boundary Logic */}
        <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Sliders className="w-4 h-4 text-indigo-400" />
            Comparison Thresholds & Boundaries ({analysis.thresholds?.length || 0})
          </h3>

          <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
            {analysis.thresholds?.map((th, idx) => (
              <div
                key={`th-${idx}`}
                className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between text-xs"
              >
                <div>
                  <div className="font-mono font-semibold text-slate-200">{th.expression}</div>
                  <div className="text-[10px] text-slate-500 mt-0.5">
                    Source Line {th.line_number} • Target Value: {th.value}
                  </div>
                </div>
                <span className="px-2 py-1 rounded bg-indigo-500/10 text-indigo-300 font-mono font-bold text-[11px]">
                  {th.operator}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Finite State Machine Diagram & Risk Areas */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* State Machine */}
        <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Layers className="w-4 h-4 text-emerald-400" />
            Finite State Machine (FSM)
          </h3>

          {analysis.states && analysis.states.length > 0 ? (
            <div className="space-y-3">
              <div className="text-xs font-mono text-slate-400">
                Enum: <span className="text-sky-300 font-bold">{analysis.states[0].enum}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {analysis.states[0].members?.map((m, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs font-mono font-bold text-slate-200"
                  >
                    <span className="w-5 h-5 rounded-full bg-slate-800 text-slate-400 flex items-center justify-center text-[10px]">
                      {m.value}
                    </span>
                    {m.name}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-500">No explicit state enum recovered.</p>
          )}
        </div>

        {/* Static Risk Areas */}
        <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <AlertOctagon className="w-4 h-4 text-rose-400" />
            Static Risk Areas ({analysis.risk_areas?.length || 0})
          </h3>

          <div className="space-y-2">
            {analysis.risk_areas && analysis.risk_areas.length > 0 ? (
              analysis.risk_areas.map((risk, idx) => (
                <div
                  key={idx}
                  className="p-3 rounded-xl bg-rose-500/5 border border-rose-500/20 text-xs flex justify-between items-center"
                >
                  <div>
                    <div className="font-bold text-rose-300">{risk.title}</div>
                    <div className="text-slate-400 text-[11px] mt-0.5">{risk.description}</div>
                  </div>
                  <span className="font-mono text-rose-400 font-bold text-[10px]">
                    Line {risk.line_number}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-slate-500">No static high-risk patterns identified.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
