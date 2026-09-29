type GuideFieldExampleProps = {
  body: string;
};

/**
 * 빌더 칸에 입력하는 원문. 파싱하지 않고 글자 그대로 보여 준다 — 가르치려는 것이 "이 칸에 이렇게 친다"라
 * 별표 같은 표기가 지워지면 안 된다. 입력칸처럼 보이면 눌러 볼 것 같아 컨트롤 보더(`input`)가 아니라
 * 구조 보더(`border`)로 감싸고, 서체는 본문과 같은 Pretendard 다(고정폭은 채팅 코드 블록 전용이다).
 */
export function GuideFieldExample({ body }: GuideFieldExampleProps) {
  return (
    <figure className="m-0 flex flex-col gap-1.5">
      <figcaption className="text-xs font-medium text-muted-foreground">빌더에 입력하는 글</figcaption>
      <div className="whitespace-pre-wrap break-keep wrap-break-word rounded-lg border border-border px-3 py-2.5 text-sm leading-relaxed text-foreground">
        {body}
      </div>
    </figure>
  );
}
