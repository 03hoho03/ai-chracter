import {
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Link } from "@tanstack/react-router";
import { Pencil, RotateCcw, Trash2 } from "lucide-react";

import { ContentCardActionMenu } from "@/entities/content";
import { VisibilityTransitionMenuItems } from "@/features/change-content-visibility";
import { DeleteContentDraftModal, ResetContentDraftModal } from "@/features/manage-content-draft";

import type { MyWorkItem } from "../model/myWorkItems";

type MyWorkCardMenuProps = {
  item: MyWorkItem;
  /** 카드에 보이는 제목. "⋯"의 접근가능 이름에 들어간다 — 카드와 **같은** 문자열이라야 스크린리더가
   * 읽는 버튼 이름이 눈에 보이는 카드 이름과 어긋나지 않는다(WCAG 2.5.3).
   *
   * 다만 이게 "⋯"끼리의 구별을 보장하지는 **않는다**: 이름 없는 초안이 둘 이상이면 셋 다 카드 폴백
   * `제목 없는 초안`을 받아 `제목 없는 초안 더보기`가 그 수만큼 생긴다. US-007의 지연 생성 이후
   * 무명 초안 복수 보유는 엣지가 아니라 정상 상태다 — 판별자는 폴백 문자열 쪽(US-008 소관)에서
   * 붙여야 하고, 여기서 카드와 다른 문자열을 쓰면 2.5.3을 깨면서 문제도 못 고친다. */
  title: string;
  /** 이 카드가 속한 작가 = 언제나 나. 공개범위 전환 성공 시 무효화할 목록 쿼리 키를 만드는 데 쓴다. */
  userId: string;
};

/** US-010 — 목록에서 바로 손대는 카드 관리 메뉴. 항목은 `item.kind`로 완전히 갈린다.
 *
 * - 발행작: 수정하기 · 공개범위 전환(현재 값은 뺀다) · 편집한 내용 버리기
 * - 초안: 이어서 쓰기 · 삭제하기
 *
 * **두 위험 액션은 같은 `destructive`다.** 처음엔 삭제만 빨갛게 칠하고 편집취소는 중립으로 뒀는데,
 * 근거로 든 선례(대화방 목록의 초기화/삭제)가 이 화면에는 성립하지 않는다 — 거기선 두 항목이 같은 메뉴
 * 안에 나란히 있어 대비가 눈에 걸리지만, `/my`는 `filterMyWorks`가 초안과 발행작을 **구조적으로 분리**해서
 * 두 항목이 한 화면에 같이 놓이는 일이 없다. 그래서 비대칭이 사는 값은 0인데, 대신 발행작 메뉴에서
 * **유일하게 되돌릴 수 없는 항목이 나머지 셋과 시각적으로 똑같아지고**, 확인 모달의 실행 버튼은
 * `variant="destructive"`라 메뉴와 모달이 서로 다른 말을 하게 된다. 심각도 차이는 색이 아니라 아이콘과
 * 카피가 진다(`Trash2` 대 `RotateCcw`, "복구할 수 없어요" 대 "되돌릴 수 없어요").
 *
 * `RotateCcw`는 유지한다 — "되돌릴 수 없는 액션에 복구 아이콘"이라는 지적이 있었지만, 이 글리프는
 * 편집 도구에서 "변경분 버리기"의 표준 표기이고(서버가 실제로 하는 일도 발행본으로의 되돌리기다),
 * 항목이 이제 빨간 이상 아이콘이 유일한 신호도 아니다. */
export function MyWorkCardMenu({ item, title, userId }: MyWorkCardMenuProps) {
  return (
    <ContentCardActionMenu title={title}>
      {/* 발행작도 초안도 같은 빌더 주소로 간다 — 발행하면 초안 버전이 자동 복제되므로 발행작에도
          편집 대상 초안이 늘 딸려 있다. 라벨만 갈린다(처음 쓰는 중 vs 발행본을 고치는 중). */}
      <DropdownMenuItem asChild>
        <Link to="/builder/$type/$draftId" params={{ type: item.type, draftId: item.id }}>
          <Pencil aria-hidden />
          {item.kind === "draft" ? "이어서 쓰기" : "수정하기"}
        </Link>
      </DropdownMenuItem>

      <DropdownMenuSeparator />

      {item.kind === "draft" ? (
        <DropdownMenuItem
          variant="destructive"
          onSelect={() => void DeleteContentDraftModal.call({ contentId: item.id })}
        >
          <Trash2 aria-hidden />
          삭제하기
        </DropdownMenuItem>
      ) : (
        <>
          <VisibilityTransitionMenuItems
            contentId={item.id}
            creatorUserId={userId}
            currentVisibility={item.visibility}
            moderationStatus={item.moderationStatus}
          />

          <DropdownMenuSeparator />

          {/* AC의 문자는 `편집 취소`지만 원본 PRD의 Open Question 1이 "'방금 누른 걸 취소'로 읽힐
              여지가 있다 — 구현 시 대안을 검토한다"로 이 라벨을 미리 열어 뒀다. 결정적인 건 확인 모달의
              좌측 버튼이 문자 그대로 `취소`라는 것이다 — `편집 취소`를 누르면 한 클릭 뒤에 `취소`가
              나와서, 같은 단어가 한 흐름에서 실행과 중단 양쪽을 뜻하게 된다. 무엇을 잃는지 라벨이 직접
              말하게 하고, 메뉴 → 모달 제목 → 실행 버튼이 한 어휘로 이어지게 했다. PRD가 제안한
              `발행본으로 되돌리기`는 안 쓴다 — 같은 모달의 "되돌릴 수 없어요"와 정면으로 충돌한다. */}
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => void ResetContentDraftModal.call({ contentId: item.id })}
          >
            <RotateCcw aria-hidden />
            편집한 내용 버리기
          </DropdownMenuItem>
        </>
      )}
    </ContentCardActionMenu>
  );
}
