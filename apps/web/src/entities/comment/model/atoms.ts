import { atom } from "jotai";

// Explicit logout differs from a recoverable 401: only logout discards comment drafts.
export const commentDraftLogoutRevisionAtom = atom(0);
