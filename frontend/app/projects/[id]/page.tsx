"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { AgentResult, Keyword, Recommendation, Report } from "@/lib/types";
import { Button, Card, Pill, ScoreBadge, SectionTitle } from "@/components/ui";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [report, setReport] = useState<Report | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [plan, setPlan] = useState<AgentResult | null>(null);
  const [kwInput, setKwInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [r, rec, kw] = await Promise.all([
        api.getReport(id),
        api.listRecommendations(id),
        api.listKeywords(id),
      ]);
      setReport(r);
      setRecs(rec);
      setKeywords(kw);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function withBusy(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const addKeywords = () =>
    withBusy(async () => {
      const list = kwInput
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (list.length) await api.addKeywords(id, list);
      setKwInput("");
      await refresh();
    });

  const cluster = () =>
    withBusy(async () => {
      await api.cluster(id);
      await refresh();
    });

  const runPlan = () =>
    withBusy(async () => {
      setPlan(await api.runPlan(id));
    });

  const markDone = (recId: string) =>
    withBusy(async () => {
      await api.setRecommendationStatus(recId, "done");
      await refresh();
    });

  return (
    <div className="mx-auto max-w-5xl">
      <a href="/" className="text-sm text-brand">
        ← Projects
      </a>
      <h1 className="mb-4 mt-1 text-3xl font-extrabold">
        {report?.project.name ?? "Project"}
      </h1>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <SectionTitle>SEO Score</SectionTitle>
          <ScoreBadge score={report?.seo_score ?? null} grade={report?.grade ?? null} />
        </Card>
        <Card>
          <SectionTitle>Inventory</SectionTitle>
          <ul className="text-sm text-slate-600">
            <li>Pages: {report?.pages ?? 0}</li>
            <li>Keywords: {report?.keywords ?? 0}</li>
            <li>Clusters: {report?.clusters ?? 0}</li>
          </ul>
        </Card>
        <Card>
          <SectionTitle>Plan</SectionTitle>
          <Button onClick={runPlan} disabled={busy}>
            Run agent team
          </Button>
        </Card>
      </div>

      {plan && (
        <Card className="mt-4">
          <SectionTitle>✨ Roadmap (Planner)</SectionTitle>
          <p className="mb-2 text-sm text-slate-500">{plan.rationale}</p>
          <ul className="list-disc pl-5 text-sm text-slate-700">
            {plan.recommendations.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <SectionTitle>Recommendations</SectionTitle>
          {recs.length === 0 ? (
            <p className="text-sm text-slate-400">None yet — run a crawl/audit.</p>
          ) : (
            <ul className="space-y-2">
              {recs.slice(0, 12).map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2">
                  <span className="text-sm">
                    <Pill label={r.type} /> {r.title}
                  </span>
                  <span className="flex items-center gap-2">
                    <Pill label={r.status} />
                    {r.status !== "done" && (
                      <button
                        onClick={() => markDone(r.id)}
                        className="text-xs font-semibold text-brand"
                      >
                        mark done
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <SectionTitle>Keywords</SectionTitle>
          <div className="mb-3 flex gap-2">
            <input
              value={kwInput}
              onChange={(e) => setKwInput(e.target.value)}
              placeholder="comma or newline separated"
              className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
            <Button onClick={addKeywords} disabled={busy}>
              Add
            </Button>
            <Button onClick={cluster} disabled={busy}>
              Cluster
            </Button>
          </div>
          {keywords.length === 0 ? (
            <p className="text-sm text-slate-400">No keywords yet.</p>
          ) : (
            <ul className="text-sm text-slate-700">
              {keywords.slice(0, 15).map((k) => (
                <li key={k.id}>
                  {k.keyword}
                  {k.volume != null && (
                    <span className="text-slate-400"> · vol {k.volume}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
