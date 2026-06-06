import Link from "next/link";

const API_BASE_URL =
  process.env.RADIOFLIX_API_URL ?? "http://127.0.0.1:8000";

type Program = {
  id: string;
  title: string;
  network: string;
  category: string;
  reason?: string;
  raw_name?: string;
};

async function getProgram(id: string): Promise<Program | null> {
  const res = await fetch(
    `${API_BASE_URL}/programs/${encodeURIComponent(id)}`,
    {
      cache: "no-store",
    }
  );

  if (!res.ok) {
    return null;
  }

  return res.json();
}

export default async function ProgramDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const program = await getProgram(id);

  if (!program) {
    return (
      <main className="min-h-screen bg-black text-white px-4 py-6">
        <Link href="/" className="text-zinc-400">
          ← 戻る
        </Link>

        <h1 className="text-2xl font-bold mt-8">
          番組が見つかりません
        </h1>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-black text-white">
      <div className="px-4 pt-6 pb-4">
        <Link href="/" className="text-sm text-zinc-400">
          ← RadioFlixへ戻る
        </Link>
      </div>

      <section className="px-4 pb-10">
        <div className="bg-[#232428] border border-[#34363b] rounded-3xl p-6 shadow-xl">
          <div className="text-xs text-yellow-300 bg-yellow-300/10 inline-block px-3 py-1 rounded-full mb-4">
            {program.category || "その他"}
          </div>

          <h1 className="text-3xl font-black leading-tight">
            {program.title}
          </h1>

          <div className="mt-4 text-zinc-300">
            {program.network || "放送局不明"}
          </div>

          {program.reason && (
            <div className="mt-6">
              <h2 className="text-lg font-bold mb-2">
                おすすめ理由
              </h2>

              <p className="text-zinc-300 leading-relaxed">
                {program.reason}
              </p>
            </div>
          )}

          <div className="mt-6">
            <h2 className="text-lg font-bold mb-2">
              録音状態
            </h2>

            <p className="text-zinc-300">
              {program.category === "おすすめ"
                ? "まだ録音していないおすすめ番組です"
                : "NASに録音フォルダがあります"}
            </p>
          </div>

          {program.raw_name && (
            <div className="mt-6">
              <h2 className="text-lg font-bold mb-2">
                元フォルダ名
              </h2>

              <p className="text-xs text-zinc-500 break-all">
                {program.raw_name}
              </p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}