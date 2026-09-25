import { Fragment, useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { imageGenerationStatusLabel, imageStyleLabel } from "@/entities/admin-image-generation";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { useImageGenerationsPager } from "../api/useImageGenerationsPager";
import type {
  AdminImageGenerationDetailItem,
  AdminImageGenerationDetailListResponse,
} from "../api/useViewImageGenerationsMutation";
import { ViewReasonDialog } from "./ViewReasonDialog";

type ImageGenerationViewPageProps = {
  userId: string;
};

export function ImageGenerationViewPage({ userId }: ImageGenerationViewPageProps) {
  const navigate = useNavigate();
  // 페이지 단위 응답을 그대로 배열에 쌓는다(채팅 열람의 flat item 배열과 다른 점) — 각 항목이
  // 어느 페이지에서 왔는지를 유지해야 presigned 이미지 만료 시 그 페이지만 다시 불러올 수 있다
  // (아래 handleRetryPage 주석 참고).
  const [pages, setPages] = useState<AdminImageGenerationDetailListResponse[]>([]);
  // presigned GET URL은 SigV4라 재요청마다 문자열이 달라진다 — 실패한 이미지를 다시 불러오면
  // <img src>가 매번 새 값이 되어 브라우저가 또 요청하고, S3 객체가 영구히 없으면 onError →
  // 재요청 → onError가 무한 반복된다. asset id당 재시도를 1회로 막는다. 페이지를 다시 받아도
  // 이 Set은 비우지 않는다(비우면 이미 재시도한 이미지가 "아직 안 해봄"으로 되돌아가 루프가
  // 되살아난다) — 리렌더가 필요 없어 ref로 충분하다.
  const retriedAssetIds = useRef<Set<string>>(new Set());
  // 두 번째로도 실패한 이미지는 화면에 "깨졌다"고 보여야 하므로 이건 리렌더가 필요해 state로 둔다.
  const [brokenAssetIds, setBrokenAssetIds] = useState<Set<string>>(new Set());
  const pager = useImageGenerationsPager(userId);
  const goToUserDetail = () => void navigate({ to: "/users/$userId", params: { userId } });

  if (pages.length === 0) {
    return (
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
        <Button asChild variant="outline" size="sm" className="self-start">
          <Link to="/users/$userId" params={{ userId }}>
            유저 상세로
          </Link>
        </Button>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">생성 이미지 열람</h1>
        <ViewReasonDialog userId={userId} onCancel={goToUserDetail} onConfirmed={(data) => setPages([data])} />
      </main>
    );
  }

  const latest = pages.at(-1);
  if (!latest) {
    // pages.length > 0은 위에서 이미 보장됐다(noUncheckedIndexedAccess가 배열 인덱싱을
    // `T | undefined`로 보므로 여기서 술어로 좁힌다).
    return null;
  }
  const items = pages.flatMap((page) => page.items);
  const hasMore = latest.page < latest.totalPages;

  const handleLoadMore = async () => {
    try {
      const next = await pager.fetchPage(latest.page + 1);
      setPages((prev) => [...prev, next]);
    } catch {
      toast.error("더 불러오지 못했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  // presigned GET URL(`s3_presigned_url_expires_seconds` 후 깨진다, `inquiry-detail/ui/
  // InquiryDetailPage.tsx`의 onError 주석과 같은 문제)이지만, 첫 페이지는 감사 로그를 남기는
  // POST 뮤테이션 결과라 그 응답 자체를 다시 fetch할 쿼리가 없다. 대신 같은 이미지를 다시
  // 내려주는 GET 더보기 엔드포인트(`.../image-generations?page=N`)로 그 이미지가 속한 페이지만
  // 다시 불러와 교체한다 — 이 GET은 로그를 쌓지 않으므로 반복 호출해도 감사 기록이
  // 늘지 않는다.
  const handleRetryPage = async (pageNumber: number) => {
    try {
      const refreshed = await pager.fetchPage(pageNumber);
      setPages((prev) => prev.map((page) => (page.page === pageNumber ? refreshed : page)));
    } catch {
      toast.error("이미지를 다시 불러오지 못했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  // asset id당 최초 1회만 handleRetryPage를 부른다(위 retriedAssetIds 주석 참고). 이미 재시도한
  // asset이면 재요청 없이 깨진 상태로 표시만 한다.
  const handleImageError = (pageNumber: number, assetId: string) => {
    if (retriedAssetIds.current.has(assetId)) {
      setBrokenAssetIds((prev) => {
        if (prev.has(assetId)) return prev;
        const next = new Set(prev);
        next.add(assetId);
        return next;
      });
      return;
    }
    retriedAssetIds.current.add(assetId);
    void handleRetryPage(pageNumber);
  };

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/users/$userId" params={{ userId }}>
          유저 상세로
        </Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">생성 이미지 열람</h1>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">생성 이력이 없어요.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {pages.map((page) => (
            <Fragment key={page.page}>
              {page.items.map((item) => (
                <ImageGenerationRequestCard
                  key={item.id}
                  item={item}
                  brokenAssetIds={brokenAssetIds}
                  onImageError={(assetId) => handleImageError(page.page, assetId)}
                />
              ))}
            </Fragment>
          ))}

          {hasMore && (
            <div className="flex justify-center">
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-disabled={pager.isFetching}
                onClick={() => {
                  if (!pager.isFetching) void handleLoadMore();
                }}
                className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
              >
                {pager.isFetching ? "불러오는 중..." : "더 보기"}
              </Button>
            </div>
          )}
        </div>
      )}
    </main>
  );
}

type ImageGenerationRequestCardProps = {
  item: AdminImageGenerationDetailItem;
  brokenAssetIds: Set<string>;
  onImageError: (assetId: string) => void;
};

function ImageGenerationRequestCard({ item, brokenAssetIds, onImageError }: ImageGenerationRequestCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
      <p className="whitespace-pre-wrap break-words text-sm text-foreground">{item.prompt}</p>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <div>
          <dt className="text-muted-foreground">상태</dt>
          <dd className="text-foreground">{imageGenerationStatusLabel(item.status)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">스타일</dt>
          <dd className="text-foreground">{imageStyleLabel(item.style)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">비율</dt>
          <dd className="text-foreground">{item.aspectRatio}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">모델</dt>
          <dd className="text-foreground">{item.model}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">생성일시</dt>
          <dd className="text-foreground">{formatDateTime(item.createdAt)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">차단 사유</dt>
          <dd className="text-foreground">{item.blockedReason ?? "-"}</dd>
        </div>
      </dl>

      {item.images.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {item.images.map((image) => (
            <div key={image.assetId} className="aspect-square overflow-hidden rounded-md bg-secondary">
              {brokenAssetIds.has(image.assetId) ? (
                <div className="flex size-full items-center justify-center p-1 text-center text-xs text-foreground">
                  이미지를 불러오지 못했어요
                </div>
              ) : (
                <img
                  src={image.imageUrl}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="size-full object-cover"
                  onError={() => onImageError(image.assetId)}
                />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
