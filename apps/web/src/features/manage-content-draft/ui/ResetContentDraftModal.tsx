import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { contentKeys, useResetContentDraftMutation } from "@/entities/content";

type Props = {
  /** 편집 변경분을 버릴 콘텐츠 id. 발행 이력이 있는 콘텐츠만 올 수 있다(호출부가 `kind`로 거른다). */
  contentId: string;
};

/** US-004/US-010 편집 취소 — 발행 후 편집한 변경분을 버리고 초안을 현재 발행본 내용으로 되돌린다.
 * 발행본 자체는 그대로 남으므로 **삭제가 아니다**. 짝이 되는 `DeleteContentDraftModal`과 카피가
 * 서로 구분돼야 한다(US-010 AC): 이쪽은 "발행본은 그대로"를 먼저 말한다.
 *
 * 손대는 캐시가 `contentKeys.draft(contentId)` 하나인 이유: 되돌린 것은 초안 버전뿐이고 목록·상세가
 * 읽는 값은 전부 **발행 버전**에서 나와 바뀌지 않는다(US-001 — `ContentSummary`의 이름·썸네일·
 * `updatedAt`이 현재 발행 버전 기준).
 *
 * 그리고 `invalidateQueries`가 아니라 **`removeQueries`**다. 빌더는 자동저장마다
 * `setQueryData(contentKeys.draft(id), draft)`로 캐시를 덮으므로(`useDraftPersistence`), 편집 취소
 * 시점의 캐시에는 **방금 버린 그 편집분**이 들어 있다. invalidate는 관찰자가 없는 쿼리를 stale로
 * 표시만 하고 지우지 않아서, 빌더로 되돌아오면 그 낡은 값이 즉시(`isPending: false`) 서빙되고
 * `useForm({defaultValues})`가 거기서 굳은 뒤 다음 자동저장이 **버린 편집분을 서버에 도로 써넣는다**
 * — 편집 취소가 조용히 취소된다(브라우저로 재현: 취소 성공 → 서버 `이도윤` → 빌더 재진입 시 폼은
 * `재현-US010-스테일2` → 한 글자 입력하니 서버가 `재현-US010-스테일2`로 되돌아갔다).
 * 지워 두면 다음 진입이 스켈레톤 한 번을 거쳐 반드시 서버 값으로 시작한다. */
export const ResetContentDraftModal = createCallable<Props, void>(({ call, contentId }) => {
  const queryClient = useQueryClient();
  const mutation = useResetContentDraftMutation(contentId);

  function handleConfirm() {
    mutation.mutate(undefined, {
      onSuccess: () => {
        // 토스트만 "편집한 내용" 사슬에서 빠져나와 **끝 상태**를 말한다. **이 액션은 버릴 편집분이
        // 없어도 실행되기 때문이다** — 발행이 초안 버전을 자동 복제하므로 발행작에는 손대지 않아도
        // 초안 행이 늘 딸려 있고, `ContentSummary`에 "미발행 편집분이 있는가"를 알려주는 필드가 없어서
        // 메뉴가 그걸 가릴 방법도 없다. 그 상태에서 "편집한 내용을 버렸어요"는 버린 게 없는데 버렸다고
        // 말한다. 끝 상태를 말하면 두 경우 모두 참이고, 사용자가 무엇을 얻었는지도 함께 말한다.
        //
        // 동사(`남다`)와 수식어(`발행된`)를 **둘 다 본문에서 가져온다.** 처음엔 "발행본 내용으로
        // 되돌렸어요"였는데 두 단어가 다 틀렸다.
        // - `되돌리다`: 한 흐름 안에서 방금 **한 일**(토스트)과 **할 수 없는 일**(본문 "되돌릴 수
        //   없어요")을 동시에 뜻한다 — `편집 취소` 라벨을 기각할 때 쓴 바로 그 검사(같은 단어가 실행과
        //   중단 양쪽을 뜻하면 안 된다)를 `취소`에만 적용하고 `되돌리다`에는 빠뜨렸던 것이다.
        // - `발행본`: 이 앱이 사용자에게 노출하는 명사가 아니다. 전수 확인 결과 사용자에게 보이는
        //   `발행본`은 이 문장 하나뿐이었고(나머지는 전부 주석), 제품이 가르치는 말은 `발행된 작품`
        //   (바로 이 모달 본문)·`발행한 작품`(`/my` 빈 상태)이다. 1초 전에 본문이 쓴 수식어를 버리고
        //   처음 보는 명사로 같은 대상을 다시 부르면 확인이 아니라 새 정보가 된다.
        toast.success("발행된 내용만 남았어요.");
        queryClient.removeQueries({ queryKey: contentKeys.draft(contentId) });
        call.end();
      },
      onError: () => toast.error("편집한 내용을 버리지 못했어요. 잠시 후 다시 시도해주세요."),
    });
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>편집한 내용을 버릴까요?</DialogTitle>
          {/* 첫 절이 **작품은 남는다**로 시작해야 짝 모달("작품이 목록에서 사라지고…")과 정면으로
              대비된다. 제목이 쓴 말("편집한 내용")을 본문에서 되풀이하지 않으려고 "고친 것"으로 받는다.

              `break-keep`은 프리미티브가 주지 않아 호출부 몫이다(저장소의 다른 한국어 본문 5곳도 전부
              호출부에서 준다). 없으면 1280px(본문 폭 352px)에서 마지막 절이 `되` / `돌릴 수 없어요.`로
              어절 중간에서 끊긴다(실측 — 390px에서는 우연히 안 끊겨 넓은 화면에서만 나타난다). 하필
              끊기는 어절이 짝 모달의 `복구할`과 심각도 차이를 지는 그 단어다. */}
          <DialogDescription className="break-keep">
            발행된 작품은 그대로 남고, 발행한 뒤에 고친 것만 사라져요. 되돌릴 수 없어요.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            취소
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={mutation.isPending}
            onClick={handleConfirm}
          >
            {mutation.isPending ? "버리는 중..." : "편집한 내용 버리기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
