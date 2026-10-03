import { Link } from "@tanstack/react-router";

import {
  CONTENT_TYPE_LABELS,
  CONTENT_VISIBILITY_LABELS,
  MODERATION_STATUS_LABELS,
  useHomeCurationsQuery,
  type AdminHomeCurationSlot,
} from "@/entities/admin-content";

/** 유형별 홈 큐레이션 현황. 지정·해제는 작품 상세에서 하고, 여기서는 무엇이 걸려 있고 지금 홈에 실제로 보이는지만
 * 보인다 — 지정 뒤 이용제한·비공개가 되면 지정은 남은 채 홈에서만 빠지기 때문이다. */
export function HomeCurationStatus() {
  const homeCurationsQuery = useHomeCurationsQuery();

  return (
    <section aria-labelledby="home-curation-status-heading" className="flex flex-col gap-3">
      <h2 id="home-curation-status-heading" className="text-sm font-medium text-muted-foreground">
        홈 큐레이션
      </h2>
      {homeCurationsQuery.isPending && <div className="h-20 animate-pulse rounded-xl bg-muted" />}
      {homeCurationsQuery.isError && (
        <p className="text-sm text-destructive-text">홈 큐레이션 현황을 불러오지 못했어요.</p>
      )}
      {homeCurationsQuery.isSuccess && (
        <ul className="grid gap-3 sm:grid-cols-2">
          {homeCurationsQuery.data.map((slot) => (
            <HomeCurationSlotCard key={slot.type} slot={slot} />
          ))}
        </ul>
      )}
    </section>
  );
}

type HomeCurationSlotCardProps = {
  slot: AdminHomeCurationSlot;
};

function HomeCurationSlotCard({ slot }: HomeCurationSlotCardProps) {
  const typeLabel = CONTENT_TYPE_LABELS[slot.type];

  if (slot.content === null) {
    return (
      <li className="flex flex-col gap-1 rounded-xl border border-border bg-card p-4">
        <span className="text-xs font-medium text-muted-foreground">{typeLabel}</span>
        <span className="text-sm text-muted-foreground">지정 안 됨 — 홈에 섹션이 없어요.</span>
      </li>
    );
  }

  return (
    <li>
      <Link
        to="/contents/$contentId"
        params={{ contentId: slot.content.id }}
        className="flex items-center gap-3 rounded-xl border border-border bg-card p-4 hover:bg-secondary"
      >
        <div className="size-12 shrink-0 overflow-hidden rounded-lg bg-secondary">
          {!!slot.content.thumbnailUrl && <img src={slot.content.thumbnailUrl} alt="" className="size-full object-cover" />}
        </div>
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-xs font-medium text-muted-foreground">{typeLabel}</span>
          <span className="truncate text-sm font-semibold text-foreground">{slot.content.name || "(이름 없음)"}</span>
          <span className={slot.isListed ? "text-xs text-muted-foreground" : "text-xs text-destructive-text"}>
            {slot.isListed
              ? "홈에 보이는 중"
              : `홈에 안 보임 · ${CONTENT_VISIBILITY_LABELS[slot.content.visibility]} · ${MODERATION_STATUS_LABELS[slot.content.moderationStatus]}`}
          </span>
        </div>
      </Link>
    </li>
  );
}
