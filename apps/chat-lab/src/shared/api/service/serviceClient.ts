import axios from "axios";

import { isRecord } from "@/shared/lib/isRecord";

import type { components } from "./generated";
import { HostedError } from "./hostedFailure";

type Schemas = components["schemas"];
/** 서비스 런 목록. 줄마다 그 런의 최신 판·살아 있는 판 수·올릴 때 측정 서버 목록이 낸 한 줄(`run`)이 실린다. */
export type HostedRunList = Schemas["RunList"];
/** 서비스에 올라온 판 하나. */
export type HostedVersion = Schemas["Version"];
export type HostedDeleteResult = Schemas["DeleteResult"];

/**
 * 호스팅 서비스 호출은 아래 엔드포인트 함수를 거쳐 이 인스턴스로만 나간다. 측정 서버 인스턴스(`client.ts`)와 따로 둔다 — 그쪽은
 * 호스팅 화면에서 요청이 나가기 전에 막히고, 이쪽은 주소 없이(같은 출처) 화면을 내준 서비스로 간다.
 */
export const serviceClient = axios.create();

/** 런 id 는 base64url 이라 지금은 인코딩해도 그대로지만, 경로 한 마디에 넣는 값이라 인코딩을 거친다. */
function runPath(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}`;
}

/**
 * 런 목록. 화면이 칸을 읽기 전에 겉모양을 본다 — 측정 서버와 달리 웹과 서비스가 다른 커밋에서 나올 수 있고(서비스 이미지만 옛 것),
 * 그때 틀린 칸을 읽어 화면이 깨지는 대신 응답 꼴 틀림으로 실패한다. 줄의 `run` 칸은 목록을 나눌 때 따로 본다.
 */
export async function getHostedRuns(): Promise<HostedRunList> {
  const response = await serviceClient.get<unknown>("/api/runs");
  const list = response.data;
  if (!isHostedRunList(list)) throw new HostedError("badResponse");
  return list;
}

/** 판 하나의 묶음(측정 서버의 통째 응답 그대로). 생성 타입이 칸을 모르는 객체라, 받는 쪽(묶음 로더)이 겉모양을 보고 좁힌다. */
export async function getHostedBundle(runId: string, sha256: string): Promise<unknown> {
  const response = await serviceClient.get<unknown>(`${runPath(runId)}/versions/${encodeURIComponent(sha256)}/bundle`);
  return response.data;
}

/** 런의 모든 판을 지운다. 서비스는 경로와 같은 runId 를 JSON 본문에 실은 지우기만 받는다(잘못 겨눈 지우기를 막는 확인). */
export async function deleteHostedRun(runId: string): Promise<HostedDeleteResult> {
  const response = await serviceClient.delete<unknown>(runPath(runId), { data: { runId } });
  const result = response.data;
  if (!isRecord(result) || typeof result.runId !== "string" || typeof result.deletedVersions !== "number") {
    throw new HostedError("badResponse");
  }
  return { runId: result.runId, deletedVersions: result.deletedVersions };
}

function isHostedRunList(value: unknown): value is HostedRunList {
  return isRecord(value) && Array.isArray(value.items) && value.items.every(isHostedRunItem);
}

function isHostedRunItem(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.runId === "string" &&
    typeof value.versionCount === "number" &&
    isRecord(value.run) &&
    isHostedVersion(value.latest)
  );
}

/** 화면이 읽는 판 칸만 본다(판 칸·삭제 확인·원문 표지). */
function isHostedVersion(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.sha256 === "string" &&
    typeof value.versionNumber === "number" &&
    typeof value.uploadedAt === "string" &&
    typeof value.uploadedBy === "string" &&
    typeof value.raw === "boolean" &&
    typeof value.contractVersion === "number" &&
    typeof value.compressedSize === "number" &&
    typeof value.uncompressedSize === "number" &&
    isRecord(value.sourceCommit) &&
    typeof value.sourceCommit.commit === "string" &&
    typeof value.sourceCommit.dirty === "boolean" &&
    isRecord(value.provenance) &&
    (typeof value.provenance.authorInExampleDomain === "boolean" || value.provenance.authorInExampleDomain === null)
  );
}
