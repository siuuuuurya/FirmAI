export interface HealthStatus {
  status: string;
  version: string;
  llm_enabled: boolean;
  llm_provider: string;
  llm_model: string;
  simulator_backend: string;
  compiler_available: boolean;
}

export interface Firmware {
  id: string;
  filename: string;
  language: string;
  size_bytes: number;
  sha256: string;
  origin: string;
  notes: string;
  created_at: string;
  analysis_count: number;
  suite_count: number;
  run_count: number;
  source_code?: string;
}

export interface AnalysisResult {
  id: string;
  firmware_id: string;
  inputs: Array<{
    symbol: string;
    pin: number | string;
    kind: string;
    role: string;
    range: [number, number];
    transfer_function?: {
      scale: number;
      offset: number;
      unit: string;
    };
  }>;
  outputs: Array<{
    symbol: string;
    pin: number | string;
    kind: string;
    role: string;
  }>;
  gpio_pins: Array<{
    pin: number | string;
    symbol: string;
    direction: string;
  }>;
  constants: Array<{
    name: string;
    type: string;
    numeric: number | null;
  }>;
  thresholds: Array<{
    expression: string;
    operator: string;
    value: number;
    symbol?: string;
    line_number: number;
  }>;
  states: Array<{
    enum: string;
    members: Array<{ name: string; value: number }>;
  }>;
  conditions: Array<{
    line: number;
    condition: string;
  }>;
  functions: Array<{
    name: string;
    return_type: string;
    length_lines: number;
  }>;
  serial_prints: Array<{
    line: number;
    text: string;
    protocol_keys: string[];
  }>;
  risk_areas: Array<{
    kind: string;
    title: string;
    description: string;
    severity: string;
    line_number: number;
  }>;
  metrics: {
    total_lines: number;
    code_lines: number;
    comment_lines: number;
    branch_count: number;
    cyclomatic_complexity: number;
    max_function_length: number;
  };
  signal_map: {
    stimulus_channels: any[];
    observable_outputs: any[];
    telemetry_keys: string[];
    primary_input?: string;
    named_thresholds?: Record<string, number>;
  };
  summary: string;
  analyzer_version: string;
  duration_ms: number;
  created_at: string;
}

export interface TestCase {
  id: string;
  test_id: string;
  name: string;
  description: string;
  category: string;
  priority: string;
  requirement: string;
  rationale: string;
  derived_from: string[];
  stimulus: {
    ticks: number;
    tick_ms: number;
    events: Array<{
      tick: number;
      channel: string;
      unit: string;
      value: number;
    }>;
  };
  expectations: Array<{
    id: string;
    kind: string;
    target: string;
    operator: string;
    value: any;
    at_tick: number;
    description: string;
  }>;
  timeout_ms: number;
  order_index: number;
}

export interface TestSuite {
  id: string;
  firmware_id: string;
  analysis_id?: string;
  name: string;
  strategy_notes: string;
  coverage_notes: string;
  generator_engine: string;
  generator_model: string;
  generation_ms: number;
  created_at: string;
  cases: TestCase[];
}

export interface FailureAnalysis {
  id: string;
  result_id: string;
  run_id: string;
  root_cause: string;
  explanation: string;
  category: string;
  severity: string;
  confidence: number;
  suspect_lines: number[];
  code_snippet: string;
  suggested_fix: string;
  fix_diff: string;
  evidence: string[];
  engine: string;
  model: string;
  duration_ms: number;
  created_at: string;
}

export interface TestResult {
  id: string;
  run_id: string;
  case_id: string;
  test_id: string;
  name: string;
  category: string;
  priority: string;
  rationale: string;
  status: 'PASS' | 'FAIL' | 'ERROR' | 'SKIP';
  stimulus: any;
  expectations: any[];
  assertions: Array<{
    id: string;
    kind: string;
    target: string;
    operator: string;
    at_tick: number;
    description: string;
    expected: any;
    actual: any;
    outcome: 'PASS' | 'FAIL' | 'ERROR';
    message: string;
  }>;
  observed: {
    final_pins?: Record<string, any>;
    telemetry_records?: Array<Record<string, string>>;
    telemetry_count?: number;
    ticks_executed?: number;
    simulated_ms?: number;
    wall_ms?: number;
    backend?: string;
  };
  serial_log: string;
  trace: Array<{
    t: number;
    ms: number;
    pins: Record<string, any>;
  }>;
  duration_ms: number;
  error_message: string;
  order_index: number;
  failure_analysis?: FailureAnalysis | null;
}

export interface TestRun {
  id: string;
  firmware_id: string;
  suite_id: string;
  status: string;
  stage: string;
  progress: number;
  simulator_backend: string;
  execution_mode: string;
  total: number;
  passed: number;
  failed: number;
  errored: number;
  skipped: number;
  pass_rate: number;
  duration_ms: number;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  error_message: string;
  is_demo: boolean;
  build_log: string;
  firmware_filename: string;
  results: TestResult[];
}

export interface DashboardStats {
  firmware_count: number;
  suite_count: number;
  test_case_count: number;
  run_count: number;
  total_tests_executed: number;
  total_passed: number;
  total_failed: number;
  total_errored: number;
  overall_pass_rate: number;
  open_failures: number;
  ai_analyses: number;
  recent_runs: Array<{
    id: string;
    firmware_id: string;
    suite_id: string;
    status: string;
    total: number;
    passed: number;
    failed: number;
    pass_rate: number;
    created_at: string;
    is_demo: boolean;
  }>;
  pass_rate_trend: Array<{
    run_id: string;
    date: string;
    pass_rate: number;
  }>;
  category_breakdown: Array<{
    category: string;
    total: number;
    passed: number;
    failed: number;
  }>;
  severity_breakdown: Array<{
    severity: string;
    count: number;
  }>;
  status_distribution: Array<{
    status: string;
    count: number;
    color: string;
  }>;
}
