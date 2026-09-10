import { Button } from "@ai-character-chat/ui/components/button";

import { usePreviewQuery } from "../api/usePreviewQuery";

type PreviewPanelProps = {
  isStale: boolean;
};

/** D-10 — 이 화면의 존재 이유. 문안 자체가 아니라 **샘플 입력으로 실제 렌더러를 태운 조립
 * 결과**를 보고 게시 여부를 판단한다. 13개 항목(채널×템플릿/발행 대상 조합)을 접이식
 * `<details>`로 늘어놓는다 — 항목마다 새 접근성 배선이 필요한 아코디언 프리미티브를 추가하는
 * 대신 네이티브 disclosure를 쓴다(키보드·스크린리더가 기본으로 지원한다). */
export function PreviewPanel({ isStale }: PreviewPanelProps) {
  const previewQuery = usePreviewQuery();

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-foreground">조립 미리보기</h2>
        <p className="break-keep text-xs text-muted-foreground">
          지금 저장된 초안을 샘플 입력으로 조립한 실제 전문이에요(모델 호출 없음). 문안이 아니라
          이 결과물을 보고 게시하세요.
        </p>
        {/* prompt-db-goal-prompt.md §11 — 순서 자유가 캐시 프리픽스 안정성과 부딪히는 유일한
         * 지점. 하드 검증 대신 여기(미리보기 화면)에 근거를 남겨 두기로 한 결정이다. */}
        <p className="break-keep text-xs text-muted-foreground">
          참고: generation 채널의 [키워드북]은 [대화 기록] 다음 순서를 유지해야 캐시 프리픽스가
          안정돼요(현재 컨텍스트 캐싱은 꺼져 있어 즉시 영향은 없어요).
        </p>
      </div>

      {isStale && (
        <p className="break-keep text-xs text-muted-foreground">
          저장하지 않은 변경사항이 있어요 — 아래 미리보기는 마지막으로 저장한 초안 기준이에요.
        </p>
      )}

      {previewQuery.isPending && <div className="h-48 animate-pulse rounded-lg bg-muted" />}

      {previewQuery.isError && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-destructive-text">
            미리보기를 만들지 못했어요. 초안의 필수 섹션이 비어 있지 않은지 확인해 주세요.
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={previewQuery.isFetching}
            onClick={() => void previewQuery.refetch()}
          >
            {previewQuery.isFetching ? "다시 시도하는 중..." : "다시 시도"}
          </Button>
        </div>
      )}

      {previewQuery.data && (
        <div className="flex flex-col gap-2">
          {previewQuery.data.items.map((item, index) => (
            <details
              key={`${item.channel}-${item.label}`}
              className="rounded-lg border border-border p-3"
              open={index === 0}
            >
              <summary className="cursor-pointer text-sm font-medium text-foreground">
                {item.label}
              </summary>
              <pre className="mt-2 max-h-96 overflow-y-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap text-foreground">
                {item.text}
              </pre>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
