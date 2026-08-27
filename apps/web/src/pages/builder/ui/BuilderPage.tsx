import { useMemo } from "react";

import { createEmptyDraft, useContentDraftQuery, type ContentType } from "@/entities/content";
import { CharacterBuilderShell } from "@/widgets/build-character";
import { StoryBuilderShell } from "@/widgets/build-story";
import { PreviewSessionView } from "@/widgets/preview-session";

/**
 * techspec-builder-common.md §2 — 초안 만들기(`draftId === null`)와 이어쓰기 양쪽의 화면.
 *
 * 초안은 첫 자동저장 시점에 만들어지므로(US-007) `draftId`가 없는 동안에는 서버 조회 없이
 * `createEmptyDraft(type)`의 로컬 초기값으로 시작한다. 첫 저장이 URL을 초안 주소로 바꿔도 라우트가
 * 하나라 리마운트되지 않는다(`NEW_DRAFT_SEGMENT` 주석).
 *
 * 응답의 `type` 판별값으로 캐릭터/스토리 빌더를 나눈다 — URL의 `$type`은 가독성용이라 신뢰하지 않고,
 * 아직 초안이 없을 때의 초기값을 고를 때만 쓴다.
 */
export function BuilderPage({ type, draftId }: { type: ContentType; draftId: string | null }) {
  const draftQuery = useContentDraftQuery(draftId);
  const emptyDraft = useMemo(() => createEmptyDraft(type), [type]);

  if (draftId !== null && draftQuery.isPending) return <BuilderSkeleton />;

  if (draftQuery.isError) {
    return (
      <main className="mx-auto flex min-h-[60vh] max-w-2xl flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="text-sm text-destructive-text">초안을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      </main>
    );
  }

  const draft = draftQuery.data ?? emptyDraft;

  if (draft.type === "character") {
    return (
      <CharacterBuilderShell
        draft={draft}
        draftId={draftId}
        renderPreview={(previewProps) => <PreviewSessionView {...previewProps} />}
      />
    );
  }

  return (
    <StoryBuilderShell
      draft={draft}
      draftId={draftId}
      renderPreview={(previewProps) => <PreviewSessionView {...previewProps} />}
    />
  );
}

function BuilderSkeleton() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-10">
      <div className="h-9 w-40 animate-pulse rounded-lg bg-muted" />
      <div className="h-8 w-full animate-pulse rounded-lg bg-muted" />
      <div className="h-64 w-full animate-pulse rounded-xl bg-muted" />
    </main>
  );
}
