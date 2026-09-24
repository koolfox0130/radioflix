// NODE_PATH=/path/to/playwright/node_modules node tests/reservations-ui.mjs
// Runs the real component in an isolated Next app; all API traffic is mocked.
import assert from "node:assert/strict";
import { mkdtemp, mkdir, copyFile, writeFile, symlink, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dir = await mkdtemp(path.join(tmpdir(), "radioflix-reservations-ui-"));
const base = "http://127.0.0.1:13032";
let server, browser;
let output = "";
try {
  await mkdir(path.join(dir, "app"));
  await symlink(path.join(root, "node_modules"), path.join(dir, "node_modules"));
  await copyFile(path.join(root, "package.json"), path.join(dir, "package.json"));
  await copyFile(path.join(root, "app/components/Reservations.tsx"), path.join(dir, "app/Reservations.tsx"));
  await writeFile(path.join(dir, "app/layout.tsx"), 'export default function Layout({children}: {children: React.ReactNode}) {return <html><body>{children}</body></html>}');
  await writeFile(path.join(dir, "app/page.tsx"), '"use client"; import {ReservationPanel,useReservations} from "./Reservations"; export default function Page(){const manager=useReservations();return <><button onClick={()=>void manager.reload()}>Mock poll</button><ReservationPanel programId="p" manager={manager}/></>}');
  server = spawn(process.execPath, [path.join(root, "node_modules/next/dist/bin/next"), "dev", "--webpack", "-p", "13032", "-H", "127.0.0.1"], {
    cwd: dir, env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1", RADIOFLIX_API_URL: "http://127.0.0.1:1" }, stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.on("data", chunk => { output += chunk; });
  server.stderr.on("data", chunk => { output += chunk; });
  for (let i = 0; ; i++) {
    if (server.exitCode !== null || i > 120) throw Error(output);
    try { if ((await fetch(base)).ok) break; } catch { /* wait for dev server */ }
    await delay(500);
  }
  browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  for (const width of [360, 1280]) {
    for (const scenario of ["weekly", "once", "post-error", "refresh-error", "create-failed", "stale-poll", "cancel-4xx", "cancel-5xx", "cancel-network", "cancel-parse", "cancel-wrong-id", "cancel-double"]) {
      const context = await browser.newContext({ viewport: { width, height: 850 }, isMobile: width < 500, hasTouch: width < 500, serviceWorkers: "block" });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", e => errors.push(e.message));
      const morning = { id: "morning", station: "JORF", title: "ラジオ日本ニュース・天気予報", starts_at: "2030-09-25T05:55:00+09:00", ends_at: "2030-09-25T06:00:00+09:00" };
      const evening = { ...morning, id: "evening", starts_at: "2030-09-25T17:50:00+09:00", ends_at: "2030-09-25T18:00:00+09:00" };
      let items = [], subs = [], posts = 0, deletes = 0, holdPoll = false;
      const held = [];
      let finishRefresh;
      let finishDelete;
      let deleteSeen;
      const deleteGate = new Promise(resolve => { finishDelete = resolve; });
      const deleteRequested = new Promise(resolve => { deleteSeen = resolve; });
      const refreshGate = new Promise(resolve => { finishRefresh = resolve; });
      let postSeen;
      const posted = new Promise(resolve => { postSeen = resolve; });
      const reply = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
      await page.route("**/*", async route => {
        const req = route.request(), url = new URL(req.url());
        if (url.origin !== base) return route.abort();
        if (!url.pathname.startsWith("/api/")) return route.continue();
        if (url.pathname.endsWith("/broadcasts")) return reply(route, { broadcasts: [morning, evening], message: "" });
        if (req.method() === "POST") {
          assert.equal(url.pathname, "/api/reservations");
          posts++;
          const body = req.postDataJSON();
          assert.equal(body.broadcast_id, "evening");
          assert.equal(body.mode, scenario === "once" ? "once" : "weekly");
          if (scenario === "post-error") {
            postSeen(); return reply(route, { detail: { message: "mock登録失敗" } }, 409);
          }
          const weekly = body.mode === "weekly";
          items = [{ id: "r", program_id: "p", title: evening.title, mode: "once", state: scenario === "create-failed" ? "create_failed" : "active", subscription_id: weekly ? "s" : null, broadcast: evening, jobs: [], message: "", created_at: evening.starts_at, updated_at: evening.starts_at }];
          if (weekly) subs = [{ id: "s", program_id: "p", station: "JORF", title: evening.title, state: "active", schedule_state: scenario === "create-failed" ? "create_failed" : "scheduled", current_reservation_id: "r", last_matched_broadcast: evening, message: "", created_at: evening.starts_at, updated_at: evening.starts_at }];
          postSeen(); return reply(route, weekly ? subs[0] : items[0]);
        }
        if (req.method() === "DELETE") {
          assert.equal(url.pathname, "/api/subscriptions/s"); deletes++;
          deleteSeen();
          if (scenario === "cancel-network") return route.abort("failed");
          if (scenario === "cancel-parse") return route.fulfill({ status: 200, contentType: "application/json", body: "not-json" });
          if (scenario === "cancel-4xx") return reply(route, { detail: { message: "mock解除拒否" } }, 409);
          if (scenario === "cancel-5xx") return reply(route, { detail: { message: "mock解除障害" } }, 503);
          if (scenario === "cancel-double") await deleteGate;
          if (scenario === "cancel-wrong-id") return reply(route, { ...subs[0], id: "wrong-id", state: "cancelled", schedule_state: "cancelled" });
          subs = [{ ...subs[0], state: "cancelled", schedule_state: "cancelled" }];
          items = [{ ...items[0], state: "cancelled" }];
          return reply(route, subs[0]);
        }
        assert.equal(req.method(), "GET");
        assert(["/api/subscriptions", "/api/reservations"].includes(url.pathname));
        if (holdPoll && posts === 0) { held.push(route); return; }
        if (posts && !deletes) await refreshGate;
        if (scenario === "refresh-error" && posts && url.pathname === "/api/subscriptions") return reply(route, { detail: { message: "mock再取得失敗" } }, 503);
        return reply(route, url.pathname === "/api/subscriptions" ? subs : items);
      });
      page.on("dialog", dialog => dialog.accept());
      await page.goto(base);
      const button = page.getByRole("button", { name: scenario === "once" ? "今回だけ録音" : "毎週録音", exact: true });
      await page.waitForFunction(() => [...document.querySelectorAll("button")].some(b => b.textContent === "毎週録音" && !b.disabled));
      await page.getByRole("combobox").selectOption("evening");
      if (scenario === "stale-poll") {
        holdPoll = true;
        await page.getByRole("button", { name: "Mock poll" }).click();
        while (held.length < 2) await delay(10);
      }
      // Two synchronous clicks must still produce just one POST.
      await button.evaluate(b => { b.click(); b.click(); });
      await posted;
      await page.getByText("録音側に反映中…", { exact: true }).waitFor();
      assert.equal(await button.isDisabled(), true);
      assert.equal(await page.getByText(/^(毎週録音を登録しました。|予約を登録しました。)$/).count(), 0);
      finishRefresh();
      await page.getByText("録音側に反映中…", { exact: true }).waitFor({ state: "hidden" });
      assert.equal(posts, 1);
      assert.equal(await page.getByRole("combobox").inputValue(), "evening");
      if (["weekly", "stale-poll", "cancel-4xx", "cancel-5xx", "cancel-network", "cancel-parse", "cancel-wrong-id", "cancel-double"].includes(scenario)) {
        await page.getByRole("heading", { name: "有効な毎週録音" }).waitFor();
        assert.equal(await page.getByRole("button", { name: "毎週録音中", exact: true }).count(), 1);
        assert.equal(await page.getByText(/今回のみ/).count(), 0);
        await page.getByText("毎週録音を登録しました。", { exact: true }).waitFor();
        if (held.length) {
          // An old poll finishing after the mutation must not erase the new state.
          await Promise.all(held.map(route => reply(route, [])));
          await delay(100);
          assert.equal(await page.getByRole("heading", { name: "有効な毎週録音" }).count(), 1);
        }
        await page.getByText(/履歴・毎週の放送回/).click();
        await page.getByText("RadioFlix予約ID: r", { exact: true }).waitFor();
        assert((await page.getByText(/対象放送:/).innerText()).includes("17:50"));
        await page.getByRole("button", { name: "毎週録音を解除", exact: true }).click();
        if (scenario === "cancel-double") {
          await deleteRequested;
          await page.getByRole("button", { name: "毎週録音を解除", exact: true }).evaluate(b => b.click());
          assert.equal(deletes, 1);
          finishDelete();
        }
        if (scenario.startsWith("cancel-") && scenario !== "cancel-double") await deleteRequested;
        if (scenario.startsWith("cancel-") && !["cancel-double"].includes(scenario)) {
          const expectedError = { "cancel-4xx": "mock解除拒否", "cancel-5xx": "mock解除障害", "cancel-network": "応答を確認できません。接続を確認してください。予約操作の後は一覧から状態を再確認してください。", "cancel-parse": "サーバーの応答を確認できません。予約一覧を再取得して状態を確認してください。", "cancel-wrong-id": "解除対象を確認できません。予約一覧を再取得して状態を確認してください。" }[scenario];
          await page.getByText(expectedError, { exact: true }).waitFor();
          assert.equal(await page.getByRole("heading", { name: "有効な毎週録音" }).count(), 1);
          assert.equal(await page.getByRole("button", { name: "毎週録音中", exact: true }).count(), 1);
          assert.equal(await page.getByText("毎週録音解除済み", { exact: true }).count(), 0);
          assert.equal(await page.getByRole("button", { name: "毎週録音を解除", exact: true }).count(), 1);
        } else {
          await page.getByText("毎週録音解除済み", { exact: true }).waitFor();
          assert.equal(await page.getByRole("heading", { name: "有効な毎週録音" }).count(), 0);
          assert.equal(await page.getByText("RadioFlix予約ID: r", { exact: true }).count(), 1);
        }
        assert.equal(deletes, 1);
      } else if (scenario === "once") {
        await page.getByRole("heading", { name: "有効な単発予約" }).waitFor();
        assert.equal(await page.getByText(/今回のみ/).count(), 1);
        assert.equal(await page.getByRole("heading", { name: "有効な毎週録音" }).count(), 0);
      } else {
        assert.equal(await page.getByText(/^(毎週録音を登録しました。|予約を登録しました。)$/).count(), 0);
        if (scenario === "post-error") {
          await page.getByText("mock登録失敗", { exact: true }).waitFor();
          assert.equal(await page.getByRole("heading", { name: "有効な毎週録音" }).count(), 0);
        }
        if (scenario === "refresh-error") await page.getByText("操作後の最新状態を取得できません。予約一覧を再取得して確認してください。", { exact: true }).waitFor();
        if (scenario === "create-failed") assert(await page.getByText("次回予約の登録失敗", { exact: true }).count() > 0);
      }
      assert.deepEqual(errors, []);
      console.log(`PASS width=${width} ${scenario}`);
      await context.close();
    }
  }
} finally {
  await browser?.close();
  if (server && server.exitCode === null) {
    const stopped = new Promise(resolve => server.once("exit", resolve));
    server.kill("SIGTERM");
    await stopped;
  }
  await rm(dir, { recursive: true, force: true });
}
