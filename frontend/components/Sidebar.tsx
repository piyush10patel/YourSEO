import Link from "next/link";

export function Sidebar() {
  return (
    <aside className="flex w-60 flex-col gap-1 bg-gradient-to-b from-brand-dark to-brand p-5 text-white">
      <div className="mb-6 flex items-center gap-2 text-xl font-extrabold">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/20">
          🚀
        </span>
        SEOOS
      </div>
      <nav className="flex flex-col gap-1 text-sm font-semibold">
        <Link href="/" className="rounded-lg px-3 py-2 hover:bg-white/10">
          Dashboard
        </Link>
        <Link href="/" className="rounded-lg px-3 py-2 hover:bg-white/10">
          Projects
        </Link>
      </nav>
      <p className="mt-auto text-xs text-white/70">
        AI SEO Operating System
      </p>
    </aside>
  );
}
