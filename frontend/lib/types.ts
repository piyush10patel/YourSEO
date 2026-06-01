// Types mirroring the FastAPI contract (app/schemas + services).

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  domain: string | null;
  created_at: string;
}

export interface Recommendation {
  id: string;
  project_id: string;
  audit_id: string | null;
  type: string;
  title: string;
  detail: string | null;
  impact: number;
  confidence: number;
  effort: number;
  priority: number;
  status: string;
  created_at: string;
}

export interface Audit {
  id: string;
  project_id: string;
  page_id: string | null;
  overall_score: number;
  grade: string;
  confidence: string;
  created_at: string;
}

export interface Keyword {
  id: string;
  project_id: string;
  keyword: string;
  volume: number | null;
  difficulty: number | null;
  intent: string | null;
  cluster_id: string | null;
}

export interface Cluster {
  id: string;
  project_id: string;
  topic: string;
  topic_id: string | null;
}

export interface AgentResult {
  id: string;
  agent: string;
  confidence: number;
  impact: number;
  rationale: string;
  evidence: string[];
  recommendations: string[];
}

export interface Report {
  project: { name: string; domain: string | null };
  seo_score: number | null;
  grade: string | null;
  score_trend: number[];
  pages: number;
  keywords: number;
  clusters: number;
  recommendations_by_status: Record<string, number>;
  issues_by_type: Record<string, number>;
  kpis: Record<string, unknown>;
  generated_at: string;
}
