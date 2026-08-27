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

import { contentKeys, useDeleteContentDraftMutation } from "@/entities/content";
import { draftKeys } from "@/entities/draft";

type Props = {
  /** 지울 초안의 콘텐츠 id. 한 번도 발행된 적 없는 콘텐츠만 올 수 있다(호출부가 `kind`로 거른다). */
  contentId: string;
};

/** US-003/US-010 — 미발행 초안 삭제 확인. 발행작 완전 삭제는 US-115/FR-67 정책상 존재하지 않으므로
 * 이 모달은 **초안 전용**이고, 발행작의 편집 변경분을 버리는 `ResetContentDraftModal`과 짝을 이룬다.
 * 두 카피는 나란히 놓고 읽었을 때 "작품이 사라진다" vs "발행본은 그대로 두고 변경분만 버린다"로
 * 갈려야 한다(US-010 AC).
 *
 * 호출부와 무관하게 성공 후 동작(토스트 + `draftKeys.list()` 무효화 + 닫기)이 항상 같아
 * `ChangeContentVisibilityModal`과 같은 "자체 mutation 직접 호출" 계열이다
 * (`ConfirmChatRoomActionModal`처럼 호출부가 mutationFn을 주입하는 계열이 아님). */
export const DeleteContentDraftModal = createCallable<Props, void>(({ call, contentId }) => {
  const queryClient = useQueryClient();
  const mutation = useDeleteContentDraftMutation(contentId);

  function handleConfirm() {
    mutation.mutate(undefined, {
      onSuccess: () => {
        toast.success("초안을 삭제했어요.");
        void queryClient.invalidateQueries({ queryKey: draftKeys.list() });
        // 방금 지운 콘텐츠의 초안 캐시는 서버에 더 이상 대응하는 행이 없다. 빌더가 자동저장마다
        // `setQueryData`로 이 키를 채워 두므로(`useDraftPersistence`) 남겨 두면 지운 작품의 폼이
        // 그대로 다시 그려진다 — `ResetContentDraftModal`이 같은 이유로 `removeQueries`를 쓴다.
        queryClient.removeQueries({ queryKey: contentKeys.draft(contentId) });
        call.end();
      },
      onError: () => toast.error("삭제에 실패했어요. 잠시 후 다시 시도해주세요."),
    });
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>이 초안을 삭제할까요?</DialogTitle>
          {/* 제목이 이미 말한 동작을 되풀이하지 않고 **결과만** 적는다(집안 문법 —
              `ConfirmChatRoomActionModal` 호출부들과 `VISIBILITY_TRANSITION_COPY`가 같은 규칙).
              주어는 반드시 **`작품`**이다: 처음엔 "…쓴 내용이 사라져요"로 썼는데 "내용은 비고 작품
              껍데기는 남는다"로 읽힐 수 있었다.

              `목록에서`가 아니라 `통째로`인 이유: 이 앱에서 발행작은 절대 삭제되지 않고 공개범위만
              바뀐다(FR-67). 그래서 "목록에서 사라진다"는 사용자가 이미 가진 모델("여기선 지워지는 게
              아니라 숨겨진다")을 정확히 먹여서 최종성을 깎는다. 짝 모달의 첫 절이 "발행된 작품은 그대로
              남고"라 존재 대 존재로 축이 맞는다.

              끝 문장이 `복구할 수 없어요`인 것도 짝 모달(`되돌릴 수 없어요`)과의 대비다. 이건 이 저장소가
              이미 쓰는 두 단계 어휘다 — `ChatRoomListItemRow`가 같은 파일에서 **초기화는 "되돌릴 수
              없어요", 삭제는 "복구할 수 없어요"**로 갈라 놨다(`GeneratedImageDetailModal`의 이미지 삭제도
              "복구할 수 없어요"). 둘 다 "되돌릴 수 없어요"로 끝내면 한국어에서 무게를 지는 마지막 절이
              글자까지 같아져, 앞에서 벌려 놓은 심각도 차이가 끝에서 도로 뭉개진다.

              `break-keep`이 없으면 1280px(본문 폭 352px)에서 그 마지막 절이 `복구` / `할 수 없어요.`로
              어절 중간에서 끊긴다(실측 — 390px에서는 우연히 안 끊겨 넓은 화면에서만 나타난다). */}
          <DialogDescription className="break-keep">
            작품이 통째로 없어지고, 지금까지 쓴 내용도 함께 지워져요. 복구할 수 없어요.
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
            {/* `삭제` 두 글자면 옆의 `취소`와 46.2×32로 **픽셀 단위 쌍둥이**가 된다(실측) — 위험한
                쪽과 안전한 쪽이 형태로 구분되지 않는다. 대상을 이름해 폭과 뜻을 함께 가른다
                (`취소` 46 / `초안 삭제` 74, Δ28).

                **다만 이 처방은 `sm` 이상에서만 산다.** `DialogFooter`가 좁은 화면에서 세로로 접어
                두 버튼을 전폭으로 만들기 때문에 390px에서 326×32, 320px에서 256×32로 **다시 Δ0**이
                된다(실측). 그 폭에서 둘을 가르는 건 채움 틴트와 글자, 그리고 순서뿐이다 — US-006
                이후 그 순서는 `취소` **위**, 위험한 쪽 **아래**이고 **탭 순서와 일치한다**(전에는
                `flex-col-reverse`가 시각 순서만 뒤집어 포커스가 아래에서 위로 올라갔다). */}
            {mutation.isPending ? "삭제 중..." : "초안 삭제"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
