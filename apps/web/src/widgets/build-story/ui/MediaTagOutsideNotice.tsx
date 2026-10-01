import { TriangleAlert } from "lucide-react";
import { useFormContext, useWatch, type Path } from "react-hook-form";

import { hasMediaTag } from "@/entities/media-book";
import type { StoryBuilderFormValues } from "@/features/build-story";

/** 태그가 그림이 되는 글의 이름. 사용자에게 그 네 곳을 같은 말로 가리킨다. */
const MEDIA_TAG_FIELDS_LABEL = "시작상황·프롤로그·에필로그·등록 설명";

/**
 * 태그가 그림이 되지 않는 글에 태그가 들어 있으면 알린다. 발행은 막지 않는다 — 이 글들은 AI 에게만 가거나
 * 화면에 글자 그대로 나간다.
 */
export function MediaTagOutsideNotice({ name }: { name: Path<StoryBuilderFormValues> }) {
  const { control } = useFormContext<StoryBuilderFormValues>();
  const value = useWatch({ control, name });
  if (typeof value !== "string" || !hasMediaTag(value)) return null;

  return (
    <p className="flex items-start gap-1.5 text-xs break-keep text-muted-foreground">
      <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
      <span>
        이미지 표기는 {MEDIA_TAG_FIELDS_LABEL}에서만 그림이 돼요. 대화 중 이미지는 미디어 북에서 자동으로 골라 보여 줘요.
      </span>
    </p>
  );
}
