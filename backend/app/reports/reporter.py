"""
Report Generator
================
Synthesizes styled, executive-ready HTML & JSON audit reports from test run results.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import REPORT_DIR


class ReportGenerator:
    """Produces self-contained, high-fidelity audit reports."""

    def generate_report_data(
        self,
        run_data: dict[str, Any],
        firmware_data: dict[str, Any],
        analysis_data: dict[str, Any] | None = None,
        suite_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compile structured JSON audit data."""
        results = run_data.get("results") or []
        total = len(results)
        passed = sum(1 for r in results if r.get("status") == "PASS")
        failed = sum(1 for r in results if r.get("status") == "FAIL")
        errored = sum(1 for r in results if r.get("status") == "ERROR")
        skipped = sum(1 for r in results if r.get("status") == "SKIP")
        pass_rate = round((passed / total * 100.0), 1) if total > 0 else 0.0

        if errored > 0 and passed == 0:
            verdict = "ERROR"
        elif failed == 0 and errored == 0 and total > 0:
            verdict = "PASS"
        elif passed > 0 and (failed > 0 or errored > 0):
            verdict = "FAIL" if failed > 0 else "PARTIAL"
        else:
            verdict = "FAIL"

        failures = []
        for r in results:
            if r.get("status") in ("FAIL", "ERROR"):
                fa = r.get("failure_analysis") or {}
                failures.append({
                    "test_id": r.get("test_id"),
                    "name": r.get("name"),
                    "category": r.get("category"),
                    "status": r.get("status"),
                    "assertions": r.get("assertions", []),
                    "root_cause": fa.get("root_cause") or r.get("error_message") or "Assertion failure",
                    "explanation": fa.get("explanation") or "",
                    "severity": fa.get("severity", "medium"),
                    "confidence": fa.get("confidence", 0.8),
                    "suspect_lines": fa.get("suspect_lines", []),
                    "code_snippet": fa.get("code_snippet", ""),
                    "suggested_fix": fa.get("suggested_fix", ""),
                    "fix_diff": fa.get("fix_diff", ""),
                    "evidence": fa.get("evidence", []),
                    "engine": fa.get("engine", "heuristic"),
                })

        recommendations = []
        if failures:
            for f in failures:
                lines_str = f" at line(s) {', '.join(map(str, f['suspect_lines']))}" if f.get("suspect_lines") else ""
                recommendations.append(f"[{f['severity'].upper()}] {f['root_cause']}{lines_str}")
        else:
            recommendations.append("All synthesized boundary, safety, and functional constraints passed. Firmware is verified against the specification.")

        categories = {}
        for r in results:
            cat = r.get("category", "functional")
            categories.setdefault(cat, {"total": 0, "passed": 0, "failed": 0})
            categories[cat]["total"] += 1
            if r.get("status") == "PASS":
                categories[cat]["passed"] += 1
            else:
                categories[cat]["failed"] += 1

        run_id = run_data.get("id", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        return {
            "run_id": run_id,
            "generated_at": now,
            "verdict": verdict,
            "firmware": {
                "id": firmware_data.get("id"),
                "filename": firmware_data.get("filename", "firmware.ino"),
                "size_bytes": firmware_data.get("size_bytes", 0),
                "sha256": firmware_data.get("sha256", ""),
                "metrics": (analysis_data or {}).get("metrics", {}),
                "gpio_pins": (analysis_data or {}).get("gpio_pins", []),
                "thresholds": (analysis_data or {}).get("thresholds", []),
            },
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "errored": errored,
                "skipped": skipped,
                "pass_rate": pass_rate,
                "duration_ms": run_data.get("duration_ms", 0),
                "simulator_backend": run_data.get("simulator_backend", "local_deterministic"),
                "execution_mode": run_data.get("execution_mode", "native-compiled"),
            },
            "coverage": {
                "category_breakdown": categories,
            },
            "results": results,
            "failures": failures,
            "recommendations": recommendations,
            "html_url": f"/api/reports/{run_id}/html",
            "json_url": f"/api/reports/{run_id}",
        }

    def render_html(self, data: dict[str, Any]) -> str:
        """Render complete, responsive, self-contained HTML audit document."""
        verdict = data.get("verdict", "FAIL")
        verdict_color = "#10b981" if verdict == "PASS" else "#ef4444" if verdict == "FAIL" else "#f59e0b"
        verdict_bg = "rgba(16, 185, 129, 0.12)" if verdict == "PASS" else "rgba(239, 68, 68, 0.12)" if verdict == "FAIL" else "rgba(245, 158, 11, 0.12)"

        firmware = data.get("firmware", {})
        summary = data.get("summary", {})
        results = data.get("results", [])
        failures = data.get("failures", [])
        recommendations = data.get("recommendations", [])

        # Build test rows
        rows_html = []
        for r in results:
            status = r.get("status", "UNKNOWN")
            badge_color = "#10b981" if status == "PASS" else "#ef4444" if status == "FAIL" else "#f59e0b"
            badge_bg = "rgba(16, 185, 129, 0.15)" if status == "PASS" else "rgba(239, 68, 68, 0.15)" if status == "FAIL" else "rgba(245, 158, 11, 0.15)"
            
            assertions = r.get("assertions", [])
            ass_passed = sum(1 for a in assertions if a.get("outcome") == "PASS")
            ass_total = len(assertions)

            rows_html.append(f"""
            <tr>
              <td class="font-mono font-bold">{r.get('test_id')}</td>
              <td>{r.get('name')}</td>
              <td><span class="tag">{r.get('category')}</span></td>
              <td><span class="tag">{r.get('priority')}</span></td>
              <td><span class="status-pill" style="color: {badge_color}; background: {badge_bg}; border-color: {badge_color}33;">{status}</span></td>
              <td class="text-right font-mono">{ass_passed}/{ass_total}</td>
              <td class="text-right font-mono">{r.get('duration_ms', 0):.1f}ms</td>
            </tr>
            """)

        # Build failures section
        failures_html = []
        if failures:
            for f in failures:
                diff_html = ""
                if f.get("fix_diff"):
                    diff_lines = []
                    for dl in f["fix_diff"].splitlines():
                        if dl.startswith("+"):
                            diff_lines.append(f'<span class="diff-add">{dl}</span>')
                        elif dl.startswith("-"):
                            diff_lines.append(f'<span class="diff-del">{dl}</span>')
                        elif dl.startswith("@"):
                            diff_lines.append(f'<span class="diff-info">{dl}</span>')
                        else:
                            diff_lines.append(f'<span>{dl}</span>')
                    diff_html = f"""
                    <div class="diff-box">
                      <div class="diff-header">AI Proposed Unified Patch</div>
                      <pre><code>{chr(10).join(diff_lines)}</code></pre>
                    </div>
                    """

                evidence_items = "".join(f"<li>{ev}</li>" for ev in f.get("evidence", []))
                lines_str = f" (Lines: {', '.join(map(str, f.get('suspect_lines', [])))})" if f.get("suspect_lines") else ""

                failures_html.append(f"""
                <div class="failure-card">
                  <div class="failure-header">
                    <span class="failure-title font-mono">{f['test_id']}: {f['name']}</span>
                    <span class="severity-badge sev-{f.get('severity', 'medium')}">{f.get('severity', 'medium').upper()}</span>
                  </div>
                  <p class="root-cause"><strong>Root Cause:</strong> {f['root_cause']}{lines_str}</p>
                  <p class="explanation">{f.get('explanation', '')}</p>
                  {f'<div class="evidence-box"><strong>Observational Evidence:</strong><ul>{evidence_items}</ul></div>' if evidence_items else ''}
                  {diff_html}
                </div>
                """)
        else:
            failures_html.append("""
            <div class="success-card">
              <div style="font-size: 20px; font-weight: 700; color: #10b981; margin-bottom: 8px;">Zero Defects Detected</div>
              <p style="color: #94a3b8; margin: 0;">All synthesized virtual simulator test runs completed with full assertion satisfaction.</p>
            </div>
            """)

        # Recommendations list
        rec_items = "".join(f"<li>{rec}</li>" for rec in recommendations)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FirmAI Diagnostic Audit Report — {firmware.get('filename')}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #111827;
      --card-border: #1f293d;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-rgb: 56, 189, 248;
      --pass: #10b981;
      --fail: #ef4444;
      --warn: #f59e0b;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 40px 24px;
    }}
    .container {{
      max-width: 1100px;
      margin: 0 auto;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 32px;
      flex-wrap: wrap;
      gap: 16px;
    }}
    .logo-badge {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }}
    .logo-badge .icon {{
      width: 36px;
      height: 36px;
      border-radius: 8px;
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      color: #fff;
    }}
    .logo-badge h1 {{
      font-size: 22px;
      font-weight: 800;
      letter-spacing: -0.5px;
    }}
    .verdict-banner {{
      padding: 8px 18px;
      border-radius: 9999px;
      font-weight: 800;
      font-size: 14px;
      letter-spacing: 0.5px;
      border: 1px solid;
    }}
    .grid-stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}
    .stat-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
    }}
    .stat-card .label {{
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 6px;
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: 0.5px;
    }}
    .stat-card .val {{
      font-size: 32px;
      font-weight: 800;
      font-family: 'JetBrains Mono', monospace;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 24px;
      margin-bottom: 28px;
    }}
    .card-title {{
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th {{
      text-align: left;
      padding: 12px 14px;
      color: var(--text-muted);
      border-bottom: 1px solid var(--card-border);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    td {{
      padding: 12px 14px;
      border-bottom: 1px solid rgba(31, 41, 61, 0.5);
    }}
    .text-right {{ text-align: right; }}
    .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
    .font-bold {{ font-weight: 700; }}
    .tag {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.08);
      font-size: 11px;
      color: #cbd5e1;
      text-transform: uppercase;
    }}
    .status-pill {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid;
    }}
    .failure-card {{
      background: rgba(239, 68, 68, 0.04);
      border: 1px solid rgba(239, 68, 68, 0.2);
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 16px;
    }}
    .failure-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }}
    .failure-title {{
      font-size: 15px;
      font-weight: 700;
      color: #fca5a5;
    }}
    .severity-badge {{
      font-size: 11px;
      font-weight: 800;
      padding: 3px 8px;
      border-radius: 4px;
      letter-spacing: 0.5px;
    }}
    .sev-critical {{ background: #ef4444; color: #fff; }}
    .sev-high {{ background: #f97316; color: #fff; }}
    .sev-medium {{ background: #eab308; color: #000; }}
    .sev-low {{ background: #3b82f6; color: #fff; }}
    .root-cause {{ font-size: 14px; margin-bottom: 8px; }}
    .explanation {{ font-size: 13px; color: var(--text-muted); margin-bottom: 12px; }}
    .evidence-box {{
      background: rgba(0,0,0,0.25);
      padding: 12px;
      border-radius: 6px;
      font-size: 13px;
      margin-bottom: 12px;
    }}
    .evidence-box ul {{ padding-left: 20px; margin-top: 6px; }}
    .diff-box {{
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 6px;
      overflow: hidden;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
    }}
    .diff-header {{
      background: #161b22;
      padding: 6px 12px;
      font-weight: 600;
      color: #8b949e;
      border-bottom: 1px solid #30363d;
    }}
    .diff-box pre {{ padding: 12px; overflow-x: auto; margin: 0; }}
    .diff-add {{ color: #7ee787; background: rgba(46, 160, 67, 0.15); display: block; }}
    .diff-del {{ color: #ffa198; background: rgba(248, 81, 73, 0.15); display: block; }}
    .diff-info {{ color: #79c0ff; display: block; }}
    .success-card {{
      background: rgba(16, 185, 129, 0.05);
      border: 1px solid rgba(16, 185, 129, 0.2);
      border-radius: 10px;
      padding: 24px;
      text-align: center;
    }}
    .recs-list {{ padding-left: 20px; font-size: 14px; }}
    .recs-list li {{ margin-bottom: 8px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="logo-badge">
        <div class="icon">FA</div>
        <div>
          <h1>FirmAI Diagnostic Audit</h1>
          <p style="font-size: 13px; color: var(--text-muted);">Autonomous Virtual Hardware & Firmware Validation Agent</p>
        </div>
      </div>
      <div class="verdict-banner" style="color: {verdict_color}; background: {verdict_bg}; border-color: {verdict_color};">
        OVERALL VERDICT: {verdict}
      </div>
    </div>

    <!-- Summary Stats -->
    <div class="grid-stats">
      <div class="stat-card">
        <div class="label">Pass Rate</div>
        <div class="val" style="color: {verdict_color};">{summary.get('pass_rate', 0)}%</div>
      </div>
      <div class="stat-card">
        <div class="label">Tests Executed</div>
        <div class="val">{summary.get('total', 0)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Passed</div>
        <div class="val" style="color: var(--pass);">{summary.get('passed', 0)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Failed / Defects</div>
        <div class="val" style="color: var(--fail);">{summary.get('failed', 0) + summary.get('errored', 0)}</div>
      </div>
    </div>

    <!-- Target Firmware Details -->
    <div class="card">
      <div class="card-title">Target Firmware Metadata</div>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; font-size: 14px;">
        <div><span style="color: var(--text-muted);">Filename:</span> <strong>{firmware.get('filename')}</strong></div>
        <div><span style="color: var(--text-muted);">Size:</span> <span class="font-mono">{firmware.get('size_bytes')} bytes</span></div>
        <div><span style="color: var(--text-muted);">Simulator:</span> <span class="tag">{summary.get('simulator_backend')}</span></div>
        <div><span style="color: var(--text-muted);">Execution Mode:</span> <span class="tag">{summary.get('execution_mode')}</span></div>
      </div>
    </div>

    <!-- AI Failure Diagnosis -->
    <div class="card">
      <div class="card-title">AI Root Cause & Defect Diagnostics ({len(failures)} item(s))</div>
      {"".join(failures_html)}
    </div>

    <!-- Test Results Table -->
    <div class="card">
      <div class="card-title">Test Suite Execution Breakdown</div>
      <div style="overflow-x: auto;">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Test Scenario</th>
              <th>Category</th>
              <th>Priority</th>
              <th>Status</th>
              <th class="text-right">Assertions</th>
              <th class="text-right">Execution</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows_html)}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Remediation Checklist -->
    <div class="card">
      <div class="card-title">Remediation & Action Plan</div>
      <ul class="recs-list">
        {rec_items}
      </ul>
    </div>

    <div style="text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 40px;">
      Report generated by FirmAI Autonomous Firmware Testing Agent • Timestamp: {data.get('generated_at')}
    </div>
  </div>
</body>
</html>
"""

    def save_report(self, run_id: str, data: dict[str, Any], html: str) -> Path:
        """Persist report artifacts to the reports directory."""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        html_path = REPORT_DIR / f"report_{run_id}.html"
        json_path = REPORT_DIR / f"report_{run_id}.json"

        html_path.write_text(html, encoding="utf-8")
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return html_path


def get_report_generator() -> ReportGenerator:
    return ReportGenerator()
