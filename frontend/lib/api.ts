import {
  cases,
  dashboard as mockDashboard,
  steps as mockSteps,
} from "@/lib/mock";
import type { Case, CheckinRun, Dashboard, Step, StepPage } from "@/lib/types";

const BASE =
  process.env.NEXT_PUBLIC_USE_API_PROXY === "1"
    ? "/backend"
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === "1";

const extraSteps: Step[] = [];

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const body = (await response.json().catch(() => ({}))) as {
    detail?: string;
  };
  if (!response.ok) {
    throw new ApiError(response.status, body.detail || response.statusText);
  }
  return body as T;
}

export function getDashboard(): Promise<Dashboard> {
  if (USE_MOCK) return Promise.resolve(mockDashboard);
  return request<Dashboard>("/dashboard");
}

export function getCase(id: string): Promise<Case> {
  if (USE_MOCK) {
    const found = cases[id];
    if (!found)
      return Promise.reject(new ApiError(404, "unknown policyholder"));
    return Promise.resolve(found);
  }
  return request<Case>(`/cases/${id}`);
}

export function getSteps(since?: number): Promise<StepPage> {
  if (USE_MOCK) {
    extraSteps.push({
      id: 100000 + extraSteps.length + 1,
      ts: new Date().toISOString().replace(".000Z", "Z"),
      kind: "plan",
      policyholder_id: null,
      tool: null,
      text: "Mock planner tick",
      ms: null,
    });
    const all = [...mockSteps.steps, ...extraSteps];
    const steps = since == null ? all : all.filter((step) => step.id > since);
    return Promise.resolve({ steps });
  }
  const query = since == null ? "" : `?since=${since}`;
  return request<StepPage>(`/steps${query}`);
}

export function runCheckin(): Promise<CheckinRun> {
  if (USE_MOCK)
    return Promise.resolve({ run_id: "run_mock", queued: 42, live: 2 });
  return request<CheckinRun>("/checkins/run", {
    method: "POST",
    body: JSON.stringify({ disaster_number: 4955 }),
  });
}

export function resetDemo(): Promise<{ ok: true }> {
  if (USE_MOCK) return Promise.resolve({ ok: true });
  return request<{ ok: true }>("/demo/reset", { method: "POST" });
}

export function callPolicyholder(
  id: string,
): Promise<{ call_id: string; status: "calling" }> {
  if (USE_MOCK)
    return Promise.resolve({ call_id: "conv_mock", status: "calling" });
  return request(`/policyholders/${id}/call`, { method: "POST" });
}
