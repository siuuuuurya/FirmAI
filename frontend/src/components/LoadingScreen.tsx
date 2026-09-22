import React, { useEffect, useMemo, useState } from 'react';

const STATUS_MESSAGES = [
  'INITIALIZING VIRTUAL MCU...',
  'ANALYZING FIRMWARE...',
  'BUILDING MACHINE MODEL...',
  'GENERATING TEST CASES...',
  'COMPILING SIMULATION...',
  'RUNNING TEST SUITE...',
  'ANALYZING FAILURES...',
  'GENERATING AUDIT REPORT...',
];

const PIPELINE = ['ANALYZE', 'GENERATE TESTS', 'SIMULATE', 'DEBUG', 'REPORT'];

const MARKERS = [
  { left: '9%', top: '17%', delay: '0.2s' },
  { left: '21%', top: '74%', delay: '1.7s' },
  { left: '37%', top: '12%', delay: '2.8s' },
  { left: '63%', top: '23%', delay: '1.1s' },
  { left: '78%', top: '69%', delay: '3.2s' },
  { left: '91%', top: '39%', delay: '2.1s' },
  { left: '48%', top: '84%', delay: '0.9s' },
  { left: '15%', top: '46%', delay: '3.8s' },
];

export const LoadingScreen: React.FC = () => {
  const [progress, setProgress] = useState(0);
  const [statusIndex, setStatusIndex] = useState(0);

  useEffect(() => {
    const start = performance.now();
    const duration = 10800;
    let frame = 0;

    const tick = (now: number) => {
      const elapsed = now - start;
      const linear = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - linear, 2.2);
      setProgress(Math.min(99, Math.round(eased * 100)));
      if (linear < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        setProgress(100);
      }
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setStatusIndex(index => (index + 1) % STATUS_MESSAGES.length);
    }, 2300);

    return () => window.clearInterval(interval);
  }, []);

  const activeStage = useMemo(() => {
    if (progress < 23) return 0;
    if (progress < 46) return 1;
    if (progress < 68) return 2;
    if (progress < 86) return 3;
    return 4;
  }, [progress]);

  return (
    <section className="firm-loader" aria-label="FirmAI loading screen">
      <div className="firm-loader__grid" aria-hidden="true" />
      <div className="firm-loader__scan" aria-hidden="true" />

      <div className="firm-loader__corner firm-loader__corner--top-right">
        <span>[FIRMWARE TESTING AGENT]</span>
        <span>v1.0.0</span>
      </div>

      <div className="firm-loader__corner firm-loader__corner--bottom-left">
        <span>BETTER</span>
        <span>FIRMWARE</span>
        <span>SAFER TOMORROW</span>
      </div>

      <div className="firm-loader__corner firm-loader__corner--bottom-right">
        <span>[ARDUINO]</span>
        <span>[SIMULATION]</span>
        <span>[AI DEBUGGING]</span>
        <span>[AUDIT READY]</span>
      </div>

      <span className="firm-loader__coordinate firm-loader__coordinate--top-left" aria-hidden="true">
        X:000 Y:000
      </span>
      <span className="firm-loader__coordinate firm-loader__coordinate--bottom-center" aria-hidden="true">
        MCU::VIRTUAL_TEST_BENCH
      </span>

      {MARKERS.map((marker, index) => (
        <span
          aria-hidden="true"
          className="firm-loader__marker"
          key={`${marker.left}-${marker.top}`}
          style={{ left: marker.left, top: marker.top, animationDelay: marker.delay }}
        >
          <span />
          {index % 3 === 0 && <b>{`P${index + 1}`}</b>}
        </span>
      ))}

      <div className="firm-loader__content">
        <div className="firm-loader__schematic" aria-hidden="true">
          <span className="firm-loader__io-label firm-loader__io-label--left">CODE INPUT</span>
          <span className="firm-loader__io-label firm-loader__io-label--right">TEST RESULTS</span>

          <svg className="firm-loader__signal" viewBox="0 0 760 180" role="presentation">
            <defs>
              <clipPath id="firm-signal-window">
                <rect x="0" y="0" width="760" height="180" />
              </clipPath>
            </defs>
            <g clipPath="url(#firm-signal-window)">
              <path
                className="firm-loader__wave firm-loader__wave--base"
                d="M0 90 H118 V66 H150 V114 H184 V90 H286 V70 H322 V110 H356 V90 H480 V62 H514 V118 H548 V90 H760"
              />
              <path
                className="firm-loader__wave firm-loader__wave--motion"
                d="M-760 90 H-642 V66 H-610 V114 H-576 V90 H-474 V70 H-438 V110 H-404 V90 H-280 V62 H-246 V118 H-212 V90 H0 H118 V66 H150 V114 H184 V90 H286 V70 H322 V110 H356 V90 H480 V62 H514 V118 H548 V90 H760"
              />
            </g>
          </svg>

          <svg className="firm-loader__chip" viewBox="0 0 220 220" role="img" aria-label="Outlined microcontroller chip">
            <g className="firm-loader__chip-lines">
              {Array.from({ length: 8 }).map((_, index) => (
                <React.Fragment key={`pins-${index}`}>
                  <line x1="39" x2="18" y1={51 + index * 17} y2={51 + index * 17} />
                  <line x1="181" x2="202" y1={51 + index * 17} y2={51 + index * 17} />
                </React.Fragment>
              ))}
              {Array.from({ length: 6 }).map((_, index) => (
                <React.Fragment key={`vertical-pins-${index}`}>
                  <line x1={67 + index * 17} x2={67 + index * 17} y1="39" y2="18" />
                  <line x1={67 + index * 17} x2={67 + index * 17} y1="181" y2="202" />
                </React.Fragment>
              ))}
              <rect x="39" y="39" width="142" height="142" rx="6" />
              <rect x="60" y="60" width="100" height="100" rx="2" />
              <circle cx="74" cy="74" r="3" />
              <line x1="84" x2="136" y1="146" y2="146" />
              <line x1="84" x2="136" y1="156" y2="156" />
            </g>
            <text x="110" y="123" textAnchor="middle">
              F
            </text>
          </svg>
        </div>

        <div className="firm-loader__title">
          <h1>FIRMAI</h1>
          <p>AUTONOMOUS FIRMWARE TESTING AGENT</p>
        </div>

        <ol className="firm-loader__pipeline" aria-label="Firmware testing pipeline">
          {PIPELINE.map((stage, index) => (
            <li
              key={stage}
              className={index === activeStage ? 'is-active' : ''}
              aria-current={index === activeStage ? 'step' : undefined}
            >
              <span>{stage}</span>
            </li>
          ))}
        </ol>

        <div className="firm-loader__progress" aria-live="polite">
          <div className="firm-loader__progress-meta">
            <span>{STATUS_MESSAGES[statusIndex]}</span>
            <strong>{String(progress).padStart(2, '0')}%</strong>
          </div>
          <div
            className="firm-loader__progress-track"
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span style={{ transform: `scaleX(${progress / 100})` }} />
          </div>
        </div>
      </div>
    </section>
  );
};
