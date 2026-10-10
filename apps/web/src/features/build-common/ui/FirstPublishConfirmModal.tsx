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

import type { ContentVisibility } from "@/entities/content";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { FIRST_PUBLISH_VISIBILITY_RESULT } from "../model/firstPublish";

type FirstPublishConfirmModalProps = {
  /** 제목의 작품 종류("캐릭터"·"스토리"). */
  contentLabel: string;
  visibility: ContentVisibility;
  /** 빌더 공개범위 토글과 같은 글자 — 방금 고른 글자 그대로 보여야 같은 것으로 읽힌다. */
  visibilityLabel: string;
};

/**
 * 한 번도 발행하지 않은 작품을 발행하기 직전에 지금 공개범위와 그 결과를 보이고 묻는다. 발행하면 `true`.
 *
 * 공개범위 기본값이 비공개라 "발행"이 곧 공개라고 오해하거나, 반대로 비공개인 줄 모르고 발행하는 일을 막는다. 발행 취소·
 * 작품 삭제는 없지만 공개범위는 발행 뒤에도 바꿀 수 있어 "되돌릴 수 없다"는 말은 쓰지 않고, 바꿀 수 있는 자리를 알린다.
 * 확인창은 발행 검증을 통과한 뒤에만 뜬다 — 오류가 있으면 먼저 그 칸을 짚는다.
 *
 * 버튼 순서는 `취소` 먼저다(푸터 프리미티브가 강제). 빌더 셸 안에 마운트한다 — 루트에 두면 빌더 코드가 첫 화면 번들로
 * 끌려온다.
 */
export const FirstPublishConfirmModal = createCallable<FirstPublishConfirmModalProps, boolean>(
  ({ call, contentLabel, visibility, visibilityLabel }) => (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-keep">이 {contentLabel}를 발행할까요?</DialogTitle>
        </DialogHeader>

        <DialogBody scrollLabel="발행 안내">
          <DialogDescription asChild>
            <div className="flex flex-col gap-2 break-keep">
              <p>
                지금 공개범위: <span className="font-semibold text-foreground">{visibilityLabel}</span>
              </p>
              <p>{FIRST_PUBLISH_VISIBILITY_RESULT[visibility]}</p>
              <p>공개범위는 발행한 뒤에도 작품 메뉴나 등록 탭에서 바꿀 수 있어요.</p>
            </div>
          </DialogDescription>
        </DialogBody>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            취소
          </Button>
          <Button type="button" onClick={() => call.end(true)}>
            발행
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ),
);
