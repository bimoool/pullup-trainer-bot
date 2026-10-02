import assert from "node:assert/strict";
import { test } from "node:test";

import { createBackButtonStack, type BackButtonAdapter } from "../src/backButtonStack.ts";

function setup(available = true) {
  const log: string[] = [];
  let listener: (() => void) | null = null;
  const adapter: BackButtonAdapter = {
    available: () => available,
    setVisible: (visible) => log.push(visible ? "show" : "hide"),
    subscribe: (cb) => {
      log.push("subscribe");
      listener = cb;
      return () => {
        log.push("unsubscribe");
        listener = null;
      };
    },
  };
  const tasks: Array<() => void> = [];
  const stack = createBackButtonStack(adapter, (task) => tasks.push(task));
  const flush = () => { while (tasks.length > 0) tasks.shift()?.(); };
  return { stack, log, flush, click: () => listener?.(), hasListener: () => listener !== null };
}

test("пустой стек: кнопка скрыта, подписки нет (корневые вкладки)", () => {
  const { stack, log, flush } = setup();
  flush();
  assert.equal(stack.isVisible(), false);
  assert.deepEqual(log, []);
});

test("первый экран показывает кнопку и подписывается один раз; клик — его обработчик", () => {
  const { stack, log, flush, click } = setup();
  const clicks: string[] = [];
  stack.push(() => () => clicks.push("a"));
  flush();
  assert.deepEqual(log, ["subscribe", "show"]);
  click();
  assert.deepEqual(clicks, ["a"]);
});

test("вложенные экраны: клик получает только верхний, одна подписка (нет двойной навигации)", () => {
  const { stack, log, flush, click } = setup();
  const clicks: string[] = [];
  const popParent = stack.push(() => () => clicks.push("parent"));
  const popChild = stack.push(() => () => clicks.push("child"));
  flush();
  assert.equal(log.filter((entry) => entry === "subscribe").length, 1);
  click();
  assert.deepEqual(clicks, ["child"]);
  popChild();
  flush();
  // родитель ещё на экране — кнопка остаётся видимой (раньше её прятал cleanup дочернего)
  assert.equal(stack.isVisible(), true);
  assert.ok(!log.includes("hide"));
  click();
  assert.deepEqual(clicks, ["child", "parent"]);
  popParent();
  flush();
  assert.equal(stack.isVisible(), false);
  assert.deepEqual(log.slice(-2), ["unsubscribe", "hide"]);
});

test("смена экрана в одном коммите (pop+push) не мигает hide→show", () => {
  const { stack, log, flush } = setup();
  const pop = stack.push(() => () => {});
  flush();
  log.length = 0;
  pop();
  stack.push(() => () => {});
  flush();
  assert.deepEqual(log, []);
  assert.equal(stack.isVisible(), true);
});

test("обработчик читается в момент клика (свежее замыкание без перерегистрации)", () => {
  const { stack, flush, click } = setup();
  let current = () => {};
  const seen: string[] = [];
  stack.push(() => current);
  flush();
  current = () => seen.push("fresh");
  click();
  assert.deepEqual(seen, ["fresh"]);
});

test("вне Telegram (adapter.available() == false) — полный no-op", () => {
  const { stack, log, flush } = setup(false);
  stack.push(() => () => {});
  flush();
  assert.deepEqual(log, []);
  assert.equal(stack.isVisible(), false);
});
