import { create } from "zustand";
import type { AuthUser } from "../types";

type Session = {
  token: string | null;
  user: AuthUser | null;
};

type AuthState = Session & {
  setSession: (session: Session) => void;
  clearSession: () => void;
};

const storageKey = "eduweave.session";

function readSession(): Session {
  const fallback = { token: null, user: null };
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? (JSON.parse(raw) as Session) : fallback;
  } catch {
    return fallback;
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  ...readSession(),
  setSession: (session) => {
    window.localStorage.setItem(storageKey, JSON.stringify(session));
    set(session);
  },
  clearSession: () => {
    window.localStorage.removeItem(storageKey);
    set({ token: null, user: null });
  },
}));
