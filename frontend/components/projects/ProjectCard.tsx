"use client";

// Ported from PersonalWebsite's ProjectCard + SoftwareProjectCard: a dark
// card that lifts and glows on hover, a 180px visual zone (cover image, or a
// hover-to-rotate STL preview when the project's card is a model), the title
// in the accent colour, the summary, stack chips and a GitHub mark top-right.
// No visual at all -> the website's terminal title bar (~/projects/<slug>).

import { useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { kbAssetUrl } from "@/lib/api";
import type { ProjectStatus, ProjectSummary } from "@/lib/projectsApi";
import { Badge } from "@/components/ui/Panel";
import GithubIcon from "./GithubIcon";

const STLViewer = dynamic(() => import("@/components/STLViewer"), { ssr: false });

export const STATUS_LABEL: Record<ProjectStatus, string> = { doing: "Doing", planned: "Planned", done: "Done" };
export const STATUS_TONE: Record<ProjectStatus, "accent" | "warn" | "ok"> = { doing: "accent", planned: "warn", done: "ok" };

export function countLine(p: ProjectSummary): string {
  const c = p.counts;
  const bits: string[] = [];
  if (c.model) bits.push(`${c.model} model${c.model > 1 ? "s" : ""}`);
  if (c.notes) bits.push(`${c.notes} note${c.notes > 1 ? "s" : ""}`);
  if (c.image) bits.push(`${c.image} image${c.image > 1 ? "s" : ""}`);
  if (c.pdf + c.doc) bits.push(`${c.pdf + c.doc} doc${c.pdf + c.doc > 1 ? "s" : ""}`);
  if (c.video) bits.push(`${c.video} video${c.video > 1 ? "s" : ""}`);
  if (c.worklogs) bits.push(`${c.worklogs} work-log day${c.worklogs > 1 ? "s" : ""}`);
  return bits.join(" · ");
}

export default function ProjectCard({ project, href }: { project: ProjectSummary; href: string }) {
  const [hover, setHover] = useState(false);
  const card = project.card;
  const meta = countLine(project);

  return (
    <div
      className="group relative flex flex-col overflow-hidden rounded-lg border border-line bg-surface/90 shadow-panel transition duration-200 hover:-translate-y-1.5 hover:border-accent/40 hover:shadow-glow"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
    >
      <Link href={href} className="flex flex-1 flex-col text-inherit no-underline">
        {card ? (
          <div className="h-[180px] overflow-hidden border-b border-line bg-black/40">
            {card.kind === "stl" ? (
              <STLViewer url={kbAssetUrl(card.folder, card.path)} height={180} hover={hover} controls={false} zoom={false} />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={kbAssetUrl(card.folder, card.path)} alt={project.title} className="h-full w-full object-cover" />
            )}
          </div>
        ) : (
          <div className="flex items-center gap-1.5 border-b border-line bg-black/40 px-3.5 py-2 font-mono text-xs text-muted/70" aria-hidden="true">
            <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_6px_rgb(34_211_238/0.6)]" />
            <span className="h-2 w-2 rounded-full bg-white/10" />
            <span className="h-2 w-2 rounded-full bg-white/10" />
            <span className="ml-2 truncate">~/projects/{project.slug}</span>
          </div>
        )}
        <div className="flex flex-1 flex-col p-4">
          <div className="mb-1.5 flex items-start gap-2 pr-6">
            <h3 className="min-w-0 flex-1 text-base font-semibold text-accent">{project.title}</h3>
          </div>
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <Badge tone={STATUS_TONE[project.status]}>{STATUS_LABEL[project.status]}</Badge>
            {project.private && <Badge tone="muted">private</Badge>}
            {!project.hub && <Badge tone="muted">no hub note</Badge>}
          </div>
          {project.summary && <p className="mb-3 line-clamp-3 flex-1 text-sm leading-relaxed text-foreground/80">{project.summary}</p>}
          {project.stack.length > 0 && (
            <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Stack">
              {project.stack.map((t) => (
                <li key={t} className="rounded border border-accent/25 bg-accent/5 px-1.5 py-0.5 font-mono text-[11px] text-accent/90">
                  {t}
                </li>
              ))}
            </ul>
          )}
          {meta && <p className="mt-auto font-mono text-[10px] uppercase tracking-wider text-muted">{meta}</p>}
        </div>
      </Link>
      {project.repo && (
        <a
          href={project.repo}
          target="_blank"
          rel="noopener noreferrer"
          title="View on GitHub"
          aria-label={`${project.title} on GitHub`}
          className={`absolute right-2.5 ${card ? "top-[190px]" : "top-1.5"} leading-none text-muted transition-colors hover:text-accent`}
        >
          <GithubIcon size={18} />
        </a>
      )}
    </div>
  );
}
