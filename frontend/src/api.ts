export type StageStatus = "passed" | "warning" | "failed" | "error" | "skipped";

export interface Finding {
  tool: string;
  rule: string;
  message: string;
  severity: "info" | "low" | "medium" | "high" | "critical";
  file?: string | null;
  line?: number | null;
}

export interface TestCase {
  nodeid: string;
  outcome: string;
  hidden: boolean;
  category: string;
  message?: string | null;
}

export interface Benchmark {
  name: string;
  ok: boolean;
  median_ms?: number | null;
  budget_ms?: number | null;
  peak_memory_kb?: number | null;
  error?: string | null;
}

export interface Stage {
  stage: string;
  status: StageStatus;
  score: number | null;
  summary: string;
  duration_ms: number;
  metrics: Record<string, unknown>;
  findings: Finding[];
  tests: TestCase[];
  benchmarks: Benchmark[];
}

export interface Scorecard {
  functional_correctness: number | null;
  edge_case_handling: number | null;
  integration: number | null;
  test_coverage: number | null;
  static_quality: number | null;
  security: "pass" | "fail" | null;
  performance_median_ms: number | null;
  performance_score: number | null;
  llm_quality: number | null;
  overall: number;
}

export interface CandidateReport {
  label: string;
  model: string | null;
  verdict: "pass" | "pass_with_warnings" | "fail";
  gates_failed: string[];
  scorecard: Scorecard;
  stages: Stage[];
}

export interface Report {
  task_id: string;
  task_title: string;
  candidates: CandidateReport[];
  ranking: string[];
  notes: string[];
}

export interface Submission {
  id: string;
  task_id: string;
  status: "queued" | "running" | "completed" | "failed";
  source: string;
  candidates: string[];
  ranking: string[] | null;
  created_at: string;
  finished_at: string | null;
  error?: string | null;
  report?: Report | null;
}

export interface TaskSummary {
  id: string;
  title: string;
  visible_tests: number;
  hidden_tests: number;
  benchmarks: number;
}

export interface CandidateInput {
  label: string;
  model?: string;
  files: Record<string, string>;
}

function headers(): HeadersInit {
  const token = localStorage.getItem("codejudge.token");
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: headers() });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status}: ${body}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  tasks: () => req<TaskSummary[]>("/api/tasks"),
  submissions: () => req<Submission[]>("/api/submissions"),
  submission: (id: string) => req<Submission>(`/api/submissions/${id}`),
  submit: (body: { task_id: string; candidates: CandidateInput[]; stages?: string[] }) =>
    req<{ id: string }>("/api/submissions", { method: "POST", body: JSON.stringify(body) }),
};
