import { Link, useParams } from "@tanstack/react-router";

export function RunDetailPage() {
  const { runId } = useParams({ from: "/runs/$runId" });

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <Link to="/" className="text-sm text-ink-muted underline-offset-4 hover:underline">
        런 목록
      </Link>
      <h1 className="mt-2 text-lg font-semibold break-all">{runId}</h1>
      <p className="mt-2 text-sm text-ink-muted">이 런의 상태 타임라인·대화 흐름·턴 상세가 여기에 놓인다.</p>
    </main>
  );
}
