import { Link } from "@tanstack/react-router";

import {
  NOVEL_MODERATION_STATUS_LABELS,
  NOVEL_VISIBILITY_LABELS,
  useHomeNovelCurationsQuery,
  type AdminHomeNovelCurationSlot,
} from "@/entities/admin-novel";

/** 홈 노벨 자리 현황(1번부터 끝까지, 빈 자리 포함). 걸기·비우기는 노벨 상세에서 하고, 여기서는 무엇이 어느 자리에 걸려
 * 있고 지금 홈에 실제로 보이는지만 보인다 — 건 뒤 거둬지거나 이용제한되면 지정은 남은 채 홈에서만 빠진다. */
export function HomeNovelCurationStatus() {
  const homeNovelCurationsQuery = useHomeNovelCurationsQuery();

  return (
    <section aria-labelledby="home-novel-curation-status-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id="home-novel-curation-status-heading" className="text-sm font-medium text-muted-foreground">
          홈 노벨
        </h2>
        <p className="text-xs text-muted-foreground">걸기·옮기기·비우기는 각 노벨 상세에서 해요.</p>
      </div>
      {homeNovelCurationsQuery.isPending && <div className="h-28 animate-pulse rounded-xl bg-muted" />}
      {homeNovelCurationsQuery.isError && (
        <p className="text-sm text-destructive-text">홈 노벨 현황을 불러오지 못했어요.</p>
      )}
      {homeNovelCurationsQuery.isSuccess && (
        <ol className="grid grid-cols-2 overflow-hidden rounded-xl border border-border bg-card">
          {homeNovelCurationsQuery.data.map((slot) => (
            <HomeNovelSlotRow key={slot.position} slot={slot} />
          ))}
        </ol>
      )}
    </section>
  );
}

type HomeNovelSlotRowProps = {
  slot: AdminHomeNovelCurationSlot;
};

/** 폰에서도 두 열이다 — 한 열이면 빈 자리 열 줄이 목록을 화면 아래로 민다. 자리 수(10)가 짝수라 마지막 두 칸이 바닥
 * 줄이고, 그 둘의 아래 선은 바깥 테두리와 겹쳐 지운다. */
const SLOT_ROW_CLASS =
  "flex min-h-14 min-w-0 items-center gap-2 border-b border-border px-3 py-2 odd:border-r sm:gap-3 sm:px-4 [&:nth-last-child(-n+2)]:border-b-0";

function HomeNovelSlotRow({ slot }: HomeNovelSlotRowProps) {
  const position = (
    <span className="w-5 shrink-0 text-right text-sm font-semibold tabular-nums text-muted-foreground">{slot.position}</span>
  );

  if (slot.novel === null) {
    return (
      <li className={SLOT_ROW_CLASS}>
        {position}
        <span className="text-sm text-muted-foreground">비어 있음</span>
      </li>
    );
  }

  return (
    <li className={`${SLOT_ROW_CLASS} relative hover:bg-secondary`}>
      {position}
      <div className="size-9 shrink-0 overflow-hidden rounded-md bg-secondary">
        {!!slot.novel.coverUrl && <img src={slot.novel.coverUrl} alt="" className="size-full object-cover" />}
      </div>
      <div className="flex min-w-0 flex-col">
        <Link
          to="/novels/$novelId"
          params={{ novelId: slot.novel.id }}
          className="truncate text-sm font-semibold text-foreground outline-none after:absolute after:inset-0 focus-visible:after:outline-1 focus-visible:after:-outline-offset-1 focus-visible:after:outline-ring focus-visible:after:ring-3 focus-visible:after:ring-ring/50"
        >
          {slot.novel.title || "(제목 없음)"}
        </Link>
        <span className={slot.isListed ? "truncate text-xs text-muted-foreground" : "truncate text-xs text-destructive-text"}>
          {slot.isListed
            ? "홈에 보이는 중"
            : `홈에 안 보임 · ${NOVEL_VISIBILITY_LABELS[slot.novel.visibility]} · ${NOVEL_MODERATION_STATUS_LABELS[slot.novel.moderationStatus]}`}
        </span>
      </div>
    </li>
  );
}
