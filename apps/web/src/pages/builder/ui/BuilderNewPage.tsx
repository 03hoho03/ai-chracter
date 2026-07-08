import { useEffect, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { useCreateContentDraftMutation, type ContentType } from "../../../entities/content";

/**
 * techspec-builder-character.md §0 AC — `/builder/$type/new` 진입 시 빈 초안을 생성하고
 * `/builder/$type/$draftId`로 리다이렉트한다. 마운트 시 뮤테이션은 React StrictMode에서
 * `.mutate(vars, { onSuccess })` 콜백이 유실될 수 있어(US-099 gotcha) `mutateAsync`+`await`와
 * 로컬 state로 구현한다 — `createDraftMutation.isPending`을 렌더링 조건으로 쓰지 않는다.
 */
export function BuilderNewPage({ type }: { type: ContentType }) {
  const navigate = useNavigate();
  const createDraftMutation = useCreateContentDraftMutation();
  const hasStartedRef = useRef(false);
  const [hasFailed, setHasFailed] = useState(false);

  useEffect(() => {
    if (hasStartedRef.current) return;
    hasStartedRef.current = true;

    void (async () => {
      try {
        const { contentId } = await createDraftMutation.mutateAsync({ type });
        await navigate({
          to: "/builder/$type/$draftId",
          params: { type, draftId: contentId },
          replace: true,
        });
      } catch {
        setHasFailed(true);
        toast.error("초안을 만들지 못했어요. 잠시 후 다시 시도해주세요.");
      }
    })();
  }, [createDraftMutation, navigate, type]);

  return (
    <main className="mx-auto flex min-h-[60vh] max-w-2xl flex-col items-center justify-center gap-2 px-6 text-center">
      <p className={hasFailed ? "text-sm text-destructive" : "text-sm text-muted-foreground"}>
        {hasFailed
          ? "초안을 만들지 못했어요. 잠시 후 다시 시도해주세요."
          : "초안을 만들고 있어요..."}
      </p>
    </main>
  );
}
