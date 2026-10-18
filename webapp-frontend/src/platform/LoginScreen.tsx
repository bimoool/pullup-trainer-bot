// Экран входа в браузере через бота (device-code). Владелец — WEB-AUTH.
// Секрет запроса живёт только в памяти этого компонента; токен сессии — HttpOnly cookie (JS его не видит).
import { useCallback, useEffect, useRef, useState } from "react";
import "./login.css";
import {
  createLoginRequest, pollLoginRequest, RateLimitedError, type LoginRequestInfo,
} from "./webAuthApi";
import {
  formatCountdown, LOGIN_COPY, nextPollDelayMs, phaseAfterPoll, secondsLeft, spokenCode, type LoginPhase,
} from "./webAuthLogic";

export function LoginScreen({ onSignedIn }: { onSignedIn: () => void }) {
  const [phase, setPhase] = useState<LoginPhase>({ kind: "idle" });
  const [now, setNow] = useState(() => Date.now());
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  const codeRef = useRef<HTMLParagraphElement | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);

  // Обратный отсчёт и истечение на клиенте (сервер всё равно проверяет срок сам).
  useEffect(() => {
    if (phase.kind !== "waiting") {
      return;
    }
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [phase.kind]);

  useEffect(() => {
    if (phase.kind === "waiting" && secondsLeft(phase.expiresAtMs, now) === 0) {
      stop();
      setPhase({ kind: "expired" });
    }
  }, [phase, now, stop]);

  useEffect(() => {
    if (phase.kind === "waiting") {
      codeRef.current?.focus();
    }
    if (phase.kind === "signed_in") {
      onSignedIn();
    }
  }, [phase.kind, onSignedIn]);

  const schedulePoll = useCallback((info: LoginRequestInfo, controller: AbortController, attempt: number, limited: boolean) => {
    timerRef.current = window.setTimeout(async () => {
      try {
        const status = await pollLoginRequest(info.request_id, info.browser_secret, controller.signal);
        if (controller.signal.aborted) {
          return;
        }
        const next = phaseAfterPoll(status);
        if (next) {
          stop();
          setPhase(next);
          return;
        }
        schedulePoll(info, controller, attempt + 1, status === "too_many");
      } catch {
        if (!controller.signal.aborted) {
          schedulePoll(info, controller, attempt + 1, false); // временный сбой сети — продолжаем с паузой
        }
      }
    }, nextPollDelayMs(attempt, info.poll_interval_seconds, limited));
  }, [stop]);

  const begin = useCallback(async () => {
    stop();
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase({ kind: "requesting" });
    try {
      const info = await createLoginRequest(controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      const expiresAtMs = Date.now() + info.expires_in_seconds * 1000;
      setNow(Date.now());
      setPhase({ kind: "waiting", requestId: info.request_id, code: info.code, botLink: info.bot_link, expiresAtMs });
      schedulePoll(info, controller, 0, false);
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      setPhase(error instanceof RateLimitedError ? { kind: "rate_limited" } : { kind: "error", message: LOGIN_COPY.networkError });
    }
  }, [schedulePoll, stop]);

  const cancel = useCallback(() => {
    stop();
    setPhase({ kind: "idle" });
  }, [stop]);

  return (
    <section className="login-screen" aria-labelledby="login-title" data-testid="login-screen">
      <h1 id="login-title" className="login-title">{LOGIN_COPY.title}</h1>
      <p className="login-lead">{LOGIN_COPY.lead}</p>

      {phase.kind === "idle" && (
        <button type="button" className="login-button" data-testid="login-start" onClick={() => void begin()}>
          {LOGIN_COPY.start}
        </button>
      )}

      {phase.kind === "requesting" && <p role="status" className="login-status">{LOGIN_COPY.requesting}</p>}

      {phase.kind === "waiting" && (
        <div className="login-waiting">
          <h2 className="login-subtitle">{LOGIN_COPY.waitingHeading}</h2>
          <p
            ref={codeRef} tabIndex={-1} className="login-code" data-testid="login-code"
            aria-label={`Код подтверждения: ${spokenCode(phase.code)}`}
          >
            {phase.code}
          </p>
          <p className="login-hint">{LOGIN_COPY.waitingHint}</p>
          {phase.botLink ? (
            <a className="login-button" data-testid="login-bot-link" href={phase.botLink} target="_blank" rel="noopener noreferrer">
              {LOGIN_COPY.openBot}
            </a>
          ) : (
            <p className="login-hint" data-testid="login-no-link">
              {LOGIN_COPY.noLinkHint} <code>/start weblogin_{phase.requestId}</code>
            </p>
          )}
          <p role="status" aria-live="polite" className="login-status" data-testid="login-countdown">
            Осталось {formatCountdown(secondsLeft(phase.expiresAtMs, now))}
          </p>
          <p className="login-safety">{LOGIN_COPY.safety}</p>
          <button type="button" className="login-link-button" data-testid="login-cancel" onClick={cancel}>
            {LOGIN_COPY.cancel}
          </button>
        </div>
      )}

      {phase.kind === "signed_in" && <p role="status" className="login-status">{LOGIN_COPY.signedIn}</p>}

      {(phase.kind === "denied" || phase.kind === "expired" || phase.kind === "rate_limited" || phase.kind === "error") && (
        <div>
          <p role="alert" className="login-error" data-testid={`login-${phase.kind}`}>
            {phase.kind === "denied" && LOGIN_COPY.denied}
            {phase.kind === "expired" && LOGIN_COPY.expired}
            {phase.kind === "rate_limited" && LOGIN_COPY.rateLimited}
            {phase.kind === "error" && phase.message}
          </p>
          <button type="button" className="login-button" data-testid="login-retry" onClick={() => void begin()}>
            {LOGIN_COPY.retry}
          </button>
        </div>
      )}
    </section>
  );
}
