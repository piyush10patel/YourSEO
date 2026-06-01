// Minimal typed client for the SEOOS FastAPI backend.
//
// The browser calls the API directly (CORS is enabled server-side). In dev,
// the API defaults the caller to the "owner" role + default organization, so
// no auth headers are needed yet (Clerk will add them later).

import type {
  AgentResult,
  Audit,
  Cluster,
  Keyword,
  Project,
  Recommendation,
  Report,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8080";

// Clerk seam: when Clerk is wired, call setAuthToken(await getToken()) so the
// API client sends "Authorization: Bearer <jwt>". Until then it's unset and the
// backend runs in dev mode (owner / default org).
let authToken: string | null = null;
export function setAuthToken(token: string | null): void {
  authToken = token;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.message ?? body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string, domain?: string) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, domain: domain || null }),
    }),
  getReport: (id: string) => request<Report>(`/projects/${id}/report`),
  listRecommendations: (id: string) =>
    request<Recommendation[]>(`/projects/${id}/recommendations`),
  listAudits: (id: string) => request<Audit[]>(`/projects/${id}/audits`),
  listKeywords: (id: string) => request<Keyword[]>(`/projects/${id}/keywords`),
  listClusters: (id: string) => request<Cluster[]>(`/projects/${id}/clusters`),
  addKeywords: (id: string, keywords: string[]) =>
    request<Keyword[]>(`/projects/${id}/keywords`, {
      method: "POST",
      body: JSON.stringify({ keywords }),
    }),
  cluster: (id: string) =>
    request<Cluster[]>(`/projects/${id}/cluster`, { method: "POST" }),
  setRecommendationStatus: (recId: string, status: string) =>
    request<Recommendation>(`/recommendations/${recId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  runPlan: (id: string) =>
    request<AgentResult>(`/projects/${id}/plan`, { method: "POST" }),
};

export { BASE as API_BASE };
