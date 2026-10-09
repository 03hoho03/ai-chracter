import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import {
  contentKeys,
  NOVEL_PERMISSION_FIELD_LABEL,
  NovelPermissionPicker,
  useUpdateNovelPermissionMutation,
  type NovelPermission,
} from "@/entities/content";
import { useCreatorPayoutRate } from "@/entities/creator-payout";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import { hasEnabledFeature, useSessionQuery } from "@/entities/session";
import { createCallable } from "@/shared/lib/callable/createCallable";

type ChangeNovelPermissionModalProps = {
  contentId: string;
  /** 작품 상세 응답의 값. 모달은 이 값을 고른 채로 열린다. */
  currentPermission: NovelPermission;
};

/** 발행한 작품의 소설 만들기 허락을 바꾸는 모달. 진입점이 작품 상세 "⋯" 메뉴 하나이고 성공 뒤 동작(토스트·캐시 무효화·닫기)이
 * 언제나 같아 자체 호출형이다. 세 단계가 문장 한 줄씩을 달고 있어 공개 범위 전환처럼 메뉴 항목 + 확인 모달로 두지 않고,
 * 고르고 저장하는 모달 하나로 둔다. */
export const ChangeNovelPermissionModal = createCallable<ChangeNovelPermissionModalProps, void>(
  ({ call, contentId, currentPermission }) => {
    const queryClient = useQueryClient();
    const mutation = useUpdateNovelPermissionMutation(contentId);
    const [selected, setSelected] = useState(currentPermission);
    const { data: me } = useSessionQuery();
    const payoutRate = useCreatorPayoutRate(hasEnabledFeature(me?.enabledFeatures, "creator_payout"));

    function handleSave() {
      if (mutation.isPending) return;
      // 고른 값이 열 때 값과 같아도 보낸다 — 열 때 값은 낡은 상세 캐시일 수 있어, 건너뛰면 서버와 다른 값을 고른 작가의
      // 선택이 조용히 사라진다. 같은 값을 다시 쓰는 것은 서버에 해가 없다.
      mutation.mutate(selected, {
        onSuccess: () => {
          toast.success("소설 만들기 설정을 바꿨어요.");
          void queryClient.invalidateQueries({ queryKey: contentKeys.detail(contentId) });
          // 초안 캐시는 지운다. 무효화만 하면 지금 그 쿼리를 보는 화면이 없어 데이터가 남고, 빌더에 다시 들어갈 때 그 옛 값으로
          // 폼이 굳는다(빌더는 다시 받은 값으로 폼을 고쳐 채우지 않는다).
          queryClient.removeQueries({ queryKey: contentKeys.draft(contentId) });
          call.end();
        },
        onError: (error) => {
          // 재동의가 필요하면 전역 처리가 재동의 모달을 띄운다 — 토스트를 겹치지 않는다.
          if (isLegalReconsentRequiredError(error)) return;
          toast.error("소설 만들기 설정을 바꾸지 못했어요. 잠시 후 다시 시도해주세요.");
        },
      });
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{NOVEL_PERMISSION_FIELD_LABEL}</DialogTitle>
            <DialogDescription className="break-keep">
              이 작품의 대화로 다른 회원이 소설을 만들 수 있는지 정해요. 바꾸면 바로 적용되고, 작가인 나는 언제든 만들 수
              있어요.
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="flex flex-col gap-2">
            <NovelPermissionPicker
              value={selected}
              onValueChange={setSelected}
              label={NOVEL_PERMISSION_FIELD_LABEL}
              earningRate={payoutRate}
            />
          </DialogBody>

          {/* 저장 중에는 `disabled` 대신 `aria-disabled` 로 막아 누른 버튼에서 포커스가 빠지지 않게 한다. */}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button
              type="button"
              aria-disabled={mutation.isPending}
              className="aria-disabled:opacity-65"
              onClick={handleSave}
            >
              {mutation.isPending ? "저장 중..." : "저장"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
