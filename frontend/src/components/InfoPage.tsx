import type { ReactNode } from 'react';

interface InfoSection {
  title: string;
  children: ReactNode;
}

interface InfoPageProps {
  eyebrow: string;
  title: string;
  description: string;
  updated: string;
  sections: InfoSection[];
}

export function InfoPage({ eyebrow, title, description, updated, sections }: InfoPageProps) {
  return (
    <main className="page-container pb-20 pt-12 sm:pb-28 sm:pt-16">
      <section className="mx-auto max-w-[920px]">
        <p className="text-[12px] font-bold uppercase tracking-[0.08em] text-emerald-600">{eyebrow}</p>
        <h1 className="mt-4 text-[44px] font-bold leading-tight tracking-[-0.04em] text-slate-900 sm:text-[56px]">
          {title}
        </h1>
        <p className="mt-5 max-w-[760px] text-[17px] leading-8 text-slate-600">{description}</p>
        <p className="mt-4 text-[13px] font-medium text-slate-400">Last updated: {updated}</p>
      </section>

      <section className="mx-auto mt-12 max-w-[920px] divide-y divide-slate-100 border-y border-slate-100">
        {sections.map((section) => (
          <article key={section.title} className="grid gap-5 py-9 lg:grid-cols-[240px_1fr]">
            <h2 className="text-[20px] font-bold tracking-[-0.02em] text-slate-900">{section.title}</h2>
            <div className="space-y-4 text-[15px] leading-7 text-slate-600">{section.children}</div>
          </article>
        ))}
      </section>
    </main>
  );
}
