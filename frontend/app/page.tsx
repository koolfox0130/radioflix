const API_BASE_URL =
  process.env.RADIOFLIX_API_URL ?? "http://127.0.0.1:8000";

async function getPrograms() {
  const res = await fetch(`${API_BASE_URL}/programs`, {
    cache: "no-store",
  });

  if (!res.ok) {
    return [];
  }

  return res.json();
}

async function getRecommendations() {
  const res = await fetch(`${API_BASE_URL}/recommendations`, {
    cache: "no-store",
  });

  if (!res.ok) {
    return [];
  }

  return res.json();
}

type Program = {
  title: string;
  network: string;
  category: string;
  reason?: string;
  raw_name?: string;
};

function ProgramCard({
  program,
  showReason = false,
}: {
  program: Program;
  showReason?: boolean;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl min-w-44 max-w-44 h-40 shrink-0 p-4 flex flex-col justify-between shadow-lg">
      <div>
        <div className="text-base font-bold leading-snug line-clamp-3">
          {program.title}
        </div>

        {showReason && program.reason && (
          <div className="text-xs text-zinc-400 mt-2 leading-relaxed line-clamp-2">
            {program.reason}
          </div>
        )}
      </div>

      <div>
        <div className="text-xs text-zinc-400 truncate">
          {program.network || "不明"}
        </div>

        <div className="inline-block text-xs text-yellow-300 bg-yellow-300/10 px-2 py-1 rounded-full mt-2">
          {program.category || "その他"}
        </div>
      </div>
    </div>
  );
}

function ProgramRow({
  title,
  subtitle,
  programs,
  showReason = false,
}: {
  title: string;
  subtitle?: string;
  programs: Program[];
  showReason?: boolean;
}) {
  if (!programs || programs.length === 0) {
    return null;
  }

  return (
    <section className="mb-9">
      <div className="mb-3">
        <h2 className="text-xl font-bold">{title}</h2>

        {subtitle && (
          <p className="text-sm text-zinc-400 mt-1">
            {subtitle}
          </p>
        )}
      </div>

      <div className="flex gap-3 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {programs.map((program: Program) => (
          <ProgramCard
            key={`${title}-${program.title}`}
            program={program}
            showReason={showReason}
          />
        ))}
      </div>
    </section>
  );
}

export default async function Home() {
  const programs: Program[] = await getPrograms();
  const recommendations: Program[] = await getRecommendations();

  const annPrograms = programs.filter(
    (program) => program.category === "ANN"
  );

  const junkPrograms = programs.filter(
    (program) => program.category === "JUNK"
  );

  const guruPrograms = programs.filter(
    (program) => program.category === "GURU"
  );

  return (
    <main className="min-h-screen bg-black text-white">
      <div className="sticky top-0 z-10 bg-black/90 backdrop-blur px-4 pt-5 pb-3">
        <h1 className="text-3xl font-black tracking-tight">
          📻 RadioFlix
        </h1>

        <p className="text-sm text-zinc-400 mt-1">
          芸人ラジオを見つける、自分専用ホーム
        </p>
      </div>

      <div className="px-4 pt-4 pb-10">
        <ProgramRow
          title="あなたへのおすすめ"
          subtitle="今の録音傾向から選んだ番組"
          programs={recommendations}
          showReason={true}
        />

        <ProgramRow
          title="録音中"
          subtitle="NASに保存されている番組"
          programs={programs}
        />

        <ProgramRow
          title="ANN好き向け"
          subtitle="ニッポン放送・ANN系"
          programs={annPrograms}
        />

        <ProgramRow
          title="JUNK好き向け"
          subtitle="TBSラジオ・JUNK系"
          programs={junkPrograms}
        />

        <ProgramRow
          title="その他の録音番組"
          subtitle="J-WAVEなど"
          programs={guruPrograms}
        />
      </div>
    </main>
  );
}