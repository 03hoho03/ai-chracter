import { Button, buttonVariants } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { FolderUp, Loader2, X } from "lucide-react";
import { useId, useState, type ChangeEvent } from "react";
import { toast } from "sonner";

import type { OverwriteChoice } from "@/entities/media-book";
import {
  applyBulkUploadEntry,
  cellImageRefusalMessage,
  finalizeBulkUploadPlan,
  knownAxisNamesOf,
  planBulkUpload,
  rememberEntryAxes,
  type BulkUploadExclusion,
  type MediaBookCellImage,
} from "@/features/build-story";
import { MediaBookOverwriteModal } from "@/features/edit-media-book";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { MAX_SOURCE_BYTES } from "@/shared/lib/asset/resizeImage";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";
import { FOCUS_WITHIN_RING_CLASSNAME } from "@/shared/ui/focusWithinRing";

import { createInOrderQueue } from "../lib/createInOrderQueue";
import { MEDIA_BOOK_IMAGE_ACCEPT } from "../lib/mediaBookImageFile";
import { runWithConcurrency } from "../lib/runWithConcurrency";
import { useMediaBookEditor } from "../model/useMediaBookEditor";
import { useMediaBookThumbnails } from "../model/useMediaBookThumbnails";

type UploadOutcome = { ok: true; image: MediaBookCellImage } | { ok: false; reason: string };

type UploadResult = { addedCellNames: string[]; excluded: BulkUploadExclusion[] };

// 동시에 올리는 파일 수. 파일마다 리사이즈(메인 스레드 캔버스)와 업로드가 돌아 많이 열면 화면이 굳는다.
const UPLOAD_CONCURRENCY = 3;

// 도움말에 적는 한 장 상한. 사용자가 고른 원본 파일에 걸리는 검사(리사이즈 전 크기 검사)와 같은 상수에서 계산해
// 도움말 숫자와 그 검사가 갈리지 않게 한다. 업로드 상한(리사이즈 결과물에 건다)은 사용자가 고른 파일 크기와 무관하다.
const MAX_FILE_MEGABYTES = MAX_SOURCE_BYTES / (1024 * 1024);

// 다 올린 뒤 버튼에 마지막 진행(`n/n`)을 남겨 두는 시간. 결과와 같은 순간에 원래 문구로 돌아가면 마지막 장이 끝났다는
// 표시가 한 번도 그려지지 않는다. 결과는 기다리지 않고 바로 보인다.
const FINAL_PROGRESS_HOLD_MS = 600;

// 결과 줄에 이름을 다 적는 칸 수. 넘으면 앞의 몇 칸과 남은 칸 수만 적어 결과 줄이 표를 아래로 밀지 않게 한다.
const RESULT_CELL_NAME_LIMIT = 3;

/**
 * 파일 이름(`인물_장면.확장자`)으로 칸을 한꺼번에 채운다. 순서: 이름 읽기 → (채워진 칸이 있으면) 덮어쓰기 묻기 →
 * 상한 적용 → 파일마다 올리고 끝나는 대로 한 장씩 폼에 반영. 업로드 주소는 `uploadAsset` 이 파일마다 올리기 직전에
 * 받으므로 대기열이 길어도 만료되지 않는다. 도중에 탭을 옮겨도 남은 파일은 계속 올라가 폼에 반영된다(폼은 빌더
 * 셸에 있다). 빌더 자체를 떠나면 폼이 사라지므로 남은 파일은 올리지 않고, 올라가던 것도 폼에 쓰지 않고, 넣지 못한
 * 장 수를 한 번 알린다.
 */
export function MediaBookBulkUpload() {
  const { getMediaBook, commit } = useMediaBookEditor();
  const thumbnails = useMediaBookThumbnails();
  const inputId = useId();
  const helpId = useId();
  const [progress, setProgress] = useState<{ done: number; total: number }>();
  // 시작할 때 한 번 읽히는 알림. 파일마다 바뀌는 버튼 글자는 읽히면 시끄러워 live 로 두지 않는다.
  const [startAnnouncement, setStartAnnouncement] = useState("");
  const [result, setResult] = useState<UploadResult>();
  const isUploading = progress !== undefined;

  async function handleFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0 || isUploading) return;
    setResult(undefined);
    const shellSignal = thumbnails.getShellSignal();

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
    const addedCellNames: string[] = [];
    // 파일 순서 대기열이 처리(반영 또는 실패)한 수 — 빌더를 떠난 순간 나머지가 넣지 못한 장이다.
    let settledCount = 0;
    // 업로드 도중 사용자가 지운 인물·장면을 되살리지 않도록, 이번 업로드가 이미 아는 이름을 들고 다닌다.
    const known = knownAxisNamesOf(getMediaBook());
    // 업로드는 동시에 돌지만 폼 반영은 파일 순서대로 — 새 인물·장면이 파일 순서로 만들어진다.
    const applyInFileOrder = createInOrderQueue<UploadOutcome>((index, outcome) => {
      const entry = final.entries[index];
      // 빌더를 떠난 뒤 끝난 업로드는 사라진 폼에 쓰지 않는다.
      if (!entry || shellSignal.aborted) return;
      settledCount += 1;
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
      addedCellNames.push(`${entry.person} · ${entry.scene}`);
    });
    // 떠난 화면 위에 뜨지만, "자동으로 저장돼요" 를 믿은 사람에게 잃은 것을 알리는 유일한 자리다.
    const notifyLeftBuilder = () => {
      const notInserted = final.entries.length - settledCount;
      if (notInserted > 0) toast(`빌더를 떠나서 이미지 ${notInserted}장은 넣지 않았어요. 다시 열어 올려 주세요.`);
    };
    // 덮어쓰기 모달은 화면 맨 위에 떠 있어 빌더를 떠난 뒤에도 답할 수 있다. 그 사이 끊긴 신호에는 리스너를 붙여도
    // 발화하지 않으므로, 여기서 한 번 알리고 아무것도 올리지 않는다(취소로 답했으면 위에서 이미 끝났다).
    if (shellSignal.aborted) {
      notifyLeftBuilder();
      return;
    }
    shellSignal.addEventListener("abort", notifyLeftBuilder, { once: true });
    setProgress({ done: 0, total: final.entries.length });
    setStartAnnouncement(`이미지 ${final.entries.length}장을 올리는 중이에요`);
    const indexedEntries = final.entries.map((entry, index) => ({ entry, index }));
    await runWithConcurrency(
      indexedEntries,
      UPLOAD_CONCURRENCY,
      async ({ entry, index }) => {
        const outcome = await uploadEntryFile(files[entry.fileIndex], (assetId, file) =>
          thumbnails.rememberUploadedFile(assetId, file),
        );
        applyInFileOrder(index, outcome);
        setProgress((current) => current && { ...current, done: current.done + 1 });
      },
      shellSignal,
    );
    shellSignal.removeEventListener("abort", notifyLeftBuilder);
    if (shellSignal.aborted) return;
    setStartAnnouncement("");
    setResult({ addedCellNames, excluded: [...final.excluded, ...failed] });
    window.setTimeout(() => setProgress(undefined), FINAL_PROGRESS_HOLD_MS);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Label
          htmlFor={inputId}
          aria-disabled={isUploading}
          className={cn(
            buttonVariants({ variant: "outline" }),
            "cursor-pointer aria-disabled:pointer-events-none aria-disabled:opacity-65",
            FOCUS_WITHIN_RING_CLASSNAME,
          )}
        >
          {isUploading ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <FolderUp aria-hidden className="size-4" />}
          {isUploading ? `올리는 중 ${progress.done}/${progress.total}` : "파일 이름으로 한꺼번에 넣기"}
          <input
            id={inputId}
            type="file"
            multiple
            accept={MEDIA_BOOK_IMAGE_ACCEPT}
            className="sr-only"
            aria-describedby={helpId}
            aria-disabled={isUploading}
            // 업로드 중에는 파일 창을 열지 않는다. `disabled` 를 주면 키보드로 이 입력에 있던 포커스가 body 로 떨어진다.
            onClick={(event) => {
              if (isUploading) event.preventDefault();
            }}
            onChange={(event) => void handleFiles(event)}
          />
        </Label>
        {/* 결과는 도움말 자리에 대신 놓는다 — 버튼 아래에 따로 두면 그만큼 표가 밀려, 방금 채운 칸이 화면 아래로 간다.
            도움말은 숨겨도 파일 입력의 설명으로는 그대로 읽힌다. */}
        {result !== undefined && <UploadResultNotice result={result} onDismiss={() => setResult(undefined)} />}
        <p id={helpId} hidden={result !== undefined} className="text-xs break-keep text-muted-foreground">
          ‘<span className="text-foreground">유나_리딩.png</span>’처럼 이름의 첫 _ 앞을 인물, 뒤를 장면으로 읽어 그 칸에
          넣어요. 없는 인물·장면은 새로 만들어요. PNG·JPG·WebP, 한 장에 {MAX_FILE_MEGABYTES}MB까지예요.
        </p>
      </div>

      <p role="status" className="sr-only">
        {startAnnouncement}
      </p>
    </div>
  );
}

function UploadResultNotice({ result, onDismiss }: { result: UploadResult; onDismiss: () => void }) {
  return (
    // 넓은 화면에서는 버튼 옆에, 좁은 화면에서는 버튼 아래 한 줄로 놓인다(도움말과 같은 자리).
    <div role="status" className="flex min-w-0 flex-1 basis-60 items-start gap-2">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-sm font-medium text-foreground">
          {result.addedCellNames.length}장을 넣었어요
          {result.excluded.length > 0 && ` · ${result.excluded.length}개 파일은 넣지 않았어요`}
        </p>
        {result.addedCellNames.length > 0 && (
          // 어느 칸에 들어갔는지 — 표에서 찾아보지 않아도 되게 칸 이름을 넣은 순서대로 적는다.
          <p className="text-xs break-keep text-muted-foreground">{summarizeCellNames(result.addedCellNames)}</p>
        )}
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
      <Button type="button" variant="ghost" size="icon-sm" aria-label="결과 닫기" onClick={onDismiss}>
        <X aria-hidden />
      </Button>
    </div>
  );
}

/** 넣은 칸 이름 한 줄. 많으면 앞의 몇 칸과 남은 칸 수만 적는다. */
function summarizeCellNames(names: string[]): string {
  if (names.length <= RESULT_CELL_NAME_LIMIT) return names.join(", ");
  return `${names.slice(0, RESULT_CELL_NAME_LIMIT).join(", ")} 외 ${names.length - RESULT_CELL_NAME_LIMIT}칸`;
}

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
