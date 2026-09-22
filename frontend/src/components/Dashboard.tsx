import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowRight,
  Bot,
  CheckCircle2,
  Cpu,
  FileCode,
  FileText,
  Play,
  RotateCcw,
  Tv,
  Upload,
} from 'lucide-react';
import type { DashboardStats, HealthStatus } from '../types';

interface DashboardProps {
  stats: DashboardStats | null;
  health: HealthStatus | null;
  isLoading: boolean;
  onRunDemo: (variant: 'buggy' | 'golden') => void;
  onNavigateTab: (tab: string) => void;
  onSelectRun: (runId: string) => void;
  demoLoading: boolean;
}

const pipeline = [
  '1. Provide Firmware',
  '2. AI Analyses Firmware',
  '3. Generate Test Scenarios',
  '4. Virtual Hardware Run',
  '5. Observe Behaviour',
  '6. Identify Failures',
  '7. Debugging Report',
];

const statusText = (value: boolean, online = 'READY', offline = 'WAITING') => value ? online : offline;

export const Dashboard: React.FC<DashboardProps> = ({
  stats,
  health,
  onRunDemo,
  onNavigateTab,
  onSelectRun,
  demoLoading,
}) => {
  const [animated, setAnimated] = useState({
    firmware: 0,
    tests: 0,
    pass: 0,
    reports: 0,
  });

  const targets = useMemo(() => ({
    firmware: stats?.firmware_count ?? 0,
    tests: stats?.test_case_count ?? 0,
    pass: stats?.overall_pass_rate ?? 0,
    reports: stats?.run_count ?? 0,
  }), [stats]);

  useEffect(() => {
    const start = performance.now();
    const duration = 850;
    let frame = 0;

    const tick = (now: number) => {
      const ratio = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - ratio, 3);
      setAnimated({
        firmware: Math.round(targets.firmware * eased),
        tests: Math.round(targets.tests * eased),
        pass: Math.round(targets.pass * eased),
        reports: Math.round(targets.reports * eased),
      });
      if (ratio < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [targets]);

  const metrics = [
    { label: 'Firmware Uploaded', value: animated.firmware, meta: 'Source artifacts', icon: FileCode },
    { label: 'Tests Generated', value: animated.tests, meta: `${stats?.total_tests_executed ?? 0} executed`, icon: Activity },
    { label: 'Pass Rate', value: `${animated.pass}%`, meta: `${stats?.total_passed ?? 0} pass / ${stats?.total_failed ?? 0} fail`, icon: CheckCircle2 },
    { label: 'Reports Created', value: animated.reports, meta: `${stats?.ai_analyses ?? 0} AI analyses`, icon: FileText },
  ];

  const activity = stats?.recent_runs?.length
    ? stats.recent_runs.slice(0, 4).map(run => ({
        time: new Date(run.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        title: run.pass_rate === 100 ? 'Simulation passed' : 'Simulation flagged defects',
        detail: `${run.passed}P / ${run.failed}F across ${run.total} tests`,
        runId: run.id,
      }))
    : [
        { time: '10:42', title: 'Firmware uploaded', detail: 'Sketch received by ingestion pipeline' },
        { time: '10:43', title: 'Analysis completed', detail: 'GPIO, thresholds, and state model extracted' },
        { time: '10:45', title: 'Test suite generated', detail: 'Boundary and safety cases synthesized' },
        { time: '10:47', title: 'Simulation executed', detail: 'Virtual MCU assertions evaluated' },
      ];

  return (
    <div className="command-center page-fade">
      <section className="workspace-hero">
        <div>
          <span className="eyebrow">AUTONOMOUS EMBEDDED SYSTEMS</span>
          <h1>FIRMWARE COMMAND CENTER</h1>
          <p>Autonomous Analysis, Testing and Debugging Platform</p>
        </div>
        <div className="workspace-health">
          <span>
            <i className="status-dot" />
            API {statusText(Boolean(health))}
          </span>
          <span>
            <i className="status-dot" />
            {health?.simulator_backend || 'local_deterministic'}
          </span>
          <span>
            <i className="status-dot" />
            {health?.llm_enabled ? `${health.llm_provider}:${health.llm_model}` : 'Deterministic'}
          </span>
        </div>
      </section>

      <section className="metric-strip" aria-label="Primary platform metrics">
        {metrics.map(metric => {
          const Icon = metric.icon;
          return (
            <button type="button" className="metric-block" key={metric.label}>
              <Icon className="h-4 w-4" />
              <strong>{metric.value}</strong>
              <span>{metric.label}</span>
              <small>{metric.meta}</small>
            </button>
          );
        })}
      </section>

      <section className="command-grid">
        <div className="platform-panel recent-activity">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">TIMELINE</span>
              <h2>Recent Activity</h2>
            </div>
            <button type="button" onClick={() => onNavigateTab('runner')}>
              Open Runs
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="timeline">
            {activity.map((item, index) => (
              <button
                type="button"
                key={`${item.time}-${item.title}-${index}`}
                onClick={() => 'runId' in item && item.runId ? onSelectRun(item.runId) : undefined}
              >
                <time>{item.time}</time>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="platform-panel system-overview">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">SYSTEM OVERVIEW</span>
              <h2>Live Firmware Pipeline</h2>
            </div>
            <Cpu className="h-5 w-5" />
          </div>

          <div className="architecture-flow" aria-label="FirmAI architecture pipeline">
            <span className="pipeline-pulse" />
            {pipeline.map(step => (
              <div className="architecture-node" key={step}>
                {step}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="platform-panel quick-actions">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">OPERATIONS</span>
            <h2>Quick Actions</h2>
          </div>
          <span className="command-hint">Upload {'>'} Analyze {'>'} Generate {'>'} Simulate {'>'} Report</span>
        </div>

        <div className="action-row">
          <button type="button" onClick={() => onNavigateTab('upload')}>
            <Upload className="h-4 w-4" />
            Upload Firmware
          </button>
          <button type="button" onClick={() => onRunDemo('buggy')} disabled={demoLoading}>
            {demoLoading ? <RotateCcw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run Demo
          </button>
          <button type="button" onClick={() => onNavigateTab('testgen')}>
            <Bot className="h-4 w-4" />
            Generate Tests
          </button>
          <button type="button" onClick={() => onNavigateTab('runner')}>
            <Cpu className="h-4 w-4" />
            Run Simulation
          </button>
          <button type="button" onClick={() => onNavigateTab('circuit')}>
            <Tv className="h-4 w-4" />
            Visual Bench
          </button>
        </div>
      </section>
    </div>
  );
};
