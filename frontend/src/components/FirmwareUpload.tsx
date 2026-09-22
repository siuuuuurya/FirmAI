import React, { useState } from 'react';
import {
  Code,
  FileCode,
  FileText,
  Play,
  Sparkles,
  Trash2,
  UploadCloud,
} from 'lucide-react';
import {
  FIRMWARE_PRESETS,
  FirmwarePreset,
  SAMPLE_BUGGY_FILENAME,
  SAMPLE_BUGGY_SOURCE,
} from '../sampleFirmware';
import type { Firmware } from '../types';

interface FirmwareUploadProps {
  firmwares: Firmware[];
  onUploadText: (payload: { filename: string; source_code: string; notes?: string }) => Promise<Firmware>;
  onUploadFile: (file: File) => Promise<Firmware>;
  onSelectFirmware: (fw: Firmware) => void;
  onDeleteFirmware: (id: string) => Promise<void>;
  onAnalyze: (firmwareId: string) => void | Promise<void>;
  selectedFirmwareId?: string;
}

export const FirmwareUpload: React.FC<FirmwareUploadProps> = ({
  firmwares,
  onUploadText,
  onUploadFile,
  onSelectFirmware,
  onDeleteFirmware,
  onAnalyze,
  selectedFirmwareId,
}) => {
  const [filename, setFilename] = useState(SAMPLE_BUGGY_FILENAME);
  const [code, setCode] = useState(SAMPLE_BUGGY_SOURCE);
  const [isUploading, setIsUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const handleSaveAndAnalyze = async () => {
    if (!code.trim()) return;
    setIsUploading(true);
    try {
      const fw = await onUploadText({
        filename: filename || 'firmware.ino',
        source_code: code,
        notes: 'User submitted sketch',
      });
      onSelectFirmware(fw);
      await onAnalyze(fw.id);
    } finally {
      setIsUploading(false);
    }
  };

  const handleSelectPreset = async (preset: FirmwarePreset, autoAnalyze = false) => {
    setFilename(preset.filename);
    setCode(preset.code);
    if (autoAnalyze) {
      setIsUploading(true);
      try {
        const fw = await onUploadText({
          filename: preset.filename,
          source_code: preset.code,
          notes: preset.description,
        });
        onSelectFirmware(fw);
        await onAnalyze(fw.id);
      } finally {
        setIsUploading(false);
      }
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      const text = await file.text();
      setFilename(file.name);
      setCode(text);
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono font-bold uppercase tracking-widest text-sky-400">Step 1 of 7: Sequence Demonstration</span>
          <h2 className="text-2xl font-extrabold text-white flex items-center gap-2">
            <FileCode className="w-6 h-6 text-sky-400" />
            Provide Embedded Firmware to System
          </h2>
          <p className="text-slate-400 text-sm">
            Ingest embedded C/C++ firmware (.ino / .cpp) for autonomous AST analysis, test synthesis, and hardware simulation.
          </p>
        </div>
      </div>

      {/* Preset Firmware Selectors */}
      <div className="bg-slate-900/90 border border-slate-800 p-4 rounded-xl space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            Benchmark Firmware Presets (1-Click Load & Run)
          </span>
          <span className="text-[11px] text-slate-500 font-mono">Select preset to populate or auto-analyze</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
          {FIRMWARE_PRESETS.map(preset => {
            const isSelected = filename === preset.filename;
            const isBuggy = preset.variant === 'buggy';
            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => handleSelectPreset(preset, false)}
                className={`text-left p-3 rounded-lg border transition-all ${
                  isSelected
                    ? 'border-sky-500 bg-sky-950/40 shadow-sm shadow-sky-500/20'
                    : 'border-slate-800 bg-slate-950/60 hover:border-slate-700 hover:bg-slate-800/50'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded font-mono ${
                    isBuggy ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  }`}>
                    {isBuggy ? 'DEFECTS PLANTED' : 'GOLDEN REF'}
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">{preset.filename}</span>
                </div>
                <div className="text-xs font-bold text-slate-200 line-clamp-1">{preset.name}</div>
                <p className="text-[11px] text-slate-400 mt-1 line-clamp-2 leading-relaxed">{preset.description}</p>
              </button>
            );
          })}
        </div>
      </div>

      {/* Editor & Dropzone Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Code Editor */}
        <div className="lg:col-span-2 glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-400 uppercase">Filename:</span>
              <input
                type="text"
                value={filename}
                onChange={e => setFilename(e.target.value)}
                className="bg-slate-900 border border-slate-700 text-xs font-mono font-semibold px-3 py-1.5 rounded-lg text-slate-200 focus:outline-none focus:border-sky-500 w-64"
                placeholder="firmware.ino"
              />
            </div>

            <button
              onClick={handleSaveAndAnalyze}
              disabled={isUploading || !code.trim()}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-bold text-xs shadow-md shadow-sky-500/20 transition-all disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              {isUploading ? 'Analyzing...' : 'Ingest & Run AST Analysis'}
            </button>
          </div>

          <div
            onDragOver={e => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`relative rounded-xl border transition-all ${
              dragOver ? 'border-sky-500 bg-sky-500/10' : 'border-slate-800 bg-slate-950/80'
            }`}
          >
            <textarea
              value={code}
              onChange={e => setCode(e.target.value)}
              rows={18}
              className="w-full bg-transparent p-4 font-mono text-xs text-slate-200 focus:outline-none resize-y leading-relaxed"
              placeholder="// Paste or write embedded C/C++ firmware here..."
            />
          </div>
        </div>

        {/* Upload & Repository History */}
        <div className="space-y-6">
          {/* Dropzone Box */}
          <div
            onDragOver={e => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className="glass-panel p-6 rounded-2xl border border-dashed border-slate-700 hover:border-sky-500/50 transition-all text-center space-y-3 cursor-pointer"
            onClick={() => {
              const input = document.createElement('input');
              input.type = 'file';
              input.accept = '.ino,.cpp,.c,.h';
              input.onchange = async (e: any) => {
                if (e.target.files && e.target.files.length > 0) {
                  const file = e.target.files[0];
                  const text = await file.text();
                  setFilename(file.name);
                  setCode(text);
                }
              };
              input.click();
            }}
          >
            <div className="w-12 h-12 mx-auto rounded-full bg-sky-500/10 text-sky-400 flex items-center justify-center">
              <UploadCloud className="w-6 h-6" />
            </div>
            <div>
              <p className="text-xs font-bold text-slate-200">Drag & Drop Firmware File</p>
              <p className="text-[11px] text-slate-400 mt-1">Supports .ino, .cpp, .c, .h</p>
            </div>
          </div>

          {/* Uploaded Repository */}
          <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <FileText className="w-4 h-4 text-slate-400" />
              Stored Firmware Builds ({firmwares.length})
            </h3>

            {firmwares.length > 0 ? (
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {firmwares.map(fw => (
                  <div
                    key={fw.id}
                    className={`p-3 rounded-xl border text-xs transition-all flex items-center justify-between gap-2 ${
                      selectedFirmwareId === fw.id
                        ? 'bg-sky-500/15 border-sky-500/40 text-sky-200'
                        : 'bg-slate-900/60 border-slate-800 hover:border-slate-700 text-slate-300'
                    }`}
                  >
                    <div
                      className="cursor-pointer truncate flex-1"
                      onClick={() => onSelectFirmware(fw)}
                    >
                      <div className="font-mono font-bold truncate">{fw.filename}</div>
                      <div className="text-[10px] text-slate-500 mt-0.5">
                        {fw.size_bytes}B • {new Date(fw.created_at).toLocaleTimeString()}
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => onAnalyze(fw.id)}
                        className="px-2 py-1 rounded bg-slate-800 hover:bg-sky-600 text-slate-200 text-[11px] font-semibold"
                      >
                        Analyze
                      </button>
                      <button
                        onClick={() => onDeleteFirmware(fw.id)}
                        className="p-1 rounded text-slate-500 hover:text-rose-400 transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-6 text-slate-500 text-xs">
                No firmware uploaded yet.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
