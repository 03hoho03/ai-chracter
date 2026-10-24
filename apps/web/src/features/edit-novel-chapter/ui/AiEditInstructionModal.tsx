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
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId } from "react";
import { useForm, useWatch } from "react-hook-form";

import { createCallable } from "@/shared/lib/callable/createCallable";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import {
  AI_EDIT_KIND_CHIPS,
  createAiEditInstructionSchema,
  type AiEditInstructionFormValues,
} from "../model/aiEditInstructionSchema";
import { withObjectParticle } from "../model/blockSelection";
import { countChapterChars } from "../model/chapterBody";

type AiEditInstructionModalProps = {
  /** "3~5번째 문단" */
  rangeLabel: string;
  /** 고른 문단들 — 무엇을 고치는지 지시를 쓰는 동안 볼 수 있게 함께 보인다. */
  paragraphs: readonly string[];
  /** 문단마다 붙일 이름("3번째 문단"). 떨어진 문단을 골랐을 때 어느 문단인지 보이려고 둔다 — 없으면 이름 없이 잇는다. */
  paragraphLabels?: readonly string[];
  /** 자주 쓰는 요청 칩을 둘지. 칩은 지시 칸에 글을 채우기만 한다(여러 문단 수정에서만 둔다). */
  hasKindChips?: boolean;
  /** 상세의 `limits.aiEditInstructionMaxLength`. */
  maxLength: number;
  /** 지난번에 적었다가 그만둔(또는 실패한) 지시. */
  defaultInstruction: string;
};

/** AI 수정 지시를 받는다. 돌려주는 값은 지시 문자열이고, 그만두면 `null` 이다. 금액 확인과 요청은 호출부가 이어
 * 한다 — 이 모달은 아직 아무것도 쓰지 않는다.
 *
 * 고른 문단이 길 수 있어 본문(`DialogBody`)만 스크롤하고 제목·버튼은 제자리에 둔다. 입력칸은 프리미티브대로
 * 16px 글자다(iOS 가 그보다 작은 입력칸에 포커스하면 화면을 확대한다). 버튼은 `취소` 먼저다. */
export const AiEditInstructionModal = createCallable<AiEditInstructionModalProps, string | null>(
  ({ call, rangeLabel, paragraphs, paragraphLabels, hasKindChips = false, maxLength, defaultInstruction }) => {
    const fieldId = useId();
    const chipsLabelId = useId();
    const form = useForm<AiEditInstructionFormValues>({
      resolver: zodResolver(createAiEditInstructionSchema(maxLength)),
      defaultValues: { instruction: defaultInstruction },
    });
    const { errors } = form.formState;
    const length = countChapterChars(useWatch({ control: form.control, name: "instruction" }));
    const describedBy = [`${fieldId}-count`, errors.instruction ? `${fieldId}-error` : undefined]
      .filter((id) => id !== undefined)
      .join(" ");

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>AI로 고치기</DialogTitle>
            <DialogDescription className="break-keep">
              {withObjectParticle(rangeLabel)} 어떻게 고칠지 적어주세요. 다음 단계에서 클로버 금액을 확인해요.
            </DialogDescription>
          </DialogHeader>

          <form
            noValidate
            className="flex min-h-0 flex-1 flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void form.handleSubmit((values) => call.end(values.instruction))(event);
            }}
          >
            <DialogBody className="flex flex-col gap-4">
              <figure className="flex flex-col gap-1.5">
                <figcaption className="text-xs font-medium text-muted-foreground">고른 문단</figcaption>
                <div className="flex flex-col gap-2 rounded-lg bg-secondary p-3 text-sm leading-relaxed break-keep whitespace-pre-line text-foreground">
                  {paragraphs.map((paragraph, index) => {
                    const label = paragraphLabels?.[index];
                    // 같은 문장이 두 번 나오는 문단도 있어 내용이 아니라 순서로 가른다(목록이 바뀌지 않는다).
                    if (label === undefined) return <p key={index}>{paragraph}</p>;
                    return (
                      <div key={index} className="flex flex-col gap-0.5">
                        <p className="text-xs font-medium text-muted-foreground">{label}</p>
                        <p>{paragraph}</p>
                      </div>
                    );
                  })}
                </div>
              </figure>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={fieldId}>고칠 방향</Label>
                {hasKindChips && (
                  <div role="group" aria-labelledby={chipsLabelId} className="flex flex-col gap-1.5">
                    <span id={chipsLabelId} className="sr-only">
                      자주 쓰는 요청 — 누르면 고칠 방향 칸에 채워요
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {AI_EDIT_KIND_CHIPS.map((chip) => (
                        <Button
                          key={chip.label}
                          type="button"
                          variant="secondary"
                          size="sm"
                          className="rounded-full"
                          onClick={() => {
                            form.setValue("instruction", chip.text, { shouldDirty: true });
                            form.setFocus("instruction");
                          }}
                        >
                          {chip.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
                <Textarea
                  id={fieldId}
                  autoFocus
                  rows={3}
                  placeholder="예: 대사를 줄이고 분위기를 더 차분하게"
                  aria-invalid={!!errors.instruction}
                  aria-describedby={describedBy}
                  {...form.register("instruction")}
                />
                <CharacterCount id={`${fieldId}-count`} count={length} max={maxLength} />
                {errors.instruction && (
                  <p id={`${fieldId}-error`} role="alert" className="text-xs break-keep text-destructive-text">
                    {errors.instruction.message}
                  </p>
                )}
              </div>
            </DialogBody>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end(null)}>
                취소
              </Button>
              <Button type="submit">다음</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
