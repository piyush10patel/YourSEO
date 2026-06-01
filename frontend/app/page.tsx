"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button, Card, LinkButton, SectionTitle } from "@/components/ui";

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      setProjects(await api.listProjects());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await api.createProject(name.trim(), domain.trim() || undefined);
      setName("");
      setDomain("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-1 text-3xl font-extrabold">Projects</h1>
      <p className="mb-6 text-slate-500">
        Create a project, then crawl, audit, cluster keywords, and plan.
      </p>

      <Card className="mb-6">
        <SectionTitle>New project</SectionTitle>
        <form onSubmit={create} className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col">
            <label className="text-xs font-semibold text-slate-500">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Website"
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-col">
            <label className="text-xs font-semibold text-slate-500">Domain</label>
            <input
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="example.com"
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </div>
          <Button type="submit">Create</Button>
        </form>
      </Card>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-slate-400">Loading…</p>
      ) : projects.length === 0 ? (
        <p className="text-slate-400">No projects yet — create one above.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {projects.map((p) => (
            <Card key={p.id} className="flex items-center justify-between">
              <div>
                <div className="font-bold">{p.name}</div>
                <div className="text-sm text-slate-500">{p.domain ?? "—"}</div>
              </div>
              <LinkButton href={`/projects/${p.id}`}>Open</LinkButton>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
