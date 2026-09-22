import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  FileCheck,
  FileCode,
  LayoutDashboard,
  Menu,
  Sparkles,
  Tv,
  X,
} from 'lucide-react';
import { api } from './api';
import { AnalysisView } from './components/AnalysisView';
import { Dashboard } from './components/Dashboard';
import { ExecutionRunner } from './components/ExecutionRunner';
import { FailureInsights } from './components/FailureInsights';
import { FirmwareUpload } from './components/FirmwareUpload';
import { LoadingScreen } from './components/LoadingScreen';
import { Reports } from './components/Reports';
import { TestGenerator } from './components/TestGenerator';
import { VisualCircuitSimulator } from './components/VisualCircuitSimulator';
import { SAMPLE_BUGGY_FILENAME, SAMPLE_BUGGY_SOURCE } from './sampleFirmware';
import type {
  AnalysisResult,
  DashboardStats,
  Firmware,
  HealthStatus,
  TestRun,
  TestSuite,
  FailureAnalysis,
} from './types';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [firmwares, setFirmwares] = useState<Firmware[]>([]);
  const [selectedFirmware, setSelectedFirmware] = useState<Firmware | null>(null);
  const [currentAnalysis, setCurrentAnalysis] = useState<AnalysisResult | null>(null);
  const [currentSuite, setCurrentSuite] = useState<TestSuite | null>(null);
  const [currentRun, setCurrentRun] = useState<TestRun | null>(null);

  const [sidebarExpanded, setSidebarExpanded] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isBooting, setIsBooting] = useState(true);
  const [demoLoading, setDemoLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const showToast = (text: string, type: 'success' | 'error' = 'success') => {
    setToastMessage({ type, text });
    setTimeout(() => setToastMessage(null), 4000);
  };

  const loadInitialData = async () => {
    try {
      const [h, s, fwList] = await Promise.all([
        api.getHealth(),
        api.getDashboard(),
        api.listFirmware(),
      ]);
      setHealth(h);
      setStats(s);
      setFirmwares(fwList);
      if (fwList.length > 0 && !selectedFirmware) {
        setSelectedFirmware(fwList[0]);
      }
    } catch (err: any) {
      console.error('Failed to load initial data:', err);
    }
  };

  useEffect(() => {
    let mounted = true;
    const minimumBoot = new Promise(resolve => window.setTimeout(resolve, 5600));

    Promise.all([loadInitialData(), minimumBoot]).finally(() => {
      if (mounted) setIsBooting(false);
    });

    return () => {
      mounted = false;
    };
  }, []);

  // Demo Runner Action
  const handleRunDemo = async (variant: 'buggy' | 'golden') => {
    setDemoLoading(true);
    try {
      const run = await api.runDemo({ variant, max_tests: 8, use_llm: true });
      setCurrentRun(run);

      // Refresh stats & firmwares
      const [s, fwList] = await Promise.all([api.getDashboard(), api.listFirmware()]);
      setStats(s);
      setFirmwares(fwList);

      const fw = fwList.find(f => f.id === run.firmware_id) || fwList[0];
      setSelectedFirmware(fw);

      // Load analysis and suite for the run
      const [analyses, suite] = await Promise.all([
        api.getFirmwareAnalyses(fw.id),
        api.getTestSuite(run.suite_id),
      ]);
      if (analyses.length > 0) setCurrentAnalysis(analyses[0]);
      setCurrentSuite(suite);

      showToast(`Demo completed! Pass Rate: ${run.pass_rate}%.`, run.pass_rate === 100 ? 'success' : 'error');
      setActiveTab('runner');
      return run;
    } catch (err: any) {
      showToast(err.message || 'Demo run failed', 'error');
      return null;
    } finally {
      setDemoLoading(false);
    }
  };

  const handleRunAiDebugDemo = async () => {
    setDemoLoading(true);
    try {
      const fw = await api.uploadFirmwareText({
        filename: SAMPLE_BUGGY_FILENAME,
        source_code: SAMPLE_BUGGY_SOURCE,
        notes: 'Built-in faulty sample for debugger demo',
      });
      setSelectedFirmware(fw);
      setFirmwares(prev => [fw, ...prev]);

      const analysis = await api.analyzeFirmware(fw.id, true);
      setCurrentAnalysis(analysis);

      const suite = await api.generateTests({
        firmware_id: fw.id,
        analysis_id: analysis.id,
        max_tests: 8,
        focus: 'boundary and safety defects',
        use_llm: true,
      });
      setCurrentSuite(suite);

      const run = await api.runTestSuite({
        suite_id: suite.id,
        auto_analyze_failures: true,
      });
      const analyses = run.failed + run.errored > 0
        ? await api.analyzeFailures(run.id, false)
        : [];
      setCurrentRun(attachAnalysesToRun(run, analyses));

      const [s, fwList] = await Promise.all([api.getDashboard(), api.listFirmware()]);
      setStats(s);
      setFirmwares(fwList);
      setActiveTab('failures');
      showToast(`Debugger demo completed with ${run.failed + run.errored} defect(s).`, run.pass_rate === 100 ? 'success' : 'error');
    } catch (err: any) {
      showToast(err.message || 'Debugger demo failed', 'error');
    } finally {
      setDemoLoading(false);
    }
  };

  const attachAnalysesToRun = (run: TestRun, analyses: FailureAnalysis[]): TestRun => {
    const byResultId = new Map(analyses.map(analysis => [analysis.result_id, analysis]));
    return {
      ...run,
      results: run.results.map(result => ({
        ...result,
        failure_analysis: byResultId.get(result.id) || result.failure_analysis || null,
      })),
    };
  };

  const handleAnalyzeCurrentFailures = async () => {
    if (!currentRun) {
      await handleRunAiDebugDemo();
      return;
    }

    const defectCount = currentRun.failed + currentRun.errored;
    if (defectCount === 0) {
      showToast('No failed tests to debug. Run the buggy demo to create a failure.', 'error');
      return;
    }

    setIsLoading(true);
    try {
      const analyses = await api.analyzeFailures(currentRun.id, true);
      const latestRun = await api.getTestRun(currentRun.id);
      setCurrentRun(attachAnalysesToRun(latestRun, analyses));
      setActiveTab('failures');
      showToast(`Debugger generated ${analyses.length} failure analysis record(s).`);
    } catch (err: any) {
      showToast(err.message || 'AI debugger analysis failed', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  // Upload Handlers
  const handleUploadText = async (payload: { filename: string; source_code: string; notes?: string }) => {
    const fw = await api.uploadFirmwareText(payload);
    setFirmwares(prev => [fw, ...prev]);
    setSelectedFirmware(fw);
    showToast(`Uploaded ${fw.filename}`);
    return fw;
  };

  const handleUploadFile = async (file: File) => {
    const fw = await api.uploadFirmwareFile(file);
    setFirmwares(prev => [fw, ...prev]);
    setSelectedFirmware(fw);
    showToast(`Uploaded ${fw.filename}`);
    return fw;
  };

  const handleDeleteFirmware = async (id: string) => {
    await api.deleteFirmware(id);
    setFirmwares(prev => prev.filter(f => f.id !== id));
    if (selectedFirmware?.id === id) {
      setSelectedFirmware(null);
      setCurrentAnalysis(null);
    }
    showToast('Firmware deleted.');
  };

  // Static Analysis Action
  const handleAnalyze = async (firmwareId: string) => {
    setIsLoading(true);
    try {
      const result = await api.analyzeFirmware(firmwareId, true);
      setCurrentAnalysis(result);
      const fw = firmwares.find(f => f.id === firmwareId) || selectedFirmware;
      if (fw) setSelectedFirmware(fw);
      setActiveTab('analysis');
      showToast('Static analysis completed.');
    } catch (err: any) {
      showToast(err.message || 'Analysis failed', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  // Test Generation Action
  const handleGenerateTests = async (params: { max_tests: number; focus: string; use_llm: boolean }) => {
    if (!selectedFirmware) return;
    setIsLoading(true);
    try {
      const suite = await api.generateTests({
        firmware_id: selectedFirmware.id,
        analysis_id: currentAnalysis?.id,
        max_tests: params.max_tests,
        focus: params.focus,
        use_llm: params.use_llm,
      });
      setCurrentSuite(suite);
      showToast(`Synthesized ${suite.cases.length} test scenarios.`);
    } catch (err: any) {
      showToast(err.message || 'Test generation failed', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  // Run Test Suite Action
  const handleRunSuite = async (suiteId: string) => {
    setIsLoading(true);
    try {
      const run = await api.runTestSuite({ suite_id: suiteId, auto_analyze_failures: true });
      setCurrentRun(run);
      const s = await api.getDashboard();
      setStats(s);
      setActiveTab('runner');
      showToast(`Executed ${run.total} tests in ${run.duration_ms}ms.`);
    } catch (err: any) {
      showToast(err.message || 'Test execution failed', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  // Select Run from History
  const handleSelectRun = async (runId: string) => {
    try {
      const run = await api.getTestRun(runId);
      setCurrentRun(run);
      setActiveTab('runner');
    } catch (err: any) {
      showToast(err.message || 'Could not fetch run', 'error');
    }
  };

  const defectCount = currentRun ? currentRun.failed + currentRun.errored : 0;

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'upload', label: '1. Ingest Firmware', icon: FileCode },
    { id: 'analysis', label: '2. AI Analyses Firmware', icon: Cpu },
    { id: 'testgen', label: '3. Generate Test Scenarios', icon: Sparkles },
    { id: 'runner', label: '4. Hardware Simulator', icon: Activity },
    { id: 'circuit', label: '5. Observe Behaviour', icon: Tv },
    { id: 'failures', label: '6. Identify Failures', icon: Bot, badge: defectCount > 0 ? defectCount : null },
    { id: 'reports', label: '7. Debugging Report', icon: FileCheck },
  ];

  const projectName = selectedFirmware?.filename || currentRun?.firmware_filename || 'No Project Selected';

  const statusItems = [
    { label: 'Backend Online', active: health?.status === 'ok' || health?.status === 'healthy' || Boolean(health) },
    { label: 'Simulator Ready', active: Boolean(health?.simulator_backend) },
    { label: health?.llm_enabled ? 'LLM Connected' : 'Heuristic Mode', active: Boolean(health) },
  ];

  const handleNavigate = (tab: string) => {
    setActiveTab(tab);
    setMobileNavOpen(false);
  };

  if (isBooting) {
    return <LoadingScreen />;
  }

  return (
    <div className="platform-shell">
      <div className="platform-grid" aria-hidden="true" />
      <div className="platform-background-text" aria-hidden="true">
        <span>FIRMAI // AUTONOMOUS FIRMWARE TESTING</span>
        <span>GPIO MAP // AST EXTRACTION // BOUNDARY ANALYSIS</span>
        <span>VIRTUAL MCU // TEST SYNTHESIS // SIMULATION</span>
        <span>ROOT CAUSE // PATCH DIFF // AUDIT REPORT</span>
        <span>UPLOAD FIRMWARE // ANALYZE LOGIC // DEBUG FAILURES</span>
        <span>DETERMINISTIC ASSERTIONS // HARDWARE TELEMETRY</span>
      </div>
      <header className="platform-topbar">
        <div className="platform-brand" onClick={() => handleNavigate('dashboard')}>
          <button
            type="button"
            className="platform-mobile-menu"
            onClick={event => {
              event.stopPropagation();
              setMobileNavOpen(true);
            }}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="platform-logo" aria-hidden="true">
            F
          </div>
          <div>
            <div className="platform-brand-name">FirmAI</div>
            <div className="platform-version">AUTONOMOUS FIRMWARE AGENT</div>
          </div>
        </div>

        <div className="platform-project" title={projectName}>
          <span>PROJECT</span>
          <strong>{projectName}</strong>
        </div>

        <div className="platform-status">
          {statusItems.map(item => (
            <span className={item.active ? 'is-active' : ''} key={item.label}>
              <i />
              {item.label}
            </span>
          ))}
        </div>
      </header>

      <div className="platform-body">
        <aside className={`platform-sidebar ${sidebarExpanded ? 'is-expanded' : 'is-collapsed'}`}>
          <button
            type="button"
            className="platform-sidebar-toggle"
            onClick={() => setSidebarExpanded(value => !value)}
          >
            {sidebarExpanded ? 'COLLAPSE' : 'OPEN'}
          </button>
          <nav className="platform-nav" aria-label="Primary navigation">
            {navItems.map(item => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => handleNavigate(item.id)}
                  className={isActive ? 'is-active' : ''}
                  aria-current={isActive ? 'page' : undefined}
                  title={item.label}
                >
                  <span className="platform-active-bar" />
                  <Icon className="h-5 w-5" />
                  <span className="platform-nav-label">{item.label}</span>
                  {item.badge && <b>{item.badge}</b>}
                </button>
              );
            })}
          </nav>
        </aside>

        {mobileNavOpen && (
          <div className="platform-drawer" role="dialog" aria-modal="true">
            <button
              type="button"
              className="platform-drawer-backdrop"
              onClick={() => setMobileNavOpen(false)}
              aria-label="Close navigation"
            />
            <div className="platform-drawer-panel">
              <div className="platform-drawer-head">
                <span>Navigation</span>
                <button type="button" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <nav className="platform-nav is-mobile" aria-label="Mobile navigation">
                {navItems.map(item => {
                  const Icon = item.icon;
                  const isActive = activeTab === item.id;
                  return (
                    <button
                      type="button"
                      key={item.id}
                      onClick={() => handleNavigate(item.id)}
                      className={isActive ? 'is-active' : ''}
                    >
                      <span className="platform-active-bar" />
                      <Icon className="h-5 w-5" />
                      <span className="platform-nav-label">{item.label}</span>
                      {item.badge && <b>{item.badge}</b>}
                    </button>
                  );
                })}
              </nav>
            </div>
          </div>
        )}

        <main className="platform-workspace">
        {activeTab === 'dashboard' && (
          <Dashboard
            stats={stats}
            health={health}
            isLoading={isLoading}
            onRunDemo={handleRunDemo}
            onNavigateTab={setActiveTab}
            onSelectRun={handleSelectRun}
            demoLoading={demoLoading}
          />
        )}

        {activeTab === 'upload' && (
          <FirmwareUpload
            firmwares={firmwares}
            onUploadText={handleUploadText}
            onUploadFile={handleUploadFile}
            onSelectFirmware={fw => {
              setSelectedFirmware(fw);
              api.getFirmwareAnalyses(fw.id).then(a => {
                if (a.length > 0) setCurrentAnalysis(a[0]);
              });
            }}
            onDeleteFirmware={handleDeleteFirmware}
            onAnalyze={handleAnalyze}
            selectedFirmwareId={selectedFirmware?.id}
          />
        )}

        {activeTab === 'analysis' && (
          <AnalysisView
            analysis={currentAnalysis}
            firmware={selectedFirmware}
            onProceedToTestGen={() => setActiveTab('testgen')}
            isLoading={isLoading}
          />
        )}

        {activeTab === 'testgen' && (
          <TestGenerator
            suite={currentSuite}
            firmware={selectedFirmware}
            onGenerate={handleGenerateTests}
            onRunSuite={handleRunSuite}
            isLoading={isLoading}
            isRunning={isLoading}
          />
        )}

        {activeTab === 'runner' && (
          <ExecutionRunner
            currentRun={currentRun}
            currentSuite={currentSuite}
            firmware={selectedFirmware}
            analysis={currentAnalysis}
            onNavigateToFailures={() => setActiveTab('failures')}
            onRerun={() => currentSuite && handleRunSuite(currentSuite.id)}
            isRunning={isLoading || demoLoading}
          />
        )}

        {activeTab === 'circuit' && (
          <VisualCircuitSimulator
            firmware={selectedFirmware}
            analysis={currentAnalysis}
            currentRun={currentRun}
            currentSuite={currentSuite}
            onNavigateToFailures={() => setActiveTab('failures')}
            onNavigateToTestGen={() => setActiveTab('testgen')}
          />
        )}

        {activeTab === 'failures' && (
          <FailureInsights
            currentRun={currentRun}
            health={health}
            isRunning={isLoading || demoLoading}
            onRunDebugDemo={handleRunAiDebugDemo}
            onAnalyzeCurrentFailures={handleAnalyzeCurrentFailures}
            onNavigateToReports={() => setActiveTab('reports')}
          />
        )}

        {activeTab === 'reports' && <Reports currentRun={currentRun} />}
        </main>
      </div>

      {toastMessage && (
        <div
          className={`platform-toast ${
            toastMessage.type === 'success'
              ? 'is-success'
              : 'is-error'
          }`}
        >
          {toastMessage.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          )}
          <span>{toastMessage.text}</span>
        </div>
      )}
    </div>
  );
};
