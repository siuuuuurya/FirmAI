import type {
  AnalysisResult,
  DashboardStats,
  FailureAnalysis,
  Firmware,
  HealthStatus,
  TestRun,
  TestSuite,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}: ${res.statusText}`;
    try {
      const err = await res.json();
      errorDetail = err.detail || errorDetail;
    } catch {
      // Non-JSON response
    }
    throw new Error(errorDetail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // System
  getHealth: () => fetch(`${API_BASE}/health`).then(r => handleResponse<HealthStatus>(r)),
  getSettings: () => fetch(`${API_BASE}/settings`).then(r => handleResponse<any>(r)),
  getDashboard: () => fetch(`${API_BASE}/dashboard`).then(r => handleResponse<DashboardStats>(r)),

  // Firmware
  listFirmware: () => fetch(`${API_BASE}/firmware`).then(r => handleResponse<Firmware[]>(r)),
  getFirmware: (id: string) => fetch(`${API_BASE}/firmware/${id}`).then(r => handleResponse<Firmware>(r)),
  deleteFirmware: (id: string) =>
    fetch(`${API_BASE}/firmware/${id}`, { method: 'DELETE' }).then(r => handleResponse<{ message: string }>(r)),

  uploadFirmwareFile: (file: File) => {
    const data = new FormData();
    data.append('file', file);
    return fetch(`${API_BASE}/firmware/upload`, {
      method: 'POST',
      body: data,
    }).then(r => handleResponse<Firmware>(r));
  },

  uploadFirmwareText: (payload: { filename: string; source_code: string; notes?: string }) =>
    fetch(`${API_BASE}/firmware/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => handleResponse<Firmware>(r)),

  runIntegratedSystemTest: (payload: {
    filename: string;
    source_code: string;
    notes?: string;
    max_tests?: number;
    focus?: string;
    use_llm?: boolean;
    simulator_backend?: string;
    auto_analyze_failures?: boolean;
  }) =>
    fetch(`${API_BASE}/ist/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => handleResponse<TestRun>(r)),

  // Static Analysis
  analyzeFirmware: (firmwareId: string, force: boolean = false) =>
    fetch(`${API_BASE}/firmware/${firmwareId}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    }).then(r => handleResponse<AnalysisResult>(r)),

  getFirmwareAnalyses: (firmwareId: string) =>
    fetch(`${API_BASE}/firmware/${firmwareId}/analyses`).then(r => handleResponse<AnalysisResult[]>(r)),

  // Test Generation
  generateTests: (params: {
    firmware_id: string;
    analysis_id?: string;
    max_tests?: number;
    focus?: string;
    use_llm?: boolean;
  }) =>
    fetch(`${API_BASE}/tests/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        firmware_id: params.firmware_id,
        analysis_id: params.analysis_id,
        max_tests: params.max_tests ?? 8,
        focus: params.focus ?? '',
        use_llm: params.use_llm ?? true,
      }),
    }).then(r => handleResponse<TestSuite>(r)),

  getTestSuite: (suiteId: string) =>
    fetch(`${API_BASE}/tests/suites/${suiteId}`).then(r => handleResponse<TestSuite>(r)),

  // Simulator Execution
  runTestSuite: (params: {
    suite_id: string;
    simulator_backend?: string;
    auto_analyze_failures?: boolean;
  }) =>
    fetch(`${API_BASE}/tests/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        suite_id: params.suite_id,
        simulator_backend: params.simulator_backend,
        auto_analyze_failures: params.auto_analyze_failures ?? true,
      }),
    }).then(r => handleResponse<TestRun>(r)),

  getTestRun: (runId: string) =>
    fetch(`${API_BASE}/tests/runs/${runId}`).then(r => handleResponse<TestRun>(r)),

  // AI Failure Diagnostics
  analyzeFailures: (runId: string, force: boolean = false) =>
    fetch(`${API_BASE}/failures/${runId}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    }).then(r => handleResponse<FailureAnalysis[]>(r)),

  getFailures: (runId: string) =>
    fetch(`${API_BASE}/failures/${runId}`).then(r => handleResponse<FailureAnalysis[]>(r)),

  // Reports
  getReport: (runId: string) =>
    fetch(`${API_BASE}/reports/${runId}`).then(r => handleResponse<any>(r)),

  getReportHtmlUrl: (runId: string) => `${API_BASE}/reports/${runId}/html`,

  // 1-Click Autonomous Demo
  runDemo: (params?: { variant?: 'buggy' | 'golden'; max_tests?: number; use_llm?: boolean }) =>
    fetch(`${API_BASE}/demo/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        variant: params?.variant ?? 'buggy',
        max_tests: params?.max_tests ?? 8,
        use_llm: params?.use_llm ?? true,
      }),
    }).then(r => handleResponse<TestRun>(r)),
};
