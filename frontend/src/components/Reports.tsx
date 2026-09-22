import React, { useState } from 'react';
import {
  Activity,
  Bot,
  CheckCircle2,
  Download,
  ExternalLink,
  FileCheck,
  FileText,
  ShieldCheck,
  Terminal,
  XCircle,
} from 'lucide-react';
import { api } from '../api';
import type { TestRun } from '../types';

interface ReportsProps {
  currentRun: TestRun | null;
}

export const Reports: React.FC<ReportsProps> = ({ currentRun }) => {
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);

  if (!currentRun) {
    return (
      <div className="report-workspace animate-fadeIn">
        <section className="workspace-hero">
          <div>
            <span className="eyebrow">AUDIT OUTPUT</span>
            <h1>REPORTS</h1>
            <p>Generate and inspect executive-ready firmware diagnostics.</p>
          </div>
        </section>

        <div className="platform-panel report-empty">
          <FileCheck className="w-12 h-12 mx-auto" />
          <h3>No Report Generated Yet</h3>
          <p>Execute a simulation run to produce a native audit preview and exportable HTML package.</p>
        </div>
      </div>
    );
  }

  const htmlUrl = api.getReportHtmlUrl(currentRun.id);
  const failed = currentRun.failed + currentRun.errored;
  const generatedAt = new Date(currentRun.finished_at || currentRun.created_at).toLocaleString();
  const selectedResult = currentRun.results.find(result => result.id === selectedResultId) || currentRun.results[0];
  const failedResults = currentRun.results.filter(result => result.status === 'FAIL' || result.status === 'ERROR');
  const telemetryRecords = selectedResult?.observed?.telemetry_records?.slice(0, 6) || [];

  const reportMetrics = [
    { label: 'Pass Rate', value: `${currentRun.pass_rate}%`, meta: `${currentRun.passed} passed / ${failed} flagged` },
    { label: 'Assertions', value: currentRun.total, meta: `${currentRun.results.length} result records` },
    { label: 'Duration', value: `${currentRun.duration_ms}ms`, meta: currentRun.simulator_backend },
    { label: 'Defects', value: failed, meta: currentRun.pass_rate === 100 ? 'No open failures' : 'Requires review' },
  ];

  const reportSections = [
    'Execution summary',
    'Firmware context',
    'Test coverage matrix',
    'Assertion telemetry',
    'Failure diagnostics',
    'Recommended patch evidence',
  ];

  return (
    <div className="report-workspace animate-fadeIn">
      <section className="workspace-hero report-hero">
        <div>
          <span className="eyebrow">AUDIT OUTPUT</span>
          <h1>REPORTS</h1>
          <p>Executive Diagnostic Audit for {currentRun.firmware_filename || 'firmware.ino'}</p>
        </div>

        <div className="report-actions">
          <a
            href={htmlUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Open in New Tab
          </a>

          <a
            href={htmlUrl}
            download={`firmware_audit_${currentRun.id.slice(0, 8)}.html`}
          >
            <Download className="w-3.5 h-3.5" />
            Download HTML Report
          </a>
        </div>
      </section>

      <section className="metric-strip" aria-label="Report metrics">
        {reportMetrics.map(metric => (
          <div className="metric-block" key={metric.label}>
            <strong>{metric.value}</strong>
            <span>{metric.label}</span>
            <small>{metric.meta}</small>
          </div>
        ))}
      </section>

      <section className="report-grid">
        <div className="platform-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">REPORT PACKAGE</span>
              <h2>Audit Manifest</h2>
            </div>
            <FileText className="h-5 w-5" />
          </div>

          <div className="report-manifest">
            <div>
              <span>Run ID</span>
              <strong>{currentRun.id.slice(0, 8)}</strong>
            </div>
            <div>
              <span>Generated</span>
              <strong>{generatedAt}</strong>
            </div>
            <div>
              <span>Mode</span>
              <strong>{currentRun.execution_mode || 'deterministic'}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{currentRun.pass_rate === 100 ? 'Audit clean' : 'Defects detected'}</strong>
            </div>
          </div>
        </div>

        <div className="platform-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">CONTENTS</span>
              <h2>Report Sections</h2>
            </div>
            <ShieldCheck className="h-5 w-5" />
          </div>

          <div className="report-section-list">
            {reportSections.map((section, index) => (
              <div key={section}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{section}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="platform-panel report-preview-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">LIVE PREVIEW</span>
            <h2>Native Audit Interface</h2>
          </div>
          <div className="report-preview-status">
            <Activity className="h-4 w-4" />
            <span>{currentRun.total} tests</span>
            <Bot className="h-4 w-4" />
            <span>{failed} defects</span>
            <Terminal className="h-4 w-4" />
            <span>{currentRun.simulator_backend}</span>
          </div>
        </div>

        <div className="native-report">
          <div className="native-report-summary">
            <div>
              <span>Firmware</span>
              <strong>{currentRun.firmware_filename || 'firmware.ino'}</strong>
            </div>
            <div>
              <span>Verdict</span>
              <strong>{currentRun.pass_rate === 100 ? 'Release candidate clean' : 'Engineering review required'}</strong>
            </div>
            <div>
              <span>Simulation</span>
              <strong>{currentRun.simulator_backend}</strong>
            </div>
          </div>

          <div className="native-report-grid">
            <div className="native-report-results">
              <div className="native-report-title">
                <span>Result Matrix</span>
                <strong>{currentRun.results.length} cases</strong>
              </div>
              <div className="native-result-list">
                {currentRun.results.map(result => {
                  const isSelected = selectedResult?.id === result.id;
                  const isPass = result.status === 'PASS';

                  return (
                    <button
                      type="button"
                      key={result.id}
                      className={isSelected ? 'is-selected' : ''}
                      onClick={() => setSelectedResultId(result.id)}
                    >
                      <span>{result.test_id}</span>
                      <strong>{result.name}</strong>
                      <em className={isPass ? 'is-pass' : 'is-fail'}>
                        {isPass ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                        {result.status}
                      </em>
                    </button>
                  );
                })}
              </div>
            </div>

            {selectedResult && (
              <div className="native-report-inspector">
                <div className="native-report-title">
                  <span>Test Inspector</span>
                  <strong>{selectedResult.test_id}</strong>
                </div>

                <div className="native-inspector-head">
                  <div>
                    <span>{selectedResult.category || 'functional'}</span>
                    <h3>{selectedResult.name}</h3>
                  </div>
                  <b className={selectedResult.status === 'PASS' ? 'is-pass' : 'is-fail'}>{selectedResult.status}</b>
                </div>

                <div className="native-report-block">
                  <span>Rationale</span>
                  <p>{selectedResult.rationale || 'No rationale supplied for this generated test case.'}</p>
                </div>

                <div className="native-assertion-list">
                  <span>Assertions</span>
                  {selectedResult.assertions?.length ? (
                    selectedResult.assertions.map(assertion => (
                      <div key={assertion.id || `${assertion.target}-${assertion.description}`}>
                        <strong>{assertion.target}</strong>
                        <p>{assertion.message || assertion.description}</p>
                        <em className={assertion.outcome === 'PASS' ? 'is-pass' : 'is-fail'}>
                          {assertion.outcome} / expected {String(assertion.expected)} / observed {String(assertion.actual)}
                        </em>
                      </div>
                    ))
                  ) : (
                    <p>No assertion records were emitted.</p>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="native-report-grid native-report-grid--lower">
            <div className="native-report-results">
              <div className="native-report-title">
                <span>Failure Diagnostics</span>
                <strong>{failedResults.length} flagged</strong>
              </div>
              <div className="native-failure-list">
                {failedResults.length ? (
                  failedResults.map(result => (
                    <div key={result.id}>
                      <span>{result.test_id}</span>
                      <strong>{result.failure_analysis?.root_cause || result.error_message || 'Assertion constraint failed'}</strong>
                      <p>{result.failure_analysis?.explanation || 'Review observed telemetry and failed assertion values.'}</p>
                    </div>
                  ))
                ) : (
                  <div>
                    <span>CLEAR</span>
                    <strong>No failed or errored test cases.</strong>
                    <p>The generated suite completed without defect diagnostics.</p>
                  </div>
                )}
              </div>
            </div>

            <div className="native-report-inspector">
              <div className="native-report-title">
                <span>Telemetry Snapshot</span>
                <strong>{selectedResult?.observed?.telemetry_count || telemetryRecords.length} records</strong>
              </div>
              <div className="native-telemetry">
                {telemetryRecords.length ? (
                  telemetryRecords.map((record, index) => (
                    <div key={index}>
                      {Object.entries(record).slice(0, 5).map(([key, value]) => (
                        <span key={key}>{key}: {String(value)}</span>
                      ))}
                    </div>
                  ))
                ) : selectedResult?.serial_log ? (
                  <pre>{selectedResult.serial_log}</pre>
                ) : (
                  <p>No telemetry emitted for the selected case.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};
