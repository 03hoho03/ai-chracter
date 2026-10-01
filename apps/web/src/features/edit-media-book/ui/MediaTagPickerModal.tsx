import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { ImageOff, Images } from "lucide-react";
import { createCallable } from "react-call";

export type MediaTagPickerGroup = {
  personName: string;
  cells: { cellId: string; sceneName: string; imageUrl: string | undefined }[];
};

export type PickedMediaTag = { personName: string; sceneName: string };

type MediaTagPickerModalProps = { groups: MediaTagPickerGroup[] };

type MediaTagPickerBodyProps = {
  groups: MediaTagPickerGroup[];
  onPick: (picked: PickedMediaTag) => void;
};

/** "이미지 넣기"에서 글에 넣을 칸을 고른다. 그림이 있는 칸만 보여 준다(빈 칸의 표기는 화면에 아무것도 그리지 않는다). */
export const MediaTagPickerModal = createCallable<MediaTagPickerModalProps, PickedMediaTag | undefined>(
  ({ call, groups }) => (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(undefined)}>
      <DialogContent className="max-h-dialog overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>넣을 이미지 고르기</DialogTitle>
          <DialogDescription className="break-keep">
            커서가 있던 자리에 이 칸의 표기를 넣어요. 화면에서는 그 자리에 그림이 보여요.
          </DialogDescription>
        </DialogHeader>
        <MediaTagPickerBody groups={groups} onPick={(picked) => call.end(picked)} />
      </DialogContent>
    </Dialog>
  ),
);

function MediaTagPickerBody({ groups, onPick }: MediaTagPickerBodyProps) {
  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-6 text-center">
        <Images aria-hidden className="size-8 text-muted-foreground" />
        <p className="text-sm break-keep text-muted-foreground">
          아직 미디어 북에 넣은 이미지가 없어요.
          <br />
          미디어 북 탭에서 먼저 칸을 채워 주세요.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {groups.map((group) => (
        <section key={group.personName} className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-foreground">{group.personName}</h3>
          <div className="grid grid-cols-3 gap-2">
            {group.cells.map((cell) => (
              <button
                key={cell.cellId}
                type="button"
                aria-label={`${group.personName} / ${cell.sceneName}`}
                onClick={() => onPick({ personName: group.personName, sceneName: cell.sceneName })}
                className="flex min-w-0 flex-col gap-1 rounded-lg text-left focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {/* 모달(popover 표면) 안이라 웰은 `secondary` 다 — `muted` 는 이 표면과 같은 값이라 사라진다. */}
                <span className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-lg bg-secondary">
                  {cell.imageUrl ? (
                    <img src={cell.imageUrl} alt="" decoding="async" className="size-full object-contain" />
                  ) : (
                    <ImageOff aria-hidden className="size-5 text-muted-foreground" />
                  )}
                </span>
                <span className="truncate text-xs text-foreground">{cell.sceneName}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
