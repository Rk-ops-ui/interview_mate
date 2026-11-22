// ProctorPanel.jsx
// Live camera view, warning counters, warning dialog and blocking overlays.
// The project has no vite.config.js, so JSX compiles to React.createElement
// and every .jsx file must import React.
import React from "react";
import { AlertTriangle, Camera, Maximize, MonitorX, ShieldCheck } from "lucide-react";
import { MAX_WARNINGS } from "./useProctoring";

export default function ProctorPanel({ proctor }) {
  const { videoRef, canvasRef, status, counts, warning, blocker, detections } = proctor;
  const active = status === "active";

  return (
    <>
      <style>{proctorStyles}</style>

      <aside className={`proctor-cam ${active ? "on" : ""}`} aria-label="Proctoring camera">
        <div className="proctor-video">
          <video ref={videoRef} muted playsInline />
          <canvas ref={canvasRef} />
          {!active && (
            <div className="proctor-video-off">
              <Camera size={22} />
              <span>{status === "starting" ? "Starting camera..." : "Camera off"}</span>
            </div>
          )}
        </div>

        <div className="proctor-meta">
          <span className={`proctor-state ${detections.length ? "bad" : "ok"}`}>
            {detections.length ? <AlertTriangle size={13} /> : <ShieldCheck size={13} />}
            {active ? (detections.length ? detections.join(", ") : "Monitoring") : "Not monitoring"}
          </span>
          <div className="proctor-counts">
            <span>Camera {counts.camera}/{MAX_WARNINGS}</span>
            <span>Tabs/apps {counts.focus}/{MAX_WARNINGS}</span>
          </div>
        </div>
      </aside>

      {warning && !blocker && (
        <div className="proctor-overlay" role="alertdialog" aria-modal="true">
          <div className="proctor-dialog warn">
            <AlertTriangle size={34} />
            <h2>{warning.count === MAX_WARNINGS - 1 ? "Final warning" : `Warning ${warning.count}`}</h2>
            <p>{warning.message}.</p>
            <p className="proctor-small">
              {warning.type === "camera"
                ? "Remove it from the camera view and stay alone in frame."
                : "Stay on this tab until the interview is finished."}{" "}
              One more {warning.type === "camera" ? "camera" : "tab or application"} violation
              will submit your interview automatically.
            </p>
            <button className="primary-button" onClick={proctor.dismissWarning}>
              I understand
            </button>
          </div>
        </div>
      )}

      {blocker && (
        <div className="proctor-overlay" role="alertdialog" aria-modal="true">
          <div className="proctor-dialog">
            {blocker === "app" && (
              <>
                <MonitorX size={34} />
                <h2>Close the other application</h2>
                <p>
                  Another application or window is in front of the interview. Close it and click
                  below to continue. Staying away for more than 10 seconds counts as a warning.
                </p>
                <button className="primary-button" onClick={proctor.returnToTest}>
                  I closed it, continue
                </button>
              </>
            )}
            {blocker === "fullscreen" && (
              <>
                <Maximize size={34} />
                <h2>Return to full screen</h2>
                <p>The interview must stay in full screen while it is running.</p>
                <button className="primary-button" onClick={proctor.returnToTest}>
                  Enter full screen
                </button>
              </>
            )}
            {blocker === "camera" && (
              <>
                <Camera size={34} />
                <h2>Camera disconnected</h2>
                <p>Your camera must stay on for the whole interview.</p>
                <button className="primary-button" onClick={proctor.restartCamera}>
                  Turn camera back on
                </button>
                {proctor.error && <p className="proctor-small">{proctor.error}</p>}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

const proctorStyles = `
.proctor-cam{position:fixed;top:20px;right:20px;z-index:40;width:230px;border:1px solid #e1e6f0;border-radius:14px;background:#fff;box-shadow:0 10px 26px rgba(26,38,68,.14);overflow:hidden}
.proctor-cam.on{border-color:#c9ecd6}
.proctor-video{position:relative;aspect-ratio:4/3;background:#111827}
.proctor-video video,.proctor-video canvas{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transform:scaleX(-1)}
.proctor-video-off{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;color:#9ca3af;font-size:12px}
.proctor-meta{display:flex;flex-direction:column;gap:6px;padding:9px 11px;font-size:11px}
.proctor-state{display:flex;align-items:center;gap:6px;font-weight:600}
.proctor-state.ok{color:#269653}
.proctor-state.bad{color:#dc2626}
.proctor-counts{display:flex;justify-content:space-between;color:#7b8496}
.proctor-overlay{position:fixed;inset:0;z-index:50;display:grid;place-items:center;padding:16px;background:rgba(15,23,42,.72)}
.proctor-dialog{max-width:440px;width:100%;padding:28px 26px;border-radius:16px;background:#fff;text-align:center;color:#596ce3;box-shadow:0 20px 50px rgba(0,0,0,.25)}
.proctor-dialog.warn{color:#dc2626}
.proctor-dialog h2{margin:12px 0 8px;color:#172033;font-size:21px}
.proctor-dialog p{margin:0 0 12px;color:#4b5567;font-size:14px;line-height:1.6}
.proctor-dialog .proctor-small{color:#7b8496;font-size:12px}
.proctor-dialog .primary-button{margin-top:6px}
.proctor-gate{margin:36px 0 0;padding:26px 28px;border:1px solid #e1e6f0;border-radius:16px;background:#fff;box-shadow:0 9px 24px rgba(32,47,83,.07);text-align:left}
.proctor-gate h2{margin:0 0 12px;font-size:20px}
.proctor-gate ul{margin:0 0 20px;padding-left:20px;color:#4b5567;font-size:14px;line-height:1.8}
.auto-submit-banner{width:100%;margin:0 0 18px;padding:14px 16px;border:1px solid #fecaca;border-radius:12px;background:#fff1f2;color:#b42335;font-size:13px;text-align:left}
.auto-submit-banner ul{margin:8px 0 0;padding-left:18px;color:#7f1d1d}
@media(max-width:850px){.proctor-cam{width:150px;top:12px;right:12px}.proctor-counts{flex-direction:column;gap:2px}}
`;
