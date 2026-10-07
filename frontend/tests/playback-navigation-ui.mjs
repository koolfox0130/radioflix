// Exercises the real Home player and intercepted routes with mocked APIs/audio.
import assert from "node:assert/strict";
import { cp, mkdtemp, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dir = await mkdtemp(path.join(tmpdir(), "radioflix-playback-ui-"));
const origin = "http://127.0.0.1:13035";
const base = `${origin}/`;
let server, browser, output = "";
const assertCount = { count: 0 };
const wav = Buffer.alloc(44 + 8000 * 90);
wav.write("RIFF", 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVE", 8);
wav.write("fmt ", 12); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20);
wav.writeUInt16LE(1, 22); wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(8000, 28);
wav.writeUInt16LE(1, 32); wav.writeUInt16LE(8, 34); wav.write("data", 36);
wav.writeUInt32LE(wav.length - 44, 40); wav.fill(128, 44);

try {
  await cp(path.join(root, "app"), path.join(dir, "app"), { recursive: true });
  await cp(path.join(root, "public"), path.join(dir, "public"), { recursive: true });
  for (const file of ["package.json", "next.config.ts", "postcss.config.mjs", "tsconfig.json"]) {
    await cp(path.join(root, file), path.join(dir, file));
  }
  await symlink(path.join(root, "node_modules"), path.join(dir, "node_modules"));
  server = spawn(process.execPath, [path.join(root, "node_modules/next/dist/bin/next"), "dev", "--webpack", "-p", "13035", "-H", "127.0.0.1"], {
    cwd: dir, env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1", RADIOFLIX_API_URL: "http://127.0.0.1:1" }, stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.on("data", chunk => { output += chunk; });
  server.stderr.on("data", chunk => { output += chunk; });
  for (let i = 0; ; i++) {
    if (server.exitCode !== null || i > 120) throw Error(output);
    try { if ((await fetch(base)).ok) break; } catch { /* wait for Next */ }
    await delay(500);
  }

  browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true });
  const page = await context.newPage(), errors = [];
  let documents = 0;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.isNavigationRequest()) documents++; });
  const today = new Date(Date.now() + 4 * 3600000).toISOString().slice(0, 10);
  const tomorrow = new Date(Date.parse(`${today}T12:00:00Z`) + 86400000).toISOString().slice(0, 10);
  const program = { id: "p1", title: "Playback Probe", network: "Test", category: "その他", raw_name: "Playback Probe", thumbnail_url: "/programs/p1/thumbnail" };
  const episode = { filename: "probe.wav", title: "Playback Probe Episode.wav", size: wav.length, updated_at: Date.now() / 1000, thumbnail_url: "/programs/p1/episodes/probe.wav/thumbnail", audio_url: "/audio/p1/probe.wav" };
  const reply = (route, data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/programs") return reply(route, [program]);
    if (url.pathname === "/programs/p1/episodes") return reply(route, [episode]);
    if (url.pathname === "/programs/p1/thumbnail" || url.pathname.endsWith("/thumbnail")) return route.fulfill({ status: 404, body: "" });
    if (url.pathname === "/audio/p1/probe.wav") return route.fulfill({ status: 200, contentType: "audio/wav", headers: { "Accept-Ranges": "bytes" }, body: wav });
    if (url.pathname === "/api/recommendations") return reply(route, []);
    if (url.pathname === "/api/reservations" || url.pathname === "/api/subscriptions") return reply(route, []);
    if (url.pathname === "/api/stations") return reply(route, { stations: [{ id: "JORF", name: "ラジオ日本" }, { id: "TBS", name: "TBSラジオ" }] });
    if (url.pathname === "/api/schedule") {
      const date = url.searchParams.get("date") || today, station = url.searchParams.get("station") || "JORF";
      return reply(route, { today, writes_enabled: false, days: [{ radio_date: date, availability: "ok", broadcasts: [{
        id: "slot", station, station_name: station === "TBS" ? "TBSラジオ" : "ラジオ日本", title: "放送テスト", performer: "出演者",
        starts_at: `${date}T12:00:00+09:00`, ends_at: `${date}T13:00:00+09:00`, schedule_revision: "a".repeat(64),
        reservation_label: "未予約", recording_state: "unknown", native_state: "unknown", allowed_actions: [], timefree_message: "",
      }] }] });
    }
    if (url.pathname.startsWith("/api/")) return reply(route, []);
    return route.continue();
  });

  await page.goto(base);
  await page.getByRole("heading", { name: "Playback Probe" }).first().waitFor();
  await page.getByRole("button", { name: /Playback Probe/ }).last().click();
  await page.getByRole("heading", { name: "録音一覧" }).waitFor();
  await page.getByRole("button", { name: /Playback Probe Episode/ }).click();
  await page.waitForFunction(() => {
    const audio = document.querySelector("audio");
    return audio && audio.readyState >= 2 && !audio.paused && audio.currentTime > 2;
  }, null, { timeout: 15000 });
  await page.locator('button[title="再生速度を切り替え"]').click();
  await page.getByRole("button", { name: "1.2x" }).waitFor();
  await page.getByRole("button", { name: "30↪" }).click();
  await page.waitForFunction(() => document.querySelector("audio")?.currentTime >= 30);
  const afterForwardSkip = await page.locator("audio").evaluate(audio => audio.currentTime);
  await page.getByRole("button", { name: "↩15" }).click();
  await page.waitForFunction(before => document.querySelector("audio").currentTime < before - 14, afterForwardSkip);
  const mediaSessionState = await page.evaluate(() => ({
    title: navigator.mediaSession?.metadata?.title,
    playbackState: navigator.mediaSession?.playbackState,
  }));
  if (mediaSessionState.title !== undefined) {
    assert(mediaSessionState.title.includes("Playback Probe Episode"));
    assert.equal(mediaSessionState.playbackState, "playing");
    assertCount.count++;
  }
  await page.evaluate(() => { window.__radioAudio = document.querySelector("audio"); });
  assertCount.count++;

  async function checkPlayback(label, expectedPlaying = true) {
    const state = await page.evaluate(() => {
      const audio = document.querySelector("audio");
      return { same: audio === window.__radioAudio, connected: audio?.isConnected, paused: audio?.paused, time: audio?.currentTime, rate: audio?.playbackRate };
    });
    assert.equal(state.same, true, `${label}: the existing audio element must remain mounted`);
    assert.equal(state.connected, true, `${label}: audio must remain connected`);
    assert.equal(state.paused, !expectedPlaying, `${label}: play/pause state must stay unchanged`);
    assert(state.time > 0, `${label}: playback position must not reset`);
    assert.equal(state.rate, 1.2, `${label}: playback rate must stay at 1.2x`);
    assertCount.count++;
    return state.time;
  }
  async function navigate(label, route, targetPath) {
    const before = await checkPlayback(`${label} before`);
    await page.getByRole("navigation", { name: "メインナビゲーション" }).getByRole("link", { name: route }).click();
    await page.waitForURL(url => url.pathname === targetPath);
    const after = await checkPlayback(label);
    assert(after >= before, `${label}: position must not move backward`);
    assert.equal(documents, 1, `${label}: client navigation must not request a new document`);
    assertCount.count++;
  }

  await navigate("録音一覧→番組表", "番組表", "/schedule");
  await page.getByRole("button", { name: "TBSラジオ", exact: true }).click();
  await page.waitForURL(url => url.searchParams.get("station") === "TBS");
  await page.getByRole("button", { name: tomorrow.slice(5).replace("-", "/") + "(" + new Intl.DateTimeFormat("ja-JP", { weekday: "short", timeZone: "UTC" }).format(new Date(tomorrow + "T00:00:00Z")) + ")", exact: true }).click();
  await page.waitForURL(url => url.searchParams.get("date") === tomorrow && url.searchParams.get("station") === "TBS");
  const scheduleUrl = new URL(page.url());
  const railScroll = await page.locator('[aria-label="放送日"]').evaluate(element => element.scrollLeft);
  assert.equal(await page.getByRole("button", { name: "TBSラジオ", exact: true }).getAttribute("aria-pressed"), "true");
  assertCount.count++;

  await navigate("番組表→予約一覧", "予約一覧", "/reservations");
  await navigate("予約一覧→番組表", "番組表", "/schedule");
  await page.waitForURL(url => url.searchParams.get("date") === tomorrow && url.searchParams.get("station") === "TBS");
  await page.getByRole("button", { name: "TBSラジオ", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "TBSラジオ", exact: true }).getAttribute("aria-pressed"), "true");
  assert.equal(await page.locator('[aria-label="放送日"]').evaluate(element => element.scrollLeft), railScroll);
  assert.equal(new URL(page.url()).search, scheduleUrl.search);
  await checkPlayback("局・日付・レール位置復元");
  assertCount.count += 2;

  await navigate("番組表→録音一覧", "録音一覧", "/");
  await page.getByRole("button", { name: "⏸" }).click();
  const pausedTime = await page.locator("audio").evaluate(audio => audio.currentTime);
  await page.getByRole("navigation", { name: "メインナビゲーション" }).getByRole("link", { name: "番組表" }).click();
  await page.waitForURL(url => url.pathname === "/schedule");
  await checkPlayback("一時停止状態の維持", false);
  await page.goBack();
  await page.waitForURL(url => url.pathname === "/");
  await checkPlayback("戻る操作後の一時停止状態", false);
  await page.goForward();
  await page.waitForURL(url => url.pathname === "/schedule");
  await checkPlayback("進む操作後の一時停止状態", false);
  await delay(500);
  const afterPause = await page.locator("audio").evaluate(audio => audio.currentTime);
  assert(Math.abs(afterPause - pausedTime) < 0.2, "paused position must not advance or reset");
  assert.equal(documents, 1);
  assert.deepEqual(errors, []);
  console.log(`PASS playback/navigation ${assertCount.count} checks at 360px`);
  await context.close();
} finally {
  await browser?.close();
  if (server && server.exitCode === null) {
    const stopped = new Promise(resolve => server.once("exit", resolve));
    server.kill("SIGTERM"); await stopped;
  }
  await rm(dir, { recursive: true, force: true });
}
