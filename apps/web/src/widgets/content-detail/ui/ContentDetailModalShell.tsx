import { DialogBody, DialogHeader, DialogTitle } from "@ai-character-chat/ui/components/dialog";
import type { ReactNode } from "react";

type ContentDetailModalShellProps = {
  /** 보이는 작품명. 없으면(불러오는 중·오류·이용 불가) 이름만 읽히는 제목을 둔다. */
  title?: string;
  /** 제목 자리에 막대를 그린다 — 작품명이 오기 전 헤더 높이를 미리 잡아 둔다. */
  isTitlePending?: boolean;
  /** 제목 오른쪽, 닫기 X 왼쪽에 놓이는 컨트롤(⋯ 메뉴). */
  actions?: ReactNode;
  /** 스크롤 본문. 없으면 헤더만 낸다. */
  children?: ReactNode;
  /** 본문 아래 고정 영역(플레이 바). */
  footer?: ReactNode;
};

/** 상세 모달의 [고정 헤더, 스크롤 본문, 고정 플레이 바] 틀. 불러오는 중·오류·이용 불가·정상 모든 상태가
 * 같은 틀을 써서 상태가 바뀔 때 헤더 띠와 본문 시작 위치가 튀지 않고, 본문이 언제나 닫기 X 띠 아래에서
 * 시작한다.
 *
 * 다이얼로그 제목은 어느 상태에서든 정확히 하나여야 한다. Radix는 다이얼로그의 `aria-labelledby`를 제목
 * id에 묶으므로, 제목이 없으면 다이얼로그 이름이 비고 둘이면 id가 겹쳐 앞쪽 제목이 이름이 된다. 그래서
 * 작품명이 없는 상태에서도 화면에 안 보이는 제목을 둔다.
 *
 * 헤더 기하: `-mt-2`로 헤더 띠를 닫기 X(`top-2`, 32px)와 같은 높이로 올리고 `min-h-8`로 그 띠 높이를
 * 어느 상태에서나 지킨다. `shrink-0`이 함께 필요하다 — `min-h-8`을 직접 주면 flex 아이템의 자동 최소
 * 높이(내용 높이)가 그 값으로 바뀌어, 본문이 넘쳐 최대 높이에 걸린 모달에서 헤더가 32px로 눌리고 두 줄
 * 제목의 둘째 줄이 본문 위로 삐져나온다. 제목은 두 줄까지 접히고(모바일에서 문장형 스토리 제목이 한 줄
 * 말줄임이면 뜻이 안 서는데 모달에는 전체 제목을 볼 다른 자리가 없다), 다만 키보드가 올라와 다이얼로그가
 * 보이는 높이로 줄어든 동안(아웃렛이 `data-editing`을 단다)에는 한 줄로 줄여 그 줄만큼 본문에 돌려준다 —
 * 그때는 제목을 읽는 중이 아니라 입력칸을 봐야 하는 중이다. `items-start`라 ⋯·X는 언제나 첫
 * 줄 옆에 있다. 제목의 `mt-0.5`는 28px 줄의 가운데를 32px 버튼의 가운데에 맞춘다. 오른쪽 X 자리 여백은
 * `DialogHeader`가 스크롤 본문이 있는 다이얼로그에서 스스로 준다. */
export function ContentDetailModalShell({
  title,
  isTitlePending = false,
  actions,
  children,
  footer,
}: ContentDetailModalShellProps) {
  return (
    <>
      <DialogHeader className="-mt-2 min-h-8 shrink-0 flex-row items-start gap-2">
        {title === undefined ? (
          <DialogTitle className="sr-only">콘텐츠 상세정보</DialogTitle>
        ) : (
          <DialogTitle className="mt-0.5 line-clamp-2 min-w-0 flex-1 leading-7 break-keep in-data-editing:line-clamp-1">{title}</DialogTitle>
        )}
        {/* 진행 표시라 모션 가드를 걸지 않는다. 모달 표면 위라 채움은 `secondary`다. */}
        {isTitlePending && (
          <div aria-hidden className="mt-1.5 h-5 w-40 max-w-full animate-pulse rounded-md bg-secondary" />
        )}
        {actions}
      </DialogHeader>
      {children !== undefined && (
        // `data-content-detail-scroll`은 실제로 스크롤하는 요소에 있어야 한다 — 댓글 입력칸이 키보드에
        // 가리지 않게 이 요소를 직접 스크롤한다.
        <DialogBody data-content-detail-scroll>{children}</DialogBody>
      )}
      {footer}
    </>
  );
}
