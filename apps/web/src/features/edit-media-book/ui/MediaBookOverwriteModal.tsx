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

import type { OverwriteChoice } from "@/entities/media-book";
import { createCallable } from "@/shared/lib/callable/createCallable";

type MediaBookOverwriteModalProps = { fileNames: string[] };

/**
 * 파일 이름으로 한꺼번에 넣을 때 이미 그림이 있는 칸을 어떻게 할지 묻는다. 덮어쓰면 그 칸의 상황 설명·해금 힌트는
 * 그대로 두고 그림만 바뀐다. 닫으면 업로드 전체를 취소한다.
 */
export const MediaBookOverwriteModal = createCallable<MediaBookOverwriteModalProps, OverwriteChoice | undefined>(
  ({ call, fileNames }) => (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(undefined)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>이미 이미지가 있는 칸이 {fileNames.length}곳 있어요</DialogTitle>
          <DialogDescription className="break-keep">
            덮어쓰면 그 칸의 이미지만 바뀌고 상황 설명·해금 힌트는 그대로 남아요.
          </DialogDescription>
        </DialogHeader>
        {/* 파일 이름 목록에는 포커스할 것이 없어, 본문 자체를 Tab 정지로 둬야 키보드로 목록을 스크롤할 수 있다. */}
        <DialogBody scrollLabel="덮어쓸 파일 목록">
          <ul className="flex flex-col gap-1 text-sm break-all text-foreground">
            {fileNames.map((fileName) => (
              <li key={fileName}>{fileName}</li>
            ))}
          </ul>
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(undefined)}>
            취소
          </Button>
          <Button type="button" variant="outline" onClick={() => call.end("skip")}>
            그 칸은 건너뛰기
          </Button>
          <Button type="button" onClick={() => call.end("overwrite")}>
            덮어쓰기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ),
);
