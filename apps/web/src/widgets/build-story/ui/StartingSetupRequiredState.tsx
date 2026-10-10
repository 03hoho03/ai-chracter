import { Button } from "@ai-character-chat/ui/components/button";

type StartingSetupRequiredStateProps = {
  /** 시작설정 탭으로 넘어가고 그 탭의 '시작설정 추가'로 포커스를 옮긴다(셸이 탭 전환을 쥐고 있다). */
  onGoToStartingSetup: () => void;
};

/**
 * 스탯·상황 노트·엔딩 탭은 시작설정마다 따로 쓰는 목록이라 시작설정이 하나도 없으면 편집할 것이 없다. 그 빈 상태에서 할 수 있는
 * 유일한 일이 시작설정을 만드는 것이라, 문장만 두지 않고 그 탭으로 가는 버튼을 둔다 — 탭 줄은 좁은 화면에서 옆으로 밀려 있어
 * 눈으로 찾기 어렵다.
 *
 * 버튼은 이 화면의 유일한 앞길이라 32px 보조 버튼(`size="sm"`)으로 낮추지 않고, 솔리드 채움은 발행 같은 진짜 행동의 자리라
 * 쓰지 않는다(외곽선 기본 크기). 다른 탭 본문과 같은 `py-6` 루트로 감싸야 탭 목록과의 간격이 탭마다 같다.
 */
export function StartingSetupRequiredState({ onGoToStartingSetup }: StartingSetupRequiredStateProps) {
  return (
    <div className="py-6">
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-20 text-center">
        <p className="text-sm break-keep text-muted-foreground">먼저 시작설정 탭에서 시작설정을 추가해주세요.</p>
        <Button type="button" variant="outline" onClick={onGoToStartingSetup}>
          시작설정으로 가기
        </Button>
      </div>
    </div>
  );
}
