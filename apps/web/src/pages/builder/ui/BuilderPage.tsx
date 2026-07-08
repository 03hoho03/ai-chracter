import { useContentDraftQuery } from "../../../entities/content";
import { ComingSoonPage } from "../../../shared/ui/ComingSoonPage";
import { CharacterBuilderShell } from "../../../widgets/build-character";

function BuilderSkeleton() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <div className="h-9 w-40 animate-pulse rounded-lg bg-muted" />
      <div className="h-8 w-full animate-pulse rounded-lg bg-muted" />
      <div className="h-64 w-full animate-pulse rounded-xl bg-muted" />
    </main>
  );
}

/** techspec-builder-common.md §2 — 초안 이어쓰기 진입점. `data.type` 판별값으로 캐릭터/스토리
 * 빌더를 나눈다(스토리 빌더는 US-106까지 ComingSoonPage로 남겨둔다). */
export function BuilderPage({ draftId }: { draftId: string }) {
  const draftQuery = useContentDraftQuery(draftId);

  if (draftQuery.isPending) return <BuilderSkeleton />;

  if (draftQuery.isError) {
    return (
      <main className="mx-auto flex min-h-[60vh] max-w-2xl flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="text-sm text-destructive">초안을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      </main>
    );
  }

  if (draftQuery.data.type === "character") {
    return <CharacterBuilderShell data={draftQuery.data} />;
  }

  return <ComingSoonPage title="스토리 빌더" description="스토리 빌더 화면을 준비하고 있어요." />;
}
