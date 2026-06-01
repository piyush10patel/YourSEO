import Link from "next/link";
import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-3 text-lg font-bold text-ink">{children}</h2>;
}

const gradeColor = (score: number) =>
  score >= 80 ? "#2b8a3e" : score >= 60 ? "#e8a700" : "#c92a2a";

export function ScoreBadge({
  score,
  grade,
}: {
  score: number | null;
  grade: string | null;
}) {
  if (score === null) {
    return <span className="text-slate-400">No audit yet</span>;
  }
  const color = gradeColor(score);
  return (
    <div className="flex items-center gap-3">
      <div
        className="flex h-16 w-16 items-center justify-center rounded-full text-xl font-extrabold text-white"
        style={{ backgroundColor: color }}
      >
        {score}
      </div>
      <div className="text-sm text-slate-500">
        Grade <span className="font-bold text-ink">{grade}</span>
      </div>
    </div>
  );
}

const badgeTone: Record<string, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-emerald-100 text-emerald-700",
  open: "bg-violet-100 text-violet-700",
  done: "bg-emerald-100 text-emerald-700",
};

export function Pill({ label }: { label: string }) {
  const tone = badgeTone[label.toLowerCase()] ?? "bg-slate-100 text-slate-600";
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}
    >
      {label}
    </span>
  );
}

export function Button({
  children,
  onClick,
  type = "button",
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-dark disabled:opacity-50"
    >
      {children}
    </button>
  );
}

export function LinkButton({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-semibold text-brand hover:bg-slate-50"
    >
      {children}
    </Link>
  );
}
