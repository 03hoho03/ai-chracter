import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { useId } from "react";
import { useFormContext } from "react-hook-form";

import type { PromptLane } from "../model/lane";
import type { PromptSetFormValues } from "../model/schema";

type LabelFieldKey = keyof PromptSetFormValues["labels"];

const LABEL_FIELDS: { key: LabelFieldKey; id: string; title: string; hint: string }[] = [
  {
    key: "userLabel",
    id: "prompt-label-user",
    title: "사용자 라벨",
    hint: "대화 로그에서 사용자 턴 앞에 붙는 이름. stop_sequence가 이 값에서 파생돼요.",
  },
  {
    key: "storyAssistantLabel",
    id: "prompt-label-story-assistant",
    title: "스토리 진행자 라벨",
    hint: "스토리 챗에서 진행자(AI) 턴 앞에 붙는 이름.",
  },
  {
    key: "storyExampleLabel",
    id: "prompt-label-story-example",
    title: "스토리 전개 예시 라벨",
    hint: "전개 예시 안에서 진행자 역할을 부르는 이름(진행자 라벨과 다를 수 있어요).",
  },
  {
    key: "characterAssistantLabel",
    id: "prompt-label-character-assistant",
    title: "캐릭터 라벨",
    hint: "캐릭터 챗에서 캐릭터(AI) 턴 앞에 붙는 이름.",
  },
];

/** prompt-scope-techspec.md §6-4(TS-E) — 이 레인에서 실제로 읽히지 않는 라벨 표시용 힌트.
 * `admin/prompts.py`의 `_LABEL_FIELDS_BY_LANE`의 여집합이라 엄밀히는 같은 사실의 두 번째
 * 사본이지만, 이쪽은 힌트 문구를 고르는 표시 데이터일 뿐 검증에 쓰이지 않는다 — 어긋나도
 * 잘못된 힌트가 뜰 뿐 저장·게시는 서버 표를 따른다. 입력을 막거나 zod를 레인별로 가르지
 * 않는다(실제 게이트는 서버 R-5). */
const UNUSED_LABELS_BY_LANE: Record<PromptLane, readonly LabelFieldKey[]> = {
  story: ["characterAssistantLabel"],
  character: ["storyAssistantLabel", "storyExampleLabel"],
  publish_filter: ["storyAssistantLabel"],
};

type LabelsCardProps = {
  lane: PromptLane;
};

/** 화자 라벨 4개 — 전부 stop_sequence 파생(§4-5)이나 전개 예시 조립에 쓰이므로 개행·':'을
 * 포함할 수 없다(R-5, zod가 `model/schema.ts`에서 먼저 막는다). */
export function LabelsCard({ lane }: LabelsCardProps) {
  const {
    register,
    formState: { errors },
  } = useFormContext<PromptSetFormValues>();
  const unusedInLane = UNUSED_LABELS_BY_LANE[lane];
  // 레인 3개가 `forceMount`로 동시에 마운트된다(PromptSetsPage) — `field.id`가 정적이면
  // 같은 id가 DOM에 3벌 생겨 `htmlFor`가 항상 첫 레인만 가리킨다. `useId()`로 레인(=컴포넌트
  // 인스턴스)별 접두어를 섞는다(선례: `apps/web/.../ContentCard.tsx`의 `useId()`).
  const uid = useId();

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4">
      <h2 className="text-lg font-semibold text-foreground">화자 라벨</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {LABEL_FIELDS.map((field) => {
          const error = errors.labels?.[field.key];
          const isUnused = unusedInLane.includes(field.key);
          const fieldId = `${uid}-${field.id}`;
          return (
            <div key={field.id} className="flex flex-col gap-1.5">
              <Label htmlFor={fieldId}>{field.title}</Label>
              <Input
                id={fieldId}
                aria-invalid={!!error}
                aria-describedby={`${fieldId}-hint${error ? ` ${fieldId}-error` : ""}`}
                {...register(`labels.${field.key}`)}
              />
              {error ? (
                <p id={`${fieldId}-error`} role="alert" className="text-xs text-destructive-text">
                  {error.message}
                </p>
              ) : (
                <p id={`${fieldId}-hint`} className="break-keep text-xs text-muted-foreground">
                  {isUnused ? "이 레인에서는 쓰이지 않아요. " : ""}
                  {field.hint}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
