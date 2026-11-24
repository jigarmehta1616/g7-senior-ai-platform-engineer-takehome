export type ToastTone = "ok" | "error";

export interface Toast {
  title: string;
  detail?: string;
  tone: ToastTone;
}

export interface ToastApi {
  notify: (title: string, detail?: string) => void;
  fail: (error: unknown) => void;
}
