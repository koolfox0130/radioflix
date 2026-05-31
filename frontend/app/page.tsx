async function getPrograms() {
  const res = await fetch("http://127.0.0.1:8000/programs", {
    cache: "no-store",
  });

  return res.json();
}

async function getRecommendations() {
  const res = await fetch("http://127.0.0.1:8000/recommendations", {
    cache: "no-store",
  });

  return res.json();
}

function ProgramRow({
  title,
  programs,
  showReason = false,
}: {
  title: string;
  programs: any[];
  showReason?: boolean;
}) {
  return (
    <section className="mb-10">
      <h2 className="text-xl font-semibold mb-4">{title}</h2>

      <div className="flex gap-3 overflow-x-auto pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {programs.map((program: any) => (
          <div
            key={`${title}-${program.title}`}
            className="bg-zinc-800 p-4 rounded-xl min-w-52 max-w-52 h-40 shrink-0 flex flex-col justify-between"
          >
            <div>
              <div className="font-bold text-base line-clamp-2">
                {program.title}
              </div>

              {showReason && program.reason && (
                <div className="text-xs text-gray-400 mt-2 line-clamp-2">
                  {program.reason}
                </div>
              )}
            </div>

            <div>
              <div className="text-sm text-gray-300">
                {program.network}
              </div>

              <div className="text-xs text-yellow-300 mt-1">
                {program.category}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default async function Home() {
  const programs = await getPrograms();
  const recommendations = await getRecommendations();

  const annPrograms = programs.filter(
    (p: any) => p.category === "ANN"
  );

  const junkPrograms = programs.filter(
    (p: any) => p.category === "JUNK"
  );

  return (
    <main className="min-h-screen bg-black text-white px-4 py-6">
      <h1 className="text-4xl font-bold mb-10">
        📻 RadioFlix
      </h1>

      <ProgramRow
        title="あなたへのおすすめ"
        programs={recommendations}
        showReason={true}
      />

      <ProgramRow
        title="録音中"
        programs={programs}
      />

      <ProgramRow
        title="ANN好き向け"
        programs={annPrograms}
      />

      <ProgramRow
        title="JUNK好き向け"
        programs={junkPrograms}
      />
    </main>
  );
}