import { Button } from "@ai-character-chat/ui/components/button";

import {
  CONTENT_TYPE_LABELS,
  useHomeCurationsQuery,
  type ContentModerationStatusFilter,
  type ContentTypeFilter,
} from "@/entities/admin-content";

import { HomeCurationConfirmModal } from "./HomeCurationConfirmModal";

type HomeCurationSectionProps = {
  contentId: string;
  contentType: ContentTypeFilter;
  contentName: string;
  moderationStatus: ContentModerationStatusFilter;
  /** 지정·해제가 성공하면(확인 모달이 닫힌 뒤) 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 삭제된 작품의 본문 카드. 삭제된 작품은 조치 열이 없지만, 삭제 전에 지정돼 있었다면 해제할 길은 남겨야 해서 같은
 * 판정을 카드로 그린다. 그 밖의 작품은 조치 열·시트 안에서 `HomeCurationActions` 를 쓴다. */
export function HomeCurationSection(props: HomeCurationSectionProps) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
      <h2 className="text-lg font-semibold text-foreground">홈 큐레이션</h2>
      <HomeCurationActions {...props} />
    </section>
  );
}

/** 이 작품을 홈 첫 화면의 유형별 큐레이션으로 지정·해제한다. 지금 공개 목록에 없는 작품(비공개·이용제한 등)은
 * 서버가 400 으로 거부하고 확인 모달이 이유를 알린다 — 그 판정을 여기 복제하지 않는다. 삭제된 작품은 되돌릴 길이
 * 없어 버튼 대신 안내만 둔다. 제목은 감싸는 쪽이 진다(로딩·오류에도 남게). 놓이는 곳이 늘 `card`·`popover`
 * 표면이라 스켈레톤은 `secondary` 다(`muted` 는 같은 값이라 보이지 않는다). */
export function HomeCurationActions({
  contentId,
  contentType,
  contentName,
  moderationStatus,
  onSuccess,
}: HomeCurationSectionProps) {
  const homeCurationsQuery = useHomeCurationsQuery();
  const typeLabel = CONTENT_TYPE_LABELS[contentType];

  if (homeCurationsQuery.isPending) {
    return <div className="h-9 animate-pulse rounded-lg bg-secondary" />;
  }
  if (homeCurationsQuery.isError) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p role="alert" className="text-sm text-destructive-text">
          홈 큐레이션 현황을 불러오지 못했어요.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={() => void homeCurationsQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  const slot = homeCurationsQuery.data.find((item) => item.type === contentType);
  const curatedContent = slot?.content ?? null;

  if (slot !== undefined && curatedContent?.id === contentId) {
    return (
      <div className="flex flex-col gap-3">
        <p className="break-keep text-sm text-foreground">{typeLabel} 홈 큐레이션으로 지정돼 있어요.</p>
        {!slot.isListed && (
          <p className="break-keep text-sm text-muted-foreground">
            지금은 공개 목록에 없어 홈에 보이지 않아요. 공개 상태로 돌아오면 다시 보여요.
          </p>
        )}
        <Button
          type="button"
          variant="outline"
          onClick={() => void HomeCurationConfirmModal.call({ mode: "clear", contentType, contentName, onSuccess })}
        >
          지정 해제
        </Button>
      </div>
    );
  }

  if (moderationStatus === "deleted") {
    return <p className="text-sm text-muted-foreground">삭제된 작품은 지정할 수 없어요.</p>;
  }

  const replacingName = curatedContent === null ? null : curatedContent.name || "(이름 없음)";

  return (
    <div className="flex flex-col gap-3">
      <p className="break-keep text-sm text-muted-foreground wrap-anywhere">
        {replacingName === null ? `지금 지정된 ${typeLabel}가 없어요.` : `지금 지정된 ${typeLabel}: ${replacingName}`}
      </p>
      <Button
        type="button"
        variant="outline"
        onClick={() =>
          void HomeCurationConfirmModal.call({ mode: "set", contentType, contentId, contentName, replacingName, onSuccess })
        }
      >
        홈 큐레이션 지정
      </Button>
    </div>
  );
}
