import { useEffect, useState } from "react";

import { currentToast, subscribeToast, type Toast } from "./toast";

/** Нижнее сообщение об успешном действии (toast.ts). role="status" — экранный диктор читает его без фокуса. */
export function ToastHost() {
  const [toast, setToast] = useState<Toast | null>(currentToast);
  useEffect(() => subscribeToast(setToast), []);
  return (
    <div className="app-toast-layer" aria-live="polite">
      {toast !== null && (
        <p key={toast.id} className="app-toast" role="status" data-testid="app-toast">{toast.text}</p>
      )}
    </div>
  );
}
