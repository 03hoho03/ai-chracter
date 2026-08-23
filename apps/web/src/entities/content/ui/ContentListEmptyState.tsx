import type { ReactNode } from "react";

type ContentListEmptyStateProps = {
  title?: string;
  message?: string;
  action?: ReactNode;
};

/** techspec-home-discovery.md §2 — 홈 검색/필터와 즐겨찾기 목록이 공용으로 쓰는 결과 0건 안내.
 *
 * `action`은 이 빈 상태에서 빠져나가는 길을 패널 **안**에 두기 위한 슬롯이다(`/my`의 `필터 해제`,
 * US-011의 `새 작품 만들기`). 문구만으로는 "아직 만든 작품이 없어요"(만들라)와 "조건에 맞는 작품이
 * 없어요"(풀라)가 화면에서 서로 다른 일을 하지 않는다 — 갈리는 건 다음 행동이다.
 *
 * `title`은 결과가 0건인 게 아니라 **아직 아무것도 시작하지 않은** 상태를 위한 슬롯이다(US-011).
 * 그때는 한 줄이 사실 통보("없어요")와 초대("만들어 보세요") 둘을 겸해야 해서 문장이 길어지는데,
 * 앞을 제목으로 떼면 상태는 굵게 먼저 읽히고 남은 한 줄이 온전히 다음 행동을 말할 수 있다.
 * 타입 조합(`text-base font-semibold text-foreground` + `text-sm text-muted-foreground`)과 문장부호
 * 규약(제목엔 마침표 없음)은 `ContentUnavailableState`에서 그대로 가져왔다 — 간격은 그쪽이 셋 다
 * `gap-3`인 것과 달리 여기선 쌍을 한 덩어리로 묶는다(아래 참고). 없으면 예전처럼 한 줄만 렌더한다. */
export function ContentListEmptyState({
  title,
  message = "조건에 맞는 작품이 없어요.",
  action,
}: ContentListEmptyStateProps) {
  return (
    // `px-6`은 이 패널이 390px에서 본문 342px를 통째로 쓰기 때문이다 — 없으면 두 줄로 접히는 문장이
    // 점선 테두리에 붙는다. 컨테이너 `px-6`(페이지 여백)과 같은 값이라 안쪽 여백이 바깥과 이어져 읽힌다.
    // 기존 소비처(홈·즐겨찾기)의 줄 수와 패널 높이는 그대로다(320/390/428 실측 3·2·2줄, 190·170·170px).
    // `break-keep`은 한국어 본문이 어절 중간에서 갈리는 걸 막는다 — 없으면 320px에서
    // `…여기에 모여` / `요.`(US-011 문구), `…즐겨` / `찾기에`(즐겨찾기 문구)로 끊긴다(실측).
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center break-keep">
      {/* 제목과 설명은 한 덩어리다 — 패널의 `gap-3`(12px)을 그대로 두면 상태와 다음 행동이 같은 거리로
          떨어져 셋이 나란한 목록으로 읽힌다. 제목이 없을 땐 자식이 하나뿐이라 예전과 픽셀이 같다. */}
      <div className="flex flex-col gap-1.5">
        {title && <p className="text-base font-semibold text-foreground">{title}</p>}
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
      {action}
    </div>
  );
}
