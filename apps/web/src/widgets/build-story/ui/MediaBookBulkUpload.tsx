import { Button, buttonVariants } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { FolderUp, Loader2, X } from "lucide-react";
import { useId, useState, type ChangeEvent } from "react";

import {
  applyBulkUploadEntry,
  cellImageRefusalMessage,
  finalizeBulkUploadPlan,
  knownAxisNamesOf,
  planBulkUpload,
  rememberEntryAxes,
  type BulkUploadExclusion,
  type MediaBookCellImage,
  type OverwriteChoice,
} from "@/features/build-story";
import { MediaBookOverwriteModal } from "@/features/edit-media-book";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";

import { useMediaBookThumbnails } from "./MediaBookThumbnailsProvider";
import { createInOrderQueue } from "../lib/createInOrderQueue";
import { runWithConcurrency } from "../lib/runWithConcurrency";
import { useMediaBookEditor } from "../model/useMediaBookEditor";

type UploadOutcome = { ok: true; image: MediaBookCellImage } | { ok: false; reason: string };

/** 파일 하나를 올린다. 실패도 결과로 돌려준다(파일 순서 반영 대기열이 실패한 번호에서 멈추지 않게). */
async function uploadEntryFile(
  file: File | undefined,
  rememberUploadedFile: (assetId: string, file: File) => string,
): Promise<UploadOutcome> {
  if (!file) return { ok: false, reason: "파일을 읽지 못했어요" };
  try {
    const assetId = await uploadAsset(file, "situational-image");
    return { ok: true, image: { assetId, imageUrl: rememberUploadedFile(assetId, file) } };
  } catch (error) {
    return { ok: false, reason: uploadAssetErrorMessage(error) };
  }
}

// 동시에 올리는 파일 수. 파일마다 리사이즈(메인 스레드 캔버스)와 업로드가 돌아 많이 열면 화면이 굳는다.
const UPLOAD_CONCURRENCY = 3;

type UploadResult = { addedCount: number; excluded: BulkUploadExclusion[] };

/**
 * 파일 이름(`인물_장면.확장자`)으로 칸을 한꺼번에 채운다. 순서: 이름 읽기 → (채워진 칸이 있으면) 덮어쓰기 묻기 →
 * 상한 적용 → 파일마다 올리고 끝나는 대로 한 장씩 폼에 반영. 업로드 주소는 `uploadAsset` 이 파일마다 올리기 직전에
 * 받으므로 대기열이 길어도 만료되지 않는다. 도중에 탭을 옮겨도 남은 파일은 계속 올라가 폼에 반영된다.
 */
export function MediaBookBulkUpload() {
  const { getMediaBook, commit } = useMediaBookEditor();
  const thumbnails = useMediaBookThumbnails();
  const inputId = useId();
  const [progress, setProgress] = useState<{ done: number; total: number }>();
  const [result, setResult] = useState<UploadResult>();
  const isUploading = progress !== undefined;

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0 || isUploading) return;
    setResult(undefined);

    const plan = planBulkUpload(
      files.map((file) => file.name),
      getMediaBook(),
    );
    const overwrites = plan.entries.filter((entry) => entry.isOverwrite);
    let choice: OverwriteChoice = "overwrite";
    if (overwrites.length > 0) {
      const picked = await MediaBookOverwriteModal.call({ fileNames: overwrites.map((entry) => entry.fileName) });
      if (!picked) return;
      choice = picked;
    }
    const final = finalizeBulkUploadPlan(plan, getMediaBook(), choice);

    const failed: BulkUploadExclusion[] = [];
    let addedCount = 0;
    // 업로드 도중 사용자가 지운 인물·장면을 되살리지 않도록, 이번 업로드가 이미 아는 이름을 들고 다닌다.
    const known = knownAxisNamesOf(getMediaBook());
    // 업로드는 동시에 돌지만 폼 반영은 파일 순서대로 — 새 인물·장면이 파일 순서로 만들어진다.
    const applyInFileOrder = createInOrderQueue<UploadOutcome>((index, outcome) => {
      const entry = final.entries[index];
      if (!entry) return;
      if (!outcome.ok) {
        failed.push({ fileName: entry.fileName, reason: outcome.reason });
        return;
      }
      const result = applyBulkUploadEntry(getMediaBook(), entry, outcome.image, () => crypto.randomUUID(), known);
      if (!result.ok) {
        failed.push({ fileName: entry.fileName, reason: cellImageRefusalMessage(result.reason) });
        return;
      }
      rememberEntryAxes(known, result.mediaBook, entry);
      commit(result.mediaBook);
      addedCount += 1;
    });
    setProgress({ done: 0, total: final.entries.length });
    const indexedEntries = final.entries.map((entry, index) => ({ entry, index }));
    await runWithConcurrency(indexedEntries, UPLOAD_CONCURRENCY, async ({ entry, index }) => {
      const outcome = await uploadEntryFile(files[entry.fileIndex], (assetId, file) =>
        thumbnails.rememberUploadedFile(assetId, file),
      );
      applyInFileOrder(index, outcome);
      setProgress((current) => current && { ...current, done: current.done + 1 });
    });
    setProgress(undefined);
    setResult({ addedCount, excluded: [...final.excluded, ...failed] });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Label
          htmlFor={inputId}
          aria-disabled={isUploading}
          className={cn(
            buttonVariants({ variant: "outline" }),
            "cursor-pointer aria-disabled:pointer-events-none aria-disabled:opacity-65 has-[input:focus-visible]:border-ring has-[input:focus-visible]:ring-3 has-[input:focus-visible]:ring-ring/50",
          )}
        >
          {isUploading ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <FolderUp aria-hidden className="size-4" />}
          {isUploading ? `올리는 중 ${progress.done}/${progress.total}` : "파일 이름으로 한꺼번에 넣기"}
          <input
            id={inputId}
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            className="sr-only"
            aria-disabled={isUploading}
            // 업로드 중에는 파일 창을 열지 않는다. `disabled` 를 주면 키보드로 이 입력에 있던 포커스가 body 로 떨어진다.
            onClick={(event) => {
              if (isUploading) event.preventDefault();
            }}
            onChange={(event) => void handleFiles(event)}
          />
        </Label>
        <p className="text-xs break-keep text-muted-foreground">
          파일 이름을 <span className="text-foreground">인물_장면</span>으로 지어 주세요. 예) 에리_기쁨.png → 인물 에리,
          장면 기쁨. 없는 인물·장면은 새로 만들어요.
        </p>
      </div>

      {result && <UploadResultNotice result={result} onDismiss={() => setResult(undefined)} />}
    </div>
  );
}

function UploadResultNotice({ result, onDismiss }: { result: UploadResult; onDismiss: () => void }) {
  return (
    <div role="status" className="flex flex-col gap-2 rounded-xl border border-border p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-foreground">
          {result.addedCount}장을 넣었어요
          {result.excluded.length > 0 && ` · ${result.excluded.length}개 파일은 넣지 않았어요`}
        </p>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="결과 닫기" onClick={onDismiss}>
          <X aria-hidden />
        </Button>
      </div>
      {result.excluded.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
          {result.excluded.map((item, index) => (
            // 같은 이름의 파일을 두 번 고를 수 있어 이름만으로는 key 가 겹친다.
            <li key={`${index}-${item.fileName}`} className="break-all">
              <span className="text-foreground">{item.fileName}</span> — {item.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
