export default function Home() {
  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">Quintacle — test UI</h1>
      <p className="opacity-70">
        Talks directly to the local Python core at{" "}
        <code>http://localhost:8000</code>. Nothing here is hosted — this is
        just a way to see the backend working while it&apos;s being built.
      </p>
      <ul className="list-disc list-inside space-y-1">
        <li>
          <b>Journal</b> — nightly dump by subtopic (productive / emotional /
          physical / work / social), each with hours logged directly, no LLM.
        </li>
        <li>
          <b>Goals</b> — set weekly/monthly hour targets per subtopic and see
          progress against them.
        </li>
        <li>
          <b>Day View</b> — Calendar B: pick a date, see everything that
          actually happened that day.
        </li>
        <li>
          <b>Todos</b> — Calendar A: the forward-looking to-do/schedule list.
        </li>
      </ul>
    </div>
  );
}
