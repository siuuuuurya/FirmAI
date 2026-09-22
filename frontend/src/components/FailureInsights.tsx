import React, { useState } from 'react';
import {
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  Copy,
  FileCode,
  KeyRound,
  Play,
  Send,
  Sparkles,
  Wrench,
} from 'lucide-react';
import type { HealthStatus, TestRun } from '../types';

interface FailureInsightsProps {
  currentRun: TestRun | null;
  health: HealthStatus | null;
  isRunning: boolean;
  onRunDebugDemo: () => void;
  onAnalyzeCurrentFailures: () => void;
  onNavigateToReports: () => void;
}

export const FailureInsights: React.FC<FailureInsightsProps> = ({
  currentRun,
  health,
  isRunning,
  onRunDebugDemo,
  onAnalyzeCurrentFailures,
  onNavigateToReports,
}) => {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'assistant' | 'user'; text: string }>>([
    {
      role: 'assistant',
      text: 'Ask me what to change, or click "Suggest changes" after diagnostics are available.',
    },
  ]);
  const geminiConnected = Boolean(health?.llm_enabled && health.llm_provider === 'gemini');
  const providerLabel = health?.llm_enabled
    ? `${health.llm_provider}:${health.llm_model}`
    : 'offline heuristic fallback';
  const failedResults = currentRun?.results.filter(
    r => r.status === 'FAIL' || r.status === 'ERROR'
  ) ?? [];

  const buildSuggestion = () => {
    if (!currentRun) {
      return 'Run a debug demo or analyze a failed simulation first. Once diagnostics exist, I can summarize the exact source changes here.';
    }

    if (failedResults.length === 0) {
      return 'No failing tests are present in this run, so there are no code changes to suggest.';
    }

    const analyzed = failedResults.filter(result => result.failure_analysis);
    if (analyzed.length === 0) {
      return 'Failures are present, but diagnostics have not been generated yet. Click "Generate Diagnostics" first, then I can suggest patches.';
    }

    return analyzed
      .map((result, index) => {
        const fa = result.failure_analysis!;
        const lines = fa.suspect_lines?.length ? `line ${fa.suspect_lines.join(', ')}` : 'the suspect control branch';
        const fix = fa.suggested_fix || fa.root_cause;
        return `${index + 1}. ${result.test_id}: change ${lines}. Suggested fix: ${fix}`;
      })
      .join('\n');
  };

  const handleChatSubmit = (event?: React.FormEvent) => {
    event?.preventDefault();
    const prompt = chatInput.trim();
    if (!prompt) return;

    const lowerPrompt = prompt.toLowerCase();
    const response = lowerPrompt.includes('change') || lowerPrompt.includes('fix') || lowerPrompt.includes('suggest')
      ? buildSuggestion()
      : `I can help with fix suggestions from the current diagnostics. Current summary:\n${buildSuggestion()}`;

    setChatMessages(prev => [
      ...prev,
      { role: 'user', text: prompt },
      { role: 'assistant', text: response },
    ]);
    setChatInput('');
  };

  const handleSuggestChanges = () => {
    setChatMessages(prev => [
      ...prev,
      { role: 'user', text: 'Suggest changes' },
      { role: 'assistant', text: buildSuggestion() },
    ]);
  };

  const chatPanel = (
    <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-bold text-white">
            <Bot className="w-4 h-4 text-sky-400" />
            Debug Assistant
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Suggests code changes from the diagnostics shown above.
          </p>
        </div>
        <button
          type="button"
          onClick={handleSuggestChanges}
          className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 border border-slate-700 transition-all self-start sm:self-auto"
        >
          <Wrench className="w-3.5 h-3.5 text-sky-400" />
          Suggest changes
        </button>
      </div>

      <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
        {chatMessages.map((message, index) => (
          <div
            key={`${message.role}-${index}`}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[88%] whitespace-pre-wrap rounded-xl px-3.5 py-2.5 text-xs leading-relaxed border ${
                message.role === 'user'
                  ? 'bg-sky-500/15 border-sky-500/30 text-sky-100'
                  : 'bg-slate-950/70 border-slate-800 text-slate-300'
              }`}
            >
              {message.text}
            </div>
          </div>
        ))}
      </div>

      <form onSubmit={handleChatSubmit} className="flex flex-col sm:flex-row gap-2">
        <input
          value={chatInput}
          onChange={event => setChatInput(event.target.value)}
          placeholder="Ask what should change in the firmware..."
          className="min-w-0 flex-1 rounded-xl border border-slate-800 bg-slate-950/80 px-3.5 py-2.5 text-xs text-slate-100 outline-none focus:border-sky-500"
        />
        <button
          type="submit"
          className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-bold transition-all"
        >
          <Send className="w-3.5 h-3.5" />
          Send
        </button>
      </form>
    </div>
  );

  if (!currentRun) {
    return (
      <div className="space-y-8 animate-fadeIn">
        <div className="glass-panel p-10 sm:p-14 rounded-2xl border border-slate-800 text-center space-y-6">
          <div className="w-14 h-14 rounded-2xl bg-sky-500/10 border border-sky-500/25 grid place-items-center mx-auto">
            <Bot className="w-8 h-8 text-sky-300" />
          </div>
          <div className="space-y-2">
            <h3 className="text-xl font-bold text-slate-100">AI Debugger Ready</h3>
            <p className="text-sm text-slate-400 max-w-lg mx-auto">
              Start the buggy firmware demo to create failures and generate root-cause diagnostics.
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-2 text-xs font-mono">
            <span className={`px-3 py-1.5 rounded-full border ${geminiConnected ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/10 text-amber-300 border-amber-500/30'}`}>
              <KeyRound className="inline w-3.5 h-3.5 mr-1" />
              {geminiConnected ? 'Debugger connected' : `Engine: ${providerLabel}`}
            </span>
          </div>
          <button
            type="button"
            onClick={onRunDebugDemo}
            disabled={isRunning}
            className="inline-flex items-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-bold shadow-lg shadow-sky-500/20 transition-all"
          >
            <Play className="w-4 h-4" />
            {isRunning ? 'Running Debugger...' : 'Run AI Debug Demo'}
          </button>
        </div>
        {chatPanel}
      </div>
    );
  }

  const missingAnalyses = failedResults.some(result => !result.failure_analysis);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Header Banner */}
      <div className="glass-panel p-6 rounded-2xl border border-rose-500/20 bg-gradient-to-r from-rose-950/20 via-indigo-950/20 to-slate-900/40 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="px-3 py-1 rounded-full text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30 flex items-center gap-1.5">
              <Bot className="w-3.5 h-3.5" />
              Root-Cause Diagnostic Engine
            </span>
            <span className="font-mono text-xs text-slate-400">
              {failedResults.length} defect(s) discovered in {currentRun.firmware_filename || 'firmware.ino'}
            </span>
          </div>

          <h2 className="text-2xl font-extrabold text-white">
            Root-Cause Discrepancy & Patch Analysis
          </h2>
          <p className="text-sm text-slate-300">
            Pinpointed source line discrepancies, observed hardware state violations, and proposed C++ patches.
          </p>
          <div className="flex flex-wrap gap-2 text-[11px] font-mono">
            <span className={`px-2.5 py-1 rounded-full border ${geminiConnected ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/10 text-amber-300 border-amber-500/30'}`}>
              {geminiConnected ? 'Debugger connected' : `Engine: ${providerLabel}`}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 self-start md:self-auto">
          {missingAnalyses && (
            <button
              type="button"
              onClick={onAnalyzeCurrentFailures}
              disabled={isRunning}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-bold transition-all"
            >
              <Sparkles className="w-4 h-4" />
              {isRunning ? 'Analyzing...' : 'Generate Diagnostics'}
            </button>
          )}
          <button
            onClick={onNavigateToReports}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition-all"
          >
            View Executive Report
          </button>
        </div>
      </div>

      {/* Failure Cards List */}
      {failedResults.length > 0 ? (
        <div className="space-y-6">
          {failedResults.map(result => {
            const fa = result.failure_analysis;
            const sevColor =
              fa?.severity === 'critical'
                ? 'bg-rose-500 text-white'
                : fa?.severity === 'high'
                ? 'bg-orange-500 text-white'
                : 'bg-amber-500 text-black';

            return (
              <div
                key={result.id}
                className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-5"
              >
                {/* Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 border-b border-slate-800">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-sm text-rose-400">{result.test_id}</span>
                      <span className={`px-2.5 py-0.5 rounded text-[10px] font-extrabold uppercase ${sevColor}`}>
                        {fa?.severity || 'HIGH'} SEVERITY
                      </span>
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-800 text-slate-300">
                        Category: {fa?.category || result.category}
                      </span>
                    </div>
                    <h3 className="text-base font-bold text-white mt-1">{result.name}</h3>
                  </div>

                  <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
                    <span>Confidence: {fa ? `${Math.round(fa.confidence * 100)}%` : '85%'}</span>
                    <span>•</span>
                    <span>Engine: {fa?.engine || 'heuristic'}</span>
                  </div>
                </div>

                {/* Root Cause & Explanation */}
                <div className="space-y-3 text-xs">
                  <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-200">
                    <span className="font-bold text-white">Root Cause: </span>
                    {fa?.root_cause || result.error_message || 'Assertion constraint failure observed in simulation.'}
                  </div>

                  {fa?.explanation && (
                    <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 text-slate-300 leading-relaxed">
                      <span className="font-bold text-slate-100">Hardware Impact Explanation: </span>
                      {fa.explanation}
                    </div>
                  )}

                  {/* Observational Evidence */}
                  {fa?.evidence && fa.evidence.length > 0 && (
                    <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                      <span className="font-bold text-slate-300 uppercase text-[11px]">Observational Evidence:</span>
                      <ul className="list-disc list-inside space-y-1 text-slate-400 font-mono text-[11px]">
                        {fa.evidence.map((ev, idx) => (
                          <li key={idx}>{ev}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {/* Code Diff Box */}
                {fa?.fix_diff ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                        <FileCode className="w-3.5 h-3.5 text-sky-400" />
                        Proposed Patch (Unified Diff)
                      </h4>
                      <button
                        onClick={() => handleCopy(fa.fix_diff, result.id)}
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-semibold transition-colors"
                      >
                        {copiedId === result.id ? (
                          <>
                            <Check className="w-3.5 h-3.5 text-emerald-400" />
                            Copied!
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5" />
                            Copy Patch
                          </>
                        )}
                      </button>
                    </div>

                    <div className="rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs overflow-x-auto p-4 space-y-0.5">
                      {fa.fix_diff.split('\n').map((line, lIdx) => {
                        const isAdd = line.startsWith('+');
                        const isDel = line.startsWith('-');
                        const isInfo = line.startsWith('@');

                        return (
                          <div
                            key={lIdx}
                            className={`px-2 py-0.5 rounded ${
                              isAdd ? 'diff-add' : isDel ? 'diff-del' : isInfo ? 'diff-info' : 'text-slate-400'
                            }`}
                          >
                            {line}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : fa?.suggested_fix ? (
                  <div className="space-y-2">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      Suggested Fix Snippet
                    </h4>
                    <pre className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-emerald-300 font-mono text-xs overflow-x-auto">
                      {fa.suggested_fix}
                    </pre>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="glass-panel p-16 rounded-2xl border border-emerald-500/20 text-center space-y-3">
          <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto" />
          <h3 className="text-lg font-bold text-white">All Tests Passed — Zero Defects</h3>
          <p className="text-sm text-slate-400 max-w-md mx-auto">
            The target firmware satisfied all synthesized boundary, safety, and functional constraints.
          </p>
        </div>
      )}
      {chatPanel}
    </div>
  );
};
