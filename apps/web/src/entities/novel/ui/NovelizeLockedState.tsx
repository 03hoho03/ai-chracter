import { LockKeyhole } from "lucide-react";

/** 허용 없는 계정이 소설 주소로 직접 들어왔을 때의 화면. 다른 곳으로 보내지 않는다 — 주소를 친 사람에게 왜 못
 * 보는지를 그 자리에서 말하는 쪽이 낫고, 회수 직후라면 메뉴의 진입점도 세션을 다시 읽으며 함께 사라진다.
 *
 * 이 상태가 그 페이지의 전부라 제목은 `h1` 이다. 모양은 콘텐츠 상세의 "볼 수 없는 콘텐츠" 안내와 같다. */
export function NovelizeLockedState() {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center break-keep">
      <LockKeyhole aria-hidden className="size-8 text-muted-foreground" />
      <h1 className="text-lg font-semibold text-foreground">아직 열리지 않은 기능이에요</h1>
      <p className="text-sm text-muted-foreground">소설로 보기는 지금 일부 계정에서만 쓸 수 있어요.</p>
    </div>
  );
}
