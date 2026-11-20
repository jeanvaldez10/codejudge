import { useCallback, useEffect, useState } from "react";
import {
  api,
  type CandidateInput,
  type CandidateReport,
  type Report,
  type Stage,
  type Submission,
  type TaskSummary,
} from "./api";

const pct = (v: number | null | undefined) => (v == null ? "n/a" : `${Math.round(v)}%`);

function tone(v: number | null | undefined): string {
  if (v == null) return "muted";
  if (v >= 90) return "good";
  if (v >= 60) return "warn";
  return "bad";
}

export default function App() {
  const [subs, setSubs] = useState<Submission[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Submission | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.submissions().then(setSubs).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    const load = () =>
      api.submission(selected).then((s) => {
        if (!alive) return;
        setDetail(s);
        if (s.status === "queued" || s.status === "running") setTimeout(load, 2000);
      });
    load();
    return () => {
      alive = false;
    };
  }, [selected]);

  return (
    <div className="app">
      <header>
        <h1>CodeJudge</h1>
        <span className="tagline">independent verification for AI-generated code</span>
        <button className="primary" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Close" : "New evaluation"}
        </button>
      </header>
      {error && <div className="banner bad">{error}</div>}
      <div className="layout">
        <aside>
          <h2>Submissions</h2>
          {subs.length === 0 && <p className="muted">No submissions yet.</p>}
          <ul className="subs">
            {subs.map((s) => (
              <li key={s.id}>
                <button
                  className={s.id === selected ? "sub active" : "sub"}
                  onClick={() => {
                    setSelected(s.id);
                    setShowForm(false);
                  }}
                >
                  <span className={`dot ${s.status}`} />
                  <span className="sub-title">{s.task_id}</span>
                  <span className="muted small">
                    {s.candidates.join(" · ")} — {s.status}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <main>
          {showForm ? (
            <SubmitForm
              onSubmitted={(id) => {
                setShowForm(false);
                setSelected(id);
                refresh();
              }}
            />
          ) : detail ? (
            <SubmissionView sub={detail} />
          ) : (
            <p className="muted">Select a submission, or start a new evaluation.</p>
          )}
        </main>
      </div>
    </div>
  );
}

function SubmissionView({ sub }: { sub: Submission }) {
  if (sub.status === "failed") return <div className="banner bad">Evaluation failed: {sub.error}</div>;
  if (!sub.report)
    return (
      <div className="pending">
        <span className={`dot ${sub.status}`} /> {sub.status === "queued" ? "Queued…" : "Running in sandbox…"}
      </div>
    );
  return <ReportView report={sub.report} id={sub.id} />;
}

function ReportView({ report, id }: { report: Report; id: string }) {
  const cs = report.candidates;
  const rows: [string, (c: CandidateReport) => React.ReactNode, (c: CandidateReport) => string][] = [
    ["Overall", (c) => c.scorecard.overall.toFixed(1), (c) => tone(c.scorecard.overall)],
    ["Functional correctness", (c) => pct(c.scorecard.functional_correctness), (c) => tone(c.scorecard.functional_correctness)],
    ["Edge-case handling", (c) => pct(c.scorecard.edge_case_handling), (c) => tone(c.scorecard.edge_case_handling)],
    ["Integration", (c) => pct(c.scorecard.integration), (c) => tone(c.scorecard.integration)],
    ["Own-test coverage", (c) => pct(c.scorecard.test_coverage), (c) => tone(c.scorecard.test_coverage)],
    ["Static quality", (c) => pct(c.scorecard.static_quality), (c) => tone(c.scorecard.static_quality)],
    [
      "Security checks",
      (c) => (c.scorecard.security ?? "n/a").toUpperCase(),
      (c) => (c.scorecard.security === "pass" ? "good" : c.scorecard.security === "fail" ? "bad" : "muted"),
    ],
    [
      "Execution time",
      (c) => (c.scorecard.performance_median_ms == null ? "n/a" : `${c.scorecard.performance_median_ms.toFixed(2)} ms`),
      (c) => tone(c.scorecard.performance_score),
    ],
    ["LLM review (advisory)", (c) => pct(c.scorecard.llm_quality), (c) => tone(c.scorecard.llm_quality)],
  ];
  return (
    <section>
      <div className="report-head">
        <div>
          <h2>{report.task_title}</h2>
          <p className="muted">
            Ranking: {report.ranking.map((l, i) => (
              <strong key={l}>{i > 0 ? " › " : ""}{l}</strong>
            ))}
          </p>
        </div>
        <a className="button" href={`/api/submissions/${id}/report.md`} target="_blank" rel="noreferrer">
          Markdown report
        </a>
      </div>
      <div className="table-wrap">
        <table className="compare">
          <thead>
            <tr>
              <th>Criterion</th>
              {cs.map((c) => (
                <th key={c.label}>
                  {c.label}
                  {c.model && <div className="muted small">{c.model}</div>}
                  <span className={`verdict ${c.verdict}`}>{c.verdict.replace(/_/g, " ")}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, val, cls]) => (
              <tr key={name}>
                <td>{name}</td>
                {cs.map((c) => (
                  <td key={c.label} className={`cell ${cls(c)}`}>
                    {val(c)}
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <td>Gates failed</td>
              {cs.map((c) => (
                <td key={c.label} className={c.gates_failed.length ? "cell bad" : "cell muted"}>
                  {c.gates_failed.join(", ") || "—"}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {cs.map((c) => (
        <CandidateDetail key={c.label} c={c} />
      ))}
      <ul className="notes">
        {report.notes.map((n) => (
          <li key={n} className="muted small">{n}</li>
        ))}
      </ul>
    </section>
  );
}

function CandidateDetail({ c }: { c: CandidateReport }) {
  return (
    <details className="candidate">
      <summary>
        <strong>{c.label}</strong> <span className={`verdict ${c.verdict}`}>{c.verdict.replace(/_/g, " ")}</span>
        <span className="muted small"> overall {c.scorecard.overall.toFixed(1)}</span>
      </summary>
      <div className="stages">
        {c.stages.map((s) => (
          <StageRow key={s.stage} s={s} />
        ))}
      </div>
    </details>
  );
}

function StageRow({ s }: { s: Stage }) {
  const failing = s.tests.filter((t) => t.outcome !== "passed");
  const rubric = s.metrics.rubric as Record<string, number> | undefined;
  const justifications = (s.metrics.justifications ?? {}) as Record<string, string>;
  const hasMore = failing.length > 0 || s.findings.length > 0 || s.benchmarks.length > 0 || rubric;
  return (
    <details className={`stage ${s.status}`} open={false}>
      <summary>
        <span className={`badge ${s.status}`}>{s.status}</span>
        <code>{s.stage}</code>
        <span className="score">{s.score == null ? "" : Math.round(s.score)}</span>
        <span className="muted small">{s.summary}</span>
      </summary>
      {hasMore && (
        <div className="stage-body">
          {failing.length > 0 && (
            <ul>
              {failing.slice(0, 15).map((t) => (
                <li key={t.nodeid}>
                  <code>{t.nodeid}</code> — {t.outcome}
                  {t.message && <pre>{t.message.split("\n").slice(-6).join("\n")}</pre>}
                </li>
              ))}
            </ul>
          )}
          {s.findings.length > 0 && (
            <ul>
              {s.findings.slice(0, 30).map((f, i) => (
                <li key={i}>
                  <span className={`sev ${f.severity}`}>{f.severity}</span> <code>{f.tool}/{f.rule}</code>{" "}
                  {f.file && <span className="muted">{f.file}{f.line ? `:${f.line}` : ""}</span>} {f.message}
                </li>
              ))}
            </ul>
          )}
          {s.benchmarks.length > 0 && (
            <table className="mini">
              <thead>
                <tr><th>Benchmark</th><th>Median</th><th>Budget</th><th>Peak mem</th></tr>
              </thead>
              <tbody>
                {s.benchmarks.map((b) => (
                  <tr key={b.name}>
                    <td>{b.name}</td>
                    <td>{b.ok ? `${b.median_ms?.toFixed(2)} ms` : b.error}</td>
                    <td>{b.budget_ms ? `${b.budget_ms} ms` : "relative"}</td>
                    <td>{b.peak_memory_kb ? `${Math.round(b.peak_memory_kb)} KiB` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {rubric && (
            <ul>
              {Object.entries(rubric).map(([k, v]) => (
                <li key={k}>
                  <strong>{k}</strong>: {v}/5 <span className="muted">{justifications[k]}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </details>
  );
}

const emptyCandidate = (n: number): CandidateDraft => ({
  label: `Model ${String.fromCharCode(65 + n)}`,
  model: "",
  solution: "",
  tests: "",
});

interface CandidateDraft {
  label: string;
  model: string;
  solution: string;
  tests: string;
}

function SubmitForm({ onSubmitted }: { onSubmitted: (id: string) => void }) {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [taskId, setTaskId] = useState("");
  const [drafts, setDrafts] = useState<CandidateDraft[]>([emptyCandidate(0), emptyCandidate(1)]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.tasks().then((t) => {
      setTasks(t);
      if (t.length && !taskId) setTaskId(t[0].id);
    });
  }, [taskId]);

  const update = (i: number, patch: Partial<CandidateDraft>) =>
    setDrafts((ds) => ds.map((d, j) => (i === j ? { ...d, ...patch } : d)));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const candidates: CandidateInput[] = drafts.map((d) => ({
        label: d.label,
        model: d.model || undefined,
        files: { "solution.py": d.solution, ...(d.tests.trim() ? { "test_solution.py": d.tests } : {}) },
      }));
      const r = await api.submit({ task_id: taskId, candidates });
      onSubmitted(r.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="form">
      <h2>New evaluation</h2>
      {tasks.length === 0 ? (
        <p className="muted">
          No tasks registered. Create one with <code>PUT /api/tasks/&lt;id&gt;</code>.
        </p>
      ) : (
        <label>
          Task
          <select value={taskId} onChange={(e) => setTaskId(e.target.value)}>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title} — {t.visible_tests} visible / {t.hidden_tests} hidden suites, {t.benchmarks} benchmarks
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="drafts">
        {drafts.map((d, i) => (
          <fieldset key={i}>
            <div className="row">
              <input value={d.label} onChange={(e) => update(i, { label: e.target.value })} placeholder="Label" />
              <input value={d.model} onChange={(e) => update(i, { model: e.target.value })} placeholder="Generator (optional)" />
              {drafts.length > 1 && (
                <button onClick={() => setDrafts((ds) => ds.filter((_, j) => j !== i))}>Remove</button>
              )}
            </div>
            <textarea
              spellCheck={false}
              value={d.solution}
              onChange={(e) => update(i, { solution: e.target.value })}
              placeholder="solution.py"
              rows={12}
            />
            <textarea
              spellCheck={false}
              value={d.tests}
              onChange={(e) => update(i, { tests: e.target.value })}
              placeholder="test_solution.py (optional: the generator's own tests)"
              rows={5}
            />
          </fieldset>
        ))}
      </div>
      <div className="row">
        <button onClick={() => setDrafts((ds) => [...ds, emptyCandidate(ds.length)])}>Add candidate</button>
        <button className="primary" disabled={busy || !taskId} onClick={submit}>
          {busy ? "Submitting…" : "Evaluate"}
        </button>
      </div>
      {error && <div className="banner bad">{error}</div>}
    </section>
  );
}
