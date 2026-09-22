import React, { useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Cpu,
  Layers,
  Play,
  RotateCcw,
  Shield,
  Sliders,
  Sparkles,
  Zap,
} from 'lucide-react';
import type { Firmware, TestCase, TestSuite } from '../types';

interface TestGeneratorProps {
  suite: TestSuite | null;
  firmware: Firmware | null;
  onGenerate: (params: { max_tests: number; focus: string; use_llm: boolean }) => Promise<void>;
  onRunSuite: (suiteId: string) => void;
  isLoading: boolean;
  isRunning: boolean;
}

export const TestGenerator: React.FC<TestGeneratorProps> = ({
  suite,
  firmware,
  onGenerate,
  onRunSuite,
  isLoading,
  isRunning,
}) => {
  const [maxTests, setMaxTests] = useState(8);
  const [useLLM, setUseLLM] = useState(true);
  const [focus, setFocus] = useState('');
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  const handleGenerate = () => {
    onGenerate({ max_tests: maxTests, focus, use_llm: useLLM });
  };

  const selectedCase = suite?.cases.find(c => c.id === selectedCaseId) || suite?.cases[0];

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Configuration & Controls */}
      <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-sky-400" />
              Autonomous Test Suite Synthesis
            </h2>
            <p className="text-slate-400 text-xs mt-1">
              Targeting <span className="font-mono font-bold text-slate-200">{firmware?.filename || 'Loaded Firmware'}</span>
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleGenerate}
              disabled={isLoading}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-bold text-xs shadow-lg shadow-sky-500/20 transition-all disabled:opacity-50"
            >
              {isLoading ? (
                <>
                  <RotateCcw className="w-3.5 h-3.5 animate-spin" />
                  Synthesizing Test Scenarios...
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5" />
                  Synthesize Test Suite
                </>
              )}
            </button>

            {suite && (
              <button
                onClick={() => onRunSuite(suite.id)}
                disabled={isRunning}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all disabled:opacity-50"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                {isRunning ? 'Running Simulator...' : 'Run in Simulator'}
              </button>
            )}
          </div>
        </div>

        {/* Synthesis Options */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-3 border-t border-slate-800/80 text-xs">
          <div>
            <label className="block font-semibold text-slate-300 mb-1.5">
              Test Count: <span className="font-mono text-sky-400 font-bold">{maxTests}</span>
            </label>
            <input
              type="range"
              min={3}
              max={15}
              value={maxTests}
              onChange={e => setMaxTests(parseInt(e.target.value))}
              className="w-full accent-sky-500 bg-slate-800"
            />
          </div>

          <div>
            <label className="block font-semibold text-slate-300 mb-1.5">Synthesis Engine</label>
            <div className="flex rounded-lg bg-slate-900 p-1 border border-slate-800">
              <button
                type="button"
                onClick={() => setUseLLM(true)}
                className={`flex-1 py-1 rounded font-semibold text-center transition-all ${
                  useLLM ? 'bg-sky-500 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                AI Reasoning (LLM)
              </button>
              <button
                type="button"
                onClick={() => setUseLLM(false)}
                className={`flex-1 py-1 rounded font-semibold text-center transition-all ${
                  !useLLM ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Deterministic
              </button>
            </div>
          </div>

          <div>
            <label className="block font-semibold text-slate-300 mb-1.5">Focus Areas (Optional)</label>
            <input
              type="text"
              value={focus}
              onChange={e => setFocus(e.target.value)}
              placeholder="e.g. boundary, hysteresis, safety"
              className="w-full bg-slate-900 border border-slate-800 text-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-sky-500"
            />
          </div>
        </div>
      </div>

      {/* Test Suite Display */}
      {suite ? (
        <div className="space-y-6">
          {/* Suite Metadata Banner */}
          <div className="glass-panel p-5 rounded-2xl border border-slate-800 flex flex-wrap items-center justify-between gap-4 text-xs">
            <div className="flex items-center gap-3">
              <span className="font-mono font-bold text-sm text-white">{suite.name}</span>
              <span className="px-2.5 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 font-mono">
                Engine: {suite.generator_engine}
              </span>
              <span className="text-slate-400 font-mono">
                Synthesized in {suite.generation_ms}ms
              </span>
            </div>

            <div className="text-slate-300">
              {suite.cases.length} synthesized test cases
            </div>
          </div>

          {/* Test Case Cards Grid & Detail Drawer */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* List of Test Cases */}
            <div className="space-y-2.5 max-h-[600px] overflow-y-auto pr-1">
              {suite.cases.map(tc => {
                const isSelected = selectedCase?.id === tc.id;
                const catColor =
                  tc.category === 'safety'
                    ? 'text-rose-400 bg-rose-500/10 border-rose-500/20'
                    : tc.category === 'boundary'
                    ? 'text-amber-400 bg-amber-500/10 border-amber-500/20'
                    : 'text-sky-400 bg-sky-500/10 border-sky-500/20';

                return (
                  <div
                    key={tc.id}
                    onClick={() => setSelectedCaseId(tc.id)}
                    className={`p-4 rounded-xl border cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-sky-500/10 border-sky-500/50 shadow-md shadow-sky-500/10'
                        : 'glass-panel border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <span className="font-mono font-bold text-slate-200">{tc.test_id}</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${catColor}`}>
                        {tc.category}
                      </span>
                    </div>
                    <div className="text-xs font-semibold text-slate-100 truncate">{tc.name}</div>
                    <div className="text-[11px] text-slate-400 line-clamp-1 mt-1">{tc.description}</div>
                  </div>
                );
              })}
            </div>

            {/* Selected Test Case Inspector */}
            {selectedCase && (
              <div className="lg:col-span-2 glass-panel p-6 rounded-2xl border border-slate-800 space-y-5">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-sm text-sky-400">{selectedCase.test_id}</span>
                      <span className="px-2 py-0.5 rounded text-xs uppercase font-bold bg-slate-800 text-slate-300">
                        Priority: {selectedCase.priority}
                      </span>
                    </div>
                    <h3 className="text-lg font-bold text-white mt-1">{selectedCase.name}</h3>
                  </div>
                </div>

                <div className="space-y-3 text-xs">
                  {selectedCase.requirement && (
                    <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800">
                      <span className="font-bold text-slate-300">Requirement: </span>
                      <span className="text-slate-300">{selectedCase.requirement}</span>
                    </div>
                  )}

                  <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800">
                    <span className="font-bold text-slate-300">Rationale & Explainability: </span>
                    <span className="text-slate-400 leading-relaxed">{selectedCase.rationale}</span>
                  </div>
                </div>

                {/* Stimulus Envelope */}
                <div className="space-y-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                    <Zap className="w-3.5 h-3.5 text-amber-400" />
                    Virtual Peripheral Stimulus
                  </h4>
                  <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono space-y-1">
                    <div className="text-slate-400">
                      Cycles: {selectedCase.stimulus?.ticks} ticks @ {selectedCase.stimulus?.tick_ms}ms/tick
                    </div>
                    {selectedCase.stimulus?.events?.map((ev, i) => (
                      <div key={i} className="text-amber-300">
                        • [Tick {ev.tick}] Channel <span className="text-white">{ev.channel}</span> = {ev.value} {ev.unit}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Expectations & Verification Contract */}
                <div className="space-y-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    Deterministic Assertions ({selectedCase.expectations?.length || 0})
                  </h4>
                  <div className="space-y-1.5">
                    {selectedCase.expectations?.map((exp, i) => (
                      <div
                        key={i}
                        className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between text-xs"
                      >
                        <div>
                          <span className="font-mono font-bold text-emerald-300">{exp.target}</span>
                          <span className="text-slate-400 ml-2">{exp.description}</span>
                        </div>
                        <span className="px-2 py-0.5 rounded bg-slate-800 font-mono text-slate-300 font-semibold">
                          {exp.operator} {exp.value !== undefined ? String(exp.value) : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="glass-panel p-16 rounded-2xl border border-slate-800 text-center space-y-3">
          <Sparkles className="w-12 h-12 text-slate-600 mx-auto" />
          <h3 className="text-lg font-bold text-slate-200">No Test Suite Synthesized Yet</h3>
          <p className="text-sm text-slate-400 max-w-md mx-auto">
            Click "Synthesize Test Suite" above to generate comprehensive boundary, functional, and safety scenarios.
          </p>
        </div>
      )}
    </div>
  );
};
