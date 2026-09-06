import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { isApiError } from "@/shared/lib/api/client";
import { LEGAL_KIND_LABELS, type LegalKind } from "../api/keys";
import { usePublishMutation } from "../api/usePublishMutation";

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

// 서버(`AdminLegalPublishRequest.version`)와 같은 포맷 제약 — zero-padded ISO 날짜가
// 아니면 `_reconsent_required`(auth/router.py)의 문자열 비교가 시간순과 어긋난다.
// 422 응답을 받고서야 알리는 대신, 여기서 미리 막아 확정 버튼을 비활성화한다.
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

type Props = {
  kind: LegalKind;
};

/** UserActionConfirmModal과 같은 결 — 입력 실패는 조용히 삼키지 않는다. 다만 이 다이얼로그는
 * 409(버전 중복)만 특별 취급한다: 폼을 닫지 않고 버전 필드 아래 서버 문구를 그대로 보여줘
 * admin이 버전만 고쳐 바로 재시도할 수 있게 한다(그 외 실패는 toast만 띄우고 역시 닫지 않는다 —
 * call.end()는 성공 분기에만 있다). */
export const PublishDialog = createCallable<Props, void>(({ call, kind }) => {
  const [version, setVersion] = useState(todayIsoDate);
  const [requiresReconsent, setRequiresReconsent] = useState(false);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);

  const publishMutation = usePublishMutation(kind);

  const trimmedVersion = version.trim();
  const isVersionFormatValid = ISO_DATE_PATTERN.test(trimmedVersion);
  const canConfirm = isVersionFormatValid;

  const handleConfirm = async () => {
    if (!canConfirm) return;

    try {
      await publishMutation.mutateAsync({ version: trimmedVersion, requiresReconsent });
      toast.success(`${LEGAL_KIND_LABELS[kind]} v${trimmedVersion}을 게시했어요.`);
      call.end();
    } catch (error) {
      if (isApiError(error) && error.status === 409 && typeof error.detail === "string") {
        setConflictMessage(error.detail);
      } else {
        toast.error("게시에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{LEGAL_KIND_LABELS[kind]} 게시</DialogTitle>
          <DialogDescription className="break-keep">
            현재 저장된 초안을 새 버전으로 게시해요. 초안은 게시 후에도 그대로 남아요.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="legal-publish-version">버전</Label>
            <Input
              id="legal-publish-version"
              value={version}
              onChange={(event) => {
                setVersion(event.target.value);
                setConflictMessage(null);
              }}
              placeholder="예: 2026-09-06"
            />
            {conflictMessage ? (
              <p className="text-xs text-destructive-text">{conflictMessage}</p>
            ) : (
              trimmedVersion.length > 0 &&
              !isVersionFormatValid && (
                <p className="text-xs text-muted-foreground">YYYY-MM-DD 형식으로 입력해 주세요.</p>
              )
            )}
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              id="legal-publish-reconsent"
              checked={requiresReconsent}
              onCheckedChange={(checked) => setRequiresReconsent(checked === true)}
            />
            <Label htmlFor="legal-publish-reconsent" className="font-normal">
              중요한 변경 — 전원 재동의 필요
            </Label>
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            취소
          </Button>
          <Button
            type="button"
            disabled={!canConfirm || publishMutation.isPending}
            onClick={() => void handleConfirm()}
          >
            {publishMutation.isPending ? "게시 중..." : "게시"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
