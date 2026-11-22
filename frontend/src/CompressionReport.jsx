// CompressionReport.jsx
// Shows how much the chunk summaries shrink the prompt sent to Gemini and how
// faithful they are to the original chunks (data from /compression-report/).
import React, { useState } from "react";
import { BarChart3, ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";

const pct = (value) => (value == null ? "—" : `${Math.round(value * 100)}%`);
const num = (value) => (value == null ? "—" : value.toLocaleString());

export default function CompressionReport({ report, loading }) {
  const [showAll, setShowAll] = useState(false);

  if (loading) {
    return (
      <section className="cr-card">
        <div className="cr-title"><BarChart3 size={17} /> Prompt compression report</div>
        <p className="cr-muted">Measuring compression and accuracy...</p>
      </section>
    );
  }
  if (!report || !report.chunks) return null;

  const { grades } = report;
  const total = report.chunks;
  const rows = showAll ? report.rows : report.weakest;

  return (
    <section className="cr-card">
      <style>{styles}</style>
      <div className="cr-title"><BarChart3 size={17} /> Prompt compression report</div>
      <p className="cr-muted">
        {total} retrieved knowledge chunks were summarized before being sent to Gemini.
      </p>

      <div className="cr-tiles">
        <div className="cr-tile">
          <span>Tokens</span>
          <strong>{num(report.tokens_before)} → {num(report.tokens_after)}</strong>
          <small>
            {report.tokens_saved >= 0
              ? `${num(report.tokens_saved)} saved`
              : `${num(-report.tokens_saved)} added`}
          </small>
        </div>
        <div className="cr-tile">
          <span>Size reduction</span>
          <strong>{report.reduction_percent}%</strong>
          <small>
            {!report.compression_ratio
              ? "—"
              : report.compression_ratio >= 1
                ? `${report.compression_ratio}× smaller`
                : "summaries longer than originals"}
          </small>
        </div>
        <div className="cr-tile">
          <span>Accuracy (meaning kept)</span>
          <strong>{pct(report.avg_similarity)}</strong>
          <small>lowest {pct(report.min_similarity)}</small>
        </div>
        <div className="cr-tile">
          <span>Key concepts found in source</span>
          <strong>{pct(report.avg_concept_coverage)}</strong>
          <small>checks for made-up terms</small>
        </div>
      </div>

      <div className="cr-grades" aria-label="Summary quality">
        {["good", "fair", "poor"].map((g) =>
          grades[g] ? (
            <div key={g} className={`cr-bar ${g}`} style={{ flex: grades[g] }} title={`${grades[g]} ${g}`} />
          ) : null
        )}
      </div>
      <div className="cr-legend">
        <span><i className="good" /> Good {grades.good}</span>
        <span><i className="fair" /> Fair {grades.fair}</span>
        <span><i className="poor" /> Poor {grades.poor}</span>
        <span className="cr-muted">
          Good ≥ {pct(report.thresholds.good)}, fair ≥ {pct(report.thresholds.fair)} similarity
        </span>
      </div>

      {(report.non_english > 0 || report.degraded > 0) && (
        <div className="cr-warn">
          <AlertTriangle size={14} />
          {report.non_english > 0 && <span>{report.non_english} summary(ies) not in English.</span>}
          {report.degraded > 0 && <span>{report.degraded} chunk(s) could not be summarized and were shortened instead.</span>}
        </div>
      )}

      <div className="cr-table-head">
        <strong>{showAll ? "All chunks" : "Weakest summaries"}</strong>
        <button type="button" className="cr-toggle" onClick={() => setShowAll((v) => !v)}>
          {showAll ? <>Show weakest only <ChevronUp size={14} /></> : <>Show all {total} <ChevronDown size={14} /></>}
        </button>
      </div>
      <div className="cr-table-wrap">
        <table className="cr-table">
          <thead>
            <tr><th>Chunk</th><th>Accuracy</th><th>Tokens</th><th>Summary</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.chunk_id}>
                <td>{r.chunk_id}</td>
                <td><span className={`cr-pill ${r.grade}`}>{pct(r.similarity)}</span>{!r.english && <span className="cr-pill poor">not EN</span>}</td>
                <td>{r.tokens_before} → {r.tokens_after}</td>
                <td title={r.original_preview}>{r.summary_preview || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="cr-muted cr-note">
        Accuracy is the semantic similarity between each original chunk and its summary
        (all-MiniLM-L6-v2 embeddings). Tokens are estimated with the cl100k tokenizer.
      </p>
    </section>
  );
}

const styles = `
.cr-card{width:100%;margin:24px 0 0;padding:22px 24px;border:1px solid #e1e6f0;border-radius:16px;background:#fff;box-shadow:0 9px 24px rgba(32,47,83,.07);text-align:left}
.cr-title{display:flex;align-items:center;gap:8px;color:#596ce3;font-size:13px;font-weight:700;letter-spacing:.4px}
.cr-muted{color:#7b8496;font-size:12px;margin:6px 0 0}
.cr-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}
.cr-tile{display:flex;flex-direction:column;gap:4px;padding:12px 14px;border-radius:12px;background:#f6f8ff}
.cr-tile span{font-size:11px;color:#6b7588}
.cr-tile strong{font-size:18px;color:#1f2a3d;font-variant-numeric:tabular-nums}
.cr-tile small{font-size:11px;color:#8a94a4}
.cr-grades{display:flex;gap:3px;height:10px;border-radius:6px;overflow:hidden;background:#eef1f7}
.cr-bar.good,.cr-legend i.good,.cr-pill.good{background:#2ea865}
.cr-bar.fair,.cr-legend i.fair,.cr-pill.fair{background:#e0a92b}
.cr-bar.poor,.cr-legend i.poor,.cr-pill.poor{background:#dc4655}
.cr-legend{display:flex;flex-wrap:wrap;gap:14px;margin:8px 0 0;font-size:12px;color:#4b5567}
.cr-legend span{display:flex;align-items:center;gap:6px}
.cr-legend i{width:9px;height:9px;border-radius:50%;display:inline-block}
.cr-warn{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:12px 0 0;padding:9px 12px;border-radius:9px;background:#fff7e6;color:#8a5a00;font-size:12px}
.cr-table-head{display:flex;align-items:center;justify-content:space-between;margin:18px 0 8px;font-size:13px}
.cr-toggle{display:inline-flex;align-items:center;gap:4px;border:0;background:transparent;color:#5a68d6;font-size:12px}
.cr-table-wrap{max-height:320px;overflow:auto;border:1px solid #edf0f5;border-radius:10px}
.cr-table{width:100%;border-collapse:collapse;font-size:12px}
.cr-table th{position:sticky;top:0;background:#f8f9fc;text-align:left;padding:8px 10px;color:#6b7588;font-weight:600}
.cr-table td{padding:8px 10px;border-top:1px solid #f0f2f6;vertical-align:top;color:#344055}
.cr-table td:first-child,.cr-table td:nth-child(3){white-space:nowrap;font-variant-numeric:tabular-nums}
.cr-pill{display:inline-block;margin:0 4px 2px 0;padding:2px 7px;border-radius:10px;color:#fff;font-size:11px;font-weight:600}
.cr-note{margin-top:10px}
@media(max-width:700px){.cr-tiles{grid-template-columns:1fr 1fr}.cr-card{padding:18px}}
`;
