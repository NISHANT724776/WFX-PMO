import Image from "next/image";
import Link from "next/link";
import { PageHeader } from "@/components/ui";

type Shot = { src: string; alt: string; notes: string[] };
type Stage = { n: number; title: string; where: string; lead: string; steps: string[]; shot: Shot; reqs: number[]; note?: string };

const STAGES: Stage[] = [
  {
    n: 1, title: "Bring the Excel in", where: "Smart Import",
    lead: "Upload the workbook you already keep. The app reads every sheet, suggests which column is which, and shows you the result before anything is saved.",
    steps: ["Choose a workbook (XLSX, XLS or CSV, up to 25 MB).", "Review the suggested mapping and fix any column the app guessed wrong.", "Validate: problems are listed row by row, nothing is saved yet.", "Commit. A committed import can be rolled back, so a wrong upload is never permanent."],
    shot: { src: "/guide/import.png", alt: "Smart Import page with upload area and import history", notes: ["Drop zone: one workbook can hold the plan, trackers, pending items and more.", "Import history: every upload, who did it, and whether it is committed, ready or rolled back."] },
    reqs: [10],
  },
  {
    n: 2, title: "Everything lands in one connected project", where: "Projects",
    lead: "Each customer's project holds its products, sites and every record imported for it. Nothing lives in a separate file any more.",
    steps: ["Open a project from the Projects list.", "The Overview shows plan items, delayed items and open pending items at a glance.", "Products and sites are attached once and reused by every tab.", "Tabs along the top are the project's working areas."],
    shot: { src: "/guide/overview.png", alt: "Project overview with KPI cards and tabs", notes: ["Tabs: Plan, Delivery, Pending, UAT, Reports & integrations and Trackers all belong to this project.", "KPI cards: the four numbers management asks first, always live."] },
    reqs: [1, 2],
  },
  {
    n: 3, title: "Plan the work and watch it move", where: "Project → Plan",
    lead: "The project plan runs customer-wise and product-wise, as a table, a Gantt chart or a calendar. Filter to one product or see them all.",
    steps: ["Switch between Table, Gantt and Calendar.", "Filter by product, status or delayed-only.", "Each task shows responsible party, owner, location, onsite or online mode, planned, revised and actual dates.", "Edit inline or open the side panel for the full record."],
    shot: { src: "/guide/plan.png", alt: "Project plan table grouped by phase", notes: ["Planned, Revised and Actual sit side by side for every task.", "Status and a red “late” flag come from the dates, not from opinions."] },
    reqs: [1, 2],
  },
  {
    n: 4, title: "Trace requirements through to delivery", where: "Project → Delivery, UAT, Reports & integrations",
    lead: "Requirements, gaps, integrations, reports and UAT scenarios are separate registers that can be linked, so you can follow one requirement all the way to its test.",
    steps: ["Delivery holds requirements (BRD), gaps and specifications, helpdesk items and actions.", "Reports & integrations lists every report, print and integration with owner, status and target.", "UAT lists test scenarios and defects with their result.", "Links connect records across registers; suggested links are offered but never applied without you."],
    shot: { src: "/guide/integrations.png", alt: "Reports and integrations register", notes: ["Counts at the top: how many are late and how many fall due in the next 14 days.", "Switch between the integration register and the reports and prints inventory."] },
    reqs: [5, 6],
  },
  {
    n: 5, title: "Know what each side owes", where: "Project → Pending",
    lead: "Pending activities are split by who must act: the customer, WFX, an external partner or an internal team.",
    steps: ["Four cards show open and overdue items per party.", "Click a party to focus the list on it.", "Every item has an owner, a target date and a late flag.", "Open an item to see its date history and add a comment."],
    shot: { src: "/guide/pending.png", alt: "Pending activities with customer and WFX cards", notes: ["Pending with Customer and Pending with WFX are counted separately.", "Revised column shows how far each commitment has moved (the +31d style badge)."] },
    reqs: [3, 4],
  },
  {
    n: 6, title: "Keep discussions and scope with the record", where: "Side panels",
    lead: "Every record opens in a side panel with its own comments, dependencies and custom fields, so decisions are not lost in email.",
    steps: ["Click any row to open its panel.", "Add a comment; it is kept with the record and its author.", "Record what a task waits for under Dependencies.", "Extra fields your team defined (drop-down, date, text) appear in the panel."],
    shot: { src: "/guide/plan-drawer.png", alt: "Plan item side panel", notes: ["The record's own fields at the top: status, phase, product, owner, dates.", "Scroll down for Date revisions (see stage 8), dependencies, custom fields and the discussion thread."] },
    reqs: [1, 2],
  },
  {
    n: 7, title: "Look at the week ahead", where: "Project → Dashboards → Week plan",
    lead: "The Week plan lists what is due this week and next, so a weekly review starts from facts.",
    steps: ["Open Dashboards and choose Week plan.", "Set the report date to the Monday you are planning from.", "Work through what is due, who owns it and what is already late."],
    shot: { src: "/guide/weekplan.png", alt: "Week plan dashboard showing next week", notes: ["Period: this week or next week; weeks run Monday to Sunday.", "Cards are grouped by product, and overdue items stand out in red."] },
    reqs: [8],
    note: "A separate daily or weekly work-breakdown board is not built yet. The Week plan dashboard is the weekly view today.",
  },
  {
    n: 8, title: "Never lose the original date", where: "Every date in the app",
    lead: "The first committed date is kept forever. When a date moves, the move is recorded with a reason, who asked and who approved. Reports show how far reality drifted from the first promise.",
    steps: ["Original: the baseline, never overwritten.", "Revised: the latest approved date. Only approved revisions move it.", "Actual: what really happened, recorded when the work finishes.", "Deviation: days between original and current, shown as a badge. History lists each revision with its reason."],
    shot: { src: "/guide/pending-drawer.png", alt: "Date commitment strip and revision timeline", notes: ["Original, Current (approved) and Actual in one strip.", "Revision timeline: status, reason, requester and approver for every change."] },
    reqs: [9],
  },
  {
    n: 9, title: "Read it on the dashboards", where: "Project → Dashboards",
    lead: "Overall status, product coverage, delays, department by location and sign-off gates all come from the same records, so a number on a dashboard always matches the list behind it.",
    steps: ["Pick a dashboard kind and a report date.", "Click a card, a bar or a phase to drill into the records.", "Print or save as PDF, or export to PowerPoint or Excel, from the same page."],
    shot: { src: "/guide/dashboard.png", alt: "Overall status dashboard", notes: ["Dashboard kinds along the top: status, coverage, week plan, delays, department by location, sign-off gates.", "Print, PowerPoint and Excel export sit just below."] },
    reqs: [7, 10],
  },
];

const REQS: { n: number; req: string; where: string; how: string; does: string; gain: string }[] = [
  { n: 1, req: "Project plan, customer and product wise", where: "Project → Plan", how: "Open the project, pick a product or all products, switch between Table, Gantt and Calendar.", does: "Shows milestones and tasks with responsible party, owner, location, onsite/online mode, planned, revised and actual dates, plus the extra fields your team defines.", gain: "One plan per customer that anyone can filter, instead of one spreadsheet per person." },
  { n: 2, req: "Project tracker for the same customer", where: "Project → Trackers", how: "Open Trackers and choose milestone events, sign-off gates or the gap/specification tracker.", does: "Holds the customer's own tracker rows beside the plan, with planned and actual dates and a product filter.", gain: "The customer tracker and the plan are read together." },
  { n: 3, req: "Pending activities with the customer", where: "Project → Pending", how: "Click the Pending with Customer card or filter the list.", does: "Lists customer-owned items with owner, target, revised date, late flag and history.", gain: "A clear list of what the customer still owes, with days late." },
  { n: 4, req: "Pending activities with WFX", where: "Project → Pending", how: "Click the Pending with WFX card.", does: "Lists WFX-owned items the same way, counted separately from the customer's.", gain: "Accountability on both sides, not just one." },
  { n: 5, req: "UAT scenarios with status", where: "Project → UAT", how: "Open UAT, filter by result, module, cycle or tester.", does: "Tracks scenarios and defects. A scenario cannot be marked Passed while it has an open defect.", gain: "Clear test readiness before go-live." },
  { n: 6, req: "Reports, prints and integrations tracker", where: "Project → Reports & integrations", how: "Open the tab and switch between integrations and reports + prints.", does: "Lists each item with owner, status, target and revised date, and counts what is late or due in 14 days.", gain: "The long tail of deliverables is visible, not buried." },
  { n: 7, req: "Delay dashboard across plan, trackers, pending and development", where: "Project → Dashboards → Delays", how: "Open Dashboards and choose Delays.", does: "Combines late items from the plan, trackers, pending items and delivery registers using the same delay rule (grace days are set on the Overview).", gain: "One answer to “what is late and by how much”." },
  { n: 8, req: "Tasks due this week and next week", where: "Project → Dashboards → Week plan", how: "Open Week plan and set the report date.", does: "Lists what falls due in the current and following week.", gain: "A weekly review that starts from facts." },
  { n: 9, req: "Original and revised target dates preserved", where: "Plan, Pending, Delivery, Reports & integrations side panels", how: "Open any record: the date strip and revision timeline are at the top.", does: "Keeps the baseline untouched, records every revision with reason, requester and approver, and shows the deviation in days.", gain: "Slippage is measured against the first promise, with the reason on record." },
  { n: 10, req: "Excel import and export", where: "Smart Import; Dashboards → Reports & exports", how: "Import a workbook under Smart Import. Export from Dashboards: PDF, PowerPoint and Excel.", does: "Imports map columns, validate, commit and can roll back. A new workbook feeds the same dashboards, so they stay interactive. Exports are built from the same figures as the screen.", gain: "Excel stays the input and the output format people already trust." },
];

function Frame({ shot }: { shot: Shot }) {
  return (
    <figure className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_8px_30px_rgba(16,24,40,0.06)]">
      <div className="flex items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-3 py-2" aria-hidden="true">
        <span className="h-2.5 w-2.5 rounded-full bg-slate-300" /><span className="h-2.5 w-2.5 rounded-full bg-slate-300" /><span className="h-2.5 w-2.5 rounded-full bg-slate-300" />
        <span className="ml-3 rounded-md bg-white px-3 py-0.5 text-[11px] text-slate-400 ring-1 ring-slate-200">WFX PMO</span>
      </div>
      <Image src={shot.src} alt={shot.alt} width={1440} height={900} className="h-auto w-full" />
      <figcaption className="border-t border-slate-100 bg-slate-50/60 px-4 py-3">
        <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-400">What to look at</div>
        <ol className="space-y-1.5 text-[13px] text-slate-600">
          {shot.notes.map((t, i) => (
            <li key={i} className="flex gap-2"><span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-blue-900 text-[10px] font-semibold text-white">{i + 1}</span><span>{t}</span></li>
          ))}
        </ol>
      </figcaption>
    </figure>
  );
}

function DateDiagram() {
  const box = "rounded-lg border px-3 py-2 text-center";
  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/60 p-4" role="img" aria-label="Diagram: original date stays fixed, revisions move the current date, actual closes it">
      <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">How one date lives (illustration, no real dates)</div>
      <div className="flex flex-wrap items-stretch gap-2 text-sm">
        <div className={`${box} flex-1 border-slate-300 bg-white`}><div className="text-[10px] uppercase tracking-wider text-slate-400">1 · Original</div><div className="font-semibold text-slate-700">Baseline</div><div className="text-[11px] text-slate-500">Never changes</div></div>
        <span className="self-center text-slate-300">→</span>
        <div className={`${box} flex-1 border-amber-200 bg-amber-50`}><div className="text-[10px] uppercase tracking-wider text-amber-700">2 · Revised</div><div className="font-semibold text-blue-950">Latest approved</div><div className="text-[11px] text-slate-500">Reason + requester + approver</div></div>
        <span className="self-center text-slate-300">→</span>
        <div className={`${box} flex-1 border-green-200 bg-green-50`}><div className="text-[10px] uppercase tracking-wider text-green-700">3 · Actual</div><div className="font-semibold text-green-800">Finished on</div><div className="text-[11px] text-slate-500">Recorded at completion</div></div>
        <span className="self-center text-slate-300">=</span>
        <div className={`${box} flex-1 border-blue-200 bg-white`}><div className="text-[10px] uppercase tracking-wider text-blue-900">Deviation</div><div className="font-semibold text-blue-950">Days vs original</div><div className="text-[11px] text-slate-500">Shown as a +Nd badge</div></div>
      </div>
    </div>
  );
}

export default function GuidePage() {
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="How WFX PMO works" subtitle="A read-only guide in nine stages, using screens from the live application" actions={<Link href="/projects" className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Open Projects</Link>} />

      <nav aria-label="Stages" className="sticky top-14 z-20 -mx-1 mb-8 overflow-x-auto bg-white/90 py-2 backdrop-blur">
        <ol className="flex min-w-max items-center gap-1 px-1">
          {STAGES.map((s, i) => (
            <li key={s.n} className="flex items-center gap-1">
              {i > 0 && <span className="h-px w-4 bg-slate-200" />}
              <a href={`#stage-${s.n}`} className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-slate-600 transition-colors hover:bg-blue-50 hover:text-blue-900">
                <span className="grid h-5 w-5 place-items-center rounded-full bg-blue-900 text-[10px] font-semibold text-white">{s.n}</span>{s.title.split(" ").slice(0, 3).join(" ")}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <div className="space-y-14">
        {STAGES.map((s) => (
          <section key={s.n} id={`stage-${s.n}`} className="scroll-mt-28">
            <div className="mb-3 flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-blue-700 to-blue-950 text-sm font-semibold text-white shadow-sm">{s.n}</span>
              <div>
                <h2 className="text-lg font-semibold tracking-tight text-blue-950">{s.title}</h2>
                <div className="text-xs text-slate-500">{s.where} · covers requirement{s.reqs.length > 1 ? "s" : ""} {s.reqs.join(", ")}</div>
              </div>
            </div>
            <p className="mb-4 max-w-3xl text-sm text-slate-600">{s.lead}</p>
            <ol className="mb-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {s.steps.map((t, i) => (
                <li key={i} className="flex gap-2.5 rounded-lg border border-slate-200 bg-white p-3 text-[13px] text-slate-700">
                  <span className="mt-px grid h-5 w-5 shrink-0 place-items-center rounded-md bg-blue-50 text-[11px] font-semibold text-blue-900">{i + 1}</span>{t}
                </li>
              ))}
            </ol>
            {s.note && <p className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[13px] text-amber-900"><b>Not built yet.</b> {s.note}</p>}
            <Frame shot={s.shot} />
            {s.n === 8 && <DateDiagram />}
          </section>
        ))}
      </div>

      <section className="mt-16" id="coverage">
        <h2 className="mb-1 text-lg font-semibold tracking-tight text-blue-950">Requirements coverage</h2>
        <p className="mb-4 max-w-3xl text-sm text-slate-500">All ten business requirements, one row each. Requirement 10 also covers the interactive dashboard that a newly imported workbook feeds.</p>
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full min-w-[920px] text-left text-[13px]">
            <thead className="bg-slate-50">
              <tr><th className="px-3">#</th><th className="px-3">Requirement</th><th className="px-3">Where in the app</th><th className="px-3">How you use it</th><th className="px-3">What the app does</th><th className="px-3">What management gains</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100 align-top">
              {REQS.map((r) => (
                <tr key={r.n}>
                  <td className="px-3 py-2"><span className="grid h-6 w-6 place-items-center rounded-full bg-blue-900 text-[11px] font-semibold text-white">{r.n}</span></td>
                  <td className="px-3 py-2 font-medium text-blue-950">{r.req}</td><td className="px-3 py-2">{r.where}</td><td className="px-3 py-2 text-slate-600">{r.how}</td><td className="px-3 py-2 text-slate-600">{r.does}</td><td className="px-3 py-2 text-slate-600">{r.gain}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-slate-500">Not built yet: daily or weekly work-breakdown board, notifications, global search, team workload view.</p>
      </section>
    </div>
  );
}
