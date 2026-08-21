import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useRef } from "react";

import {
  contentKeys,
  useCreateContentDraftMutation,
  useUpdateContentDraftMutation,
  type ContentDraftPayload,
  type ContentDraftResponse,
  type ContentType,
} from "@/entities/content";
import { draftKeys } from "@/entities/draft";

import { runOnce } from "../lib/runOnce";

/**
 * 빌더의 저장 경로 하나 — 초안이 아직 서버에 없으면 만들고(US-007 지연 생성), 저장하고, URL을 초안
 * 주소로 바꾼다. 자동저장·임시저장·발행 직전 저장이 전부 이 함수를 지난다.
 *
 * 만들기와 이어쓰기가 한 라우트라 이 URL 교체는 파라미터만 바꾼다 — 리마운트가 없으므로 입력 중이던
 * 폼 상태와 포커스가 그대로 남는다(이유는 `pages/builder`의 `NEW_DRAFT_SEGMENT` 주석).
 */
export function useDraftPersistence({ type, draftId }: { type: ContentType; draftId: string | null }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const createDraftMutation = useCreateContentDraftMutation();
  const updateDraftMutation = useUpdateContentDraftMutation();

  // 이 래퍼가 마운트 동안 하나여야 "초안은 정확히 한 번만 만들어진다"가 성립한다(연속 자동저장이
  // 겹쳐 들어온다) → ref에 담아 첫 렌더의 것을 계속 쓴다. 첫 렌더의 `mutateAsync`를 붙잡는 건
  // 안전하다 — useMutation의 MutationObserver는 마운트 내내 같은 인스턴스다.
  const createDraftOnceRef = useRef<(() => Promise<string>) | null>(null);
  const createDraftOnce = (createDraftOnceRef.current ??= runOnce(
    async () => (await createDraftMutation.mutateAsync({ type })).contentId,
  ));

  // `draftId`를 클로저가 아니라 ref로 읽어 `saveDraft`가 마운트 내내 **같은 함수**로 남게 한다.
  // 의존성에 넣으면 초안이 생기는 순간(null → id) 정체성이 바뀌는데, 그러면 `useAutosave`의
  // `useMemo`가 그 렌더에서 새 디바운서를 만들고 옛 디바운서의 타이머는 취소되지 않은 채 남아
  // 낡은 폼 값으로 한 번 더 저장된다(`useAutosave`가 요구하는 "렌더마다 같은 함수" 계약).
  const draftIdRef = useRef(draftId);
  draftIdRef.current = draftId;

  const saveDraft = useCallback(
    async (payload: ContentDraftPayload): Promise<ContentDraftResponse> => {
      const knownId = draftIdRef.current;
      const id = knownId ?? (await createDraftOnce());
      const draft = await updateDraftMutation.mutateAsync({ id, payload });

      // 저장할 때마다 캐시를 응답으로 덮는다(`invalidateQueries`가 아니다 — 1.5초마다 리페치가 돈다).
      // 두 가지를 동시에 막는다:
      // (1) 초안이 막 생긴 경우 — URL이 바뀌는 순간 `useContentDraftQuery`의 키도 바뀌는데 비어 있으면
      //     그 렌더에서 isPending이 되어 BuilderPage가 스켈레톤으로 빠지고 빌더가 통째로 리마운트된다
      //     (= 입력 중이던 폼 상태가 날아간다). 그래서 navigate **전에** 채운다.
      // (2) 이어쓰기의 경우 — 안 채우면 캐시가 진입 시점 스냅샷에 멈춘다. 빌더를 나갔다 gcTime(5분)
      //     안에 돌아오면 그 낡은 값으로 `useForm({defaultValues})`가 굳고(리페치가 끝나도 reset이
      //     없다) 다음 자동저장이 그걸 서버에 덮어써 **편집분이 사라진다**(실측으로 재현하고 고쳤다).
      queryClient.setQueryData(contentKeys.draft(id), draft);

      if (knownId === null) {
        // 방금 없던 초안이 생겼으니 초안 목록은 낡았다(마이페이지 "작성 중인 초안").
        void queryClient.invalidateQueries({ queryKey: draftKeys.list() });
        await navigate({ to: "/builder/$type/$draftId", params: { type, draftId: id }, replace: true });
      }
      return draft;
    },
    [createDraftOnce, navigate, queryClient, type, updateDraftMutation.mutateAsync],
  );

  // 진행 상태(`isPending`)는 일부러 내보내지 않는다 — 이 훅은 자동저장·임시저장·발행 직전 저장이
  // 전부 지나는 길목이라, 그 플래그를 발행 버튼에 걸면 **자동저장이 돌 때마다 "발행 중..."**이 된다
  // (실측: 타이핑을 멈추고 1.5초 뒤 25ms 동안 primary CTA가 비활성화됐다. 느린 회선에선 초 단위다).
  // 사용자가 시작한 액션의 진행 상태는 그 액션을 시작한 곳에서 로컬 state로 판단한다.
  return { saveDraft };
}
