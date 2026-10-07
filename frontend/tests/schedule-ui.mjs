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
const dir = await mkdtemp(path.join(tmpdir(), "radioflix-schedule-ui-"));
const origin = "http://127.0.0.1:13033";
const base = `${origin}/schedule`;
let server, browser;
let output = "";
try {
  await mkdir(path.join(dir, "app/components"), { recursive: true });
  await mkdir(path.join(dir, "app/@modal/(.)schedule"), { recursive: true });
  await mkdir(path.join(dir, "app/@modal/(.)reservations"), { recursive: true });
  await mkdir(path.join(dir, "app/@modal"), { recursive: true });
  await mkdir(path.join(dir, "app/schedule"), { recursive: true });
  await mkdir(path.join(dir, "app/reservations"), { recursive: true });
  await mkdir(path.join(dir, "public/icons"), { recursive: true });
  await symlink(path.join(root, "node_modules"), path.join(dir, "node_modules"));
  await copyFile(path.join(root, "package.json"), path.join(dir, "package.json"));
  await copyFile(path.join(root, "app/schedule/page.tsx"), path.join(dir, "app/schedule/page.tsx"));
  await copyFile(path.join(root, "app/globals.css"), path.join(dir, "app/globals.css"));
  await copyFile(path.join(root, "app/layout.tsx"), path.join(dir, "app/layout.tsx"));
  await copyFile(path.join(root, "app/components/Navigation.tsx"), path.join(dir, "app/components/Navigation.tsx"));
  await copyFile(path.join(root, "app/components/PrimaryRouteContext.tsx"), path.join(dir, "app/components/PrimaryRouteContext.tsx"));
  await copyFile(path.join(root, "app/components/InterceptedRoute.tsx"), path.join(dir, "app/components/InterceptedRoute.tsx"));
  await copyFile(path.join(root, "app/@modal/default.tsx"), path.join(dir, "app/@modal/default.tsx"));
  await copyFile(path.join(root, "app/@modal/page.tsx"), path.join(dir, "app/@modal/page.tsx"));
  await copyFile(path.join(root, "app/@modal/(.)schedule/page.tsx"), path.join(dir, "app/@modal/(.)schedule/page.tsx"));
  await copyFile(path.join(root, "app/@modal/(.)reservations/page.tsx"), path.join(dir, "app/@modal/(.)reservations/page.tsx"));
  await copyFile(path.join(root, "app/pwa-register.tsx"), path.join(dir, "app/pwa-register.tsx"));
  await copyFile(path.join(root, "postcss.config.mjs"), path.join(dir, "postcss.config.mjs"));
  await writeFile(path.join(dir, "app/reservations/page.tsx"), 'export default function Page(){return <main><h1>統合確認用予約一覧</h1></main>}');
  // Match the browser fixture date during SSR too, while preserving elapsed
  // time for Next's timers. This clock applies only to the isolated test app.
  const clockFile = path.join(dir, "test-clock.cjs");
  await writeFile(clockFile, 'const now = Date.now; const offset = Date.parse("2026-10-05T03:00:00Z") - now(); Date.now = () => now() + offset;');
  await Promise.all([
    copyFile(path.join(root, "public/sw.js"), path.join(dir, "public/sw.js")),
    copyFile(path.join(root, "public/radioflix.webmanifest"), path.join(dir, "public/radioflix.webmanifest")),
    copyFile(path.join(root, "public/icons/icon-192.png"), path.join(dir, "public/icons/icon-192.png")),
    copyFile(path.join(root, "public/icons/icon-512.png"), path.join(dir, "public/icons/icon-512.png")),
    copyFile(path.join(root, "public/icons/maskable-512.png"), path.join(dir, "public/icons/maskable-512.png")),
  ]);
  server = spawn(process.execPath, [path.join(root, "node_modules/next/dist/bin/next"), "dev", "--webpack", "-p", "13033", "-H", "127.0.0.1"], {
    cwd: dir, env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1", RADIOFLIX_API_URL: "http://127.0.0.1:1",
      NODE_OPTIONS: `${process.env.NODE_OPTIONS || ""} --require=${clockFile}` }, stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout.on("data", chunk => { output += chunk; });
  server.stderr.on("data", chunk => { output += chunk; });
  for (let i = 0; ; i++) {
    if (server.exitCode !== null || i > 120) throw Error(output);
    try { if ((await fetch(base)).ok) break; } catch { /* wait for dev server */ }
    await delay(500);
  }
  browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  let checks = 0;
  const widths = process.env.RADIOFLIX_UI_WIDTHS ? process.env.RADIOFLIX_UI_WIDTHS.split(",").map(Number) : [360, 390, 412, 1280];
  for (const width of widths) {
    const checksBeforeViewport = checks;
    const context = await browser.newContext({ viewport: { width, height: 850 }, isMobile: width < 500, hasTouch: width < 500 });
    const page = await context.newPage(), errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await context.addInitScript(() => { Date.now = () => Date.parse("2026-10-05T03:00:00Z"); });
    const today = "2026-10-05";
    const labels = ["09/28(月)", "09/29(火)", "09/30(水)", "10/01(木)", "10/02(金)", "10/03(土)", "10/04(日)", "10/05(月) 今日", "10/06(火)", "10/07(水)", "10/08(木)", "10/09(金)", "10/10(土)", "10/11(日)", "10/12(月)"];
    const offset = n => new Date(Date.parse(today+"T12:00:00Z")+n*86400000).toISOString().slice(0,10);
    let failed = false, posts = 0, mode = "", state = "未予約", postFailure = false;
    const seen = [];
    const reply = (route, data, status=200) => route.fulfill({status, contentType:"application/json",body:JSON.stringify(data)});
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (url.pathname === "/api/stations") return reply(route,{stations:[{id:"JORF",name:"ラジオ日本"},{id:"TBS",name:"TBSラジオ"}]});
      if (request.method() === "POST") {
        assert.equal(url.pathname, "/api/broadcasts/slot/reservations");
        posts++; mode=request.postDataJSON().mode;
        assert.equal(request.postDataJSON().schedule_revision,"a".repeat(64));
        if (postFailure) return reply(route,{detail:{message:"rfriends3で予約済みです。既存予約は変更していません。"}},409);
        state = mode === "once" ? "今回のみ予約済み" : "毎週録音中";
        return reply(route,{state:"active",...(mode === "weekly" ? {schedule_state:"scheduled"} : {})});
      }
      assert.equal(url.pathname,"/api/schedule"); seen.push(url.search);
      const date=url.searchParams.get("date"), station=url.searchParams.get("station")||"JORF", past=date<today;
      return reply(route,{today,writes_enabled:false,days:[{radio_date:date,availability:failed?"fetch_failed":"ok",broadcasts:failed?[]:[{
        id:"slot",station,station_name:station==="JORF"?"ラジオ日本":"TBSラジオ",title:"長い番組名 テスト番組 番組表の折り返し表示確認用タイトル",performer:"テスト出演者",
        starts_at:date+"T12:00:00+09:00",ends_at:date+"T13:00:00+09:00",schedule_revision:"a".repeat(64),
        reservation_label:state,recording_state:"unknown",native_state:"unknown",allowed_actions:past||state!=="未予約"?[]:["once","weekly"],timefree_message:past?"タイムフリー録音は準備中":"",
      }]}]});
    });
    await page.goto(base); await page.getByText("テスト出演者",{exact:true}).waitFor();
    await page.waitForFunction(() => Boolean(navigator.serviceWorker?.controller));
    assert.equal(new URL(await page.locator('link[rel="manifest"]').getAttribute("href"), base).pathname, "/radioflix.webmanifest");checks++;
    assert.equal(await page.getByRole("navigation",{name:"メインナビゲーション"}).getByRole("link").count(),3);checks++;
    assert.equal(await page.getByRole("button",{name:/今日/}).count(),1);checks++;
    assert.equal(await page.getByRole("button",{name:"すべての局",exact:true}).getAttribute("aria-pressed"),"true");checks++;
    assert.equal(await page.locator('[aria-label="放送日"] button').count(),15);checks++;
    assert.deepEqual(await page.locator('[aria-label="放送日"] button').allTextContents(), labels);checks++;
    assert(await page.locator('[aria-label="放送日"] button').evaluateAll(buttons => buttons.every(button => {
      const range = document.createRange(); range.selectNodeContents(button);
      const text = range.getBoundingClientRect(), box = button.getBoundingClientRect();
      return box.height >= 48 && text.width <= box.width - 30 && text.height <= 25 && button.scrollWidth <= button.clientWidth;
    })), "date labels must stay on one line with padding and a 48px tap target");checks++;
    assert.equal(await page.locator('[aria-label="放送局"] button').count(),3);checks++;
    await page.getByRole("button",{name:"TBSラジオ",exact:true}).click();await page.waitForURL(url=>url.searchParams.get("station")==="TBS");await page.locator("summary").filter({hasText:"TBSラジオ"}).waitFor();assert(seen.at(-1).includes("station=TBS"));checks++;
    await page.getByRole("button",{name:labels[7 + 1],exact:true}).click();await page.waitForURL(url=>url.searchParams.get("date")===offset(1));await page.getByRole("heading",{name:offset(1)+" の番組"}).waitFor();await page.locator("summary").waitFor();assert(seen.at(-1).includes(offset(1)));checks++;
    const restoredRailScroll=await page.locator('[aria-label="放送日"]').evaluate(el=>el.scrollLeft);
    await page.getByRole("button",{name:labels[7 + 2],exact:true}).click();await page.getByRole("heading",{name:offset(2)+" の番組"}).waitFor();
    await page.goBack();await page.waitForURL(url=>url.searchParams.get("date")===offset(1));await page.getByRole("heading",{name:offset(1)+" の番組"}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("station"),"TBS");assert.equal(new URL(page.url()).searchParams.get("date"),offset(1));
    assert.equal(await page.getByRole("button",{name:"TBSラジオ",exact:true}).getAttribute("aria-pressed"),"true");
    assert.equal(await page.locator('[aria-label="放送日"]').evaluate(el=>el.scrollLeft),restoredRailScroll);checks++;
    await page.goBack();await page.waitForURL(url=>url.searchParams.get("date")===today);await page.getByRole("heading",{name:today+" の番組"}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("station"),"TBS");assert.equal(await page.getByRole("button",{name:"TBSラジオ",exact:true}).getAttribute("aria-pressed"),"true");checks++;
    await page.goForward();await page.waitForURL(url=>url.searchParams.get("date")===offset(1));await page.getByRole("heading",{name:offset(1)+" の番組"}).waitFor();
    await page.getByRole("button",{name:labels[7 + 1],exact:true}).click();
    await page.locator("main").evaluate(el=>{el.style.paddingBottom="900px";window.scrollTo(0,480)});
    const pageScroll=await page.evaluate(()=>window.scrollY);
    await page.getByRole("button",{name:labels[7 + 2],exact:true}).evaluate(button=>button.click());
    await page.waitForURL(url=>url.searchParams.get("date")===offset(2));
    await page.goBack();await page.waitForURL(url=>url.pathname==="/schedule"&&url.searchParams.get("date")===offset(1));
    await page.getByRole("heading",{name:offset(1)+" の番組"}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("station"),"TBS");
    assert(Math.abs(await page.evaluate(()=>window.scrollY)-pageScroll)<=2);checks++;
    assert((await page.locator("summary").innerText()).includes("12:00〜13:00"));checks++;
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));checks++;
    await page.locator("summary").click();const once=page.getByRole("button",{name:"今回だけ録音",exact:true});await once.waitFor();assert.equal(await page.getByRole("button",{name:"毎週録音",exact:true}).count(),1);checks++;
    await once.evaluate(b=>{b.click();b.click();});await page.locator("summary").filter({hasText:"今回のみ予約済み"}).waitFor();assert.equal(posts,1);assert.equal(mode,"once");checks++;
    state="未予約";await page.getByRole("button",{name:"再読み込み"}).click();await page.locator("summary").waitFor();await page.locator("summary").click();await page.getByRole("button",{name:"毎週録音",exact:true}).click();await page.locator("summary").filter({hasText:"毎週録音中"}).waitFor();assert.equal(posts,2);assert.equal(mode,"weekly");checks++;
    state="未予約";postFailure=true;await page.getByRole("button",{name:"再読み込み"}).click();await page.locator("summary").waitFor();await page.locator("summary").click();await page.getByRole("button",{name:"今回だけ録音",exact:true}).click();await page.getByText("rfriends3で予約済みです。既存予約は変更していません。",{exact:true}).waitFor();checks++;
    await page.getByRole("button",{name:labels[7 + -1],exact:true}).click();await page.locator("summary").waitFor();await page.locator("summary").click();await page.getByText("タイムフリー録音は準備中",{exact:true}).waitFor();assert.equal(await page.getByRole("button",{name:"今回だけ録音",exact:true}).count(),0);checks++;
    failed=true;await page.getByRole("button",{name:"再読み込み"}).click();await page.getByRole("alert").filter({hasText:"この日の番組表を取得できませんでした"}).waitFor();assert.equal(await page.locator("summary").count(),0);checks++;
    failed=false;await page.getByRole("button",{name:"ラジオ日本",exact:true}).click();await page.locator("summary").waitFor();checks++;
    const navigationPage=await context.newPage();let documentRequests=0;
    navigationPage.on("request", request => { if (request.isNavigationRequest()) documentRequests++; });
    await navigationPage.goto(base);await navigationPage.getByText("テスト出演者",{exact:true}).waitFor();
    await navigationPage.getByRole("button",{name:"TBSラジオ",exact:true}).click();await navigationPage.waitForURL(url=>url.searchParams.get("station")==="TBS");
    await navigationPage.getByRole("button",{name:labels[7 + 1],exact:true}).click();await navigationPage.waitForURL(url=>url.searchParams.get("date")===offset(1));
    await navigationPage.getByRole("navigation",{name:"メインナビゲーション"}).getByRole("link",{name:"予約一覧"}).click();
    await navigationPage.waitForURL(url=>url.pathname==="/reservations");await navigationPage.getByRole("heading",{name:"統合確認用予約一覧"}).waitFor();
    assert.equal(documentRequests, 1, "Navigation soft route must not request a new document");
    await navigationPage.getByRole("navigation",{name:"メインナビゲーション"}).getByRole("link",{name:"番組表"}).click();
    await navigationPage.waitForURL(url=>url.pathname==="/schedule"&&url.searchParams.get("date")===offset(1)&&url.searchParams.get("station")==="TBS");
    assert.equal(await navigationPage.getByRole("button",{name:"TBSラジオ",exact:true}).getAttribute("aria-pressed"),"true");
    assert.equal(documentRequests, 1, "returning from reservations must stay client-side");
    checks++;
    await navigationPage.goBack();await navigationPage.waitForURL(url=>url.pathname==="/reservations");
    await navigationPage.goBack();await navigationPage.waitForURL(url=>url.pathname==="/schedule"&&url.searchParams.get("date")===offset(1));
    await navigationPage.getByRole("heading",{name:offset(1)+" の番組"}).waitFor();
    assert.equal(new URL(navigationPage.url()).searchParams.get("station"),"TBS");
    await navigationPage.locator("summary").waitFor();assert(await navigationPage.locator("summary").count());checks+=3;
    await navigationPage.close();
    assert.deepEqual(errors,[]);await page.screenshot({path:path.join(tmpdir(),`radioflix-schedule-${width}.png`),fullPage:true});
    console.log(`PASS schedule width=${width} (${checks - checksBeforeViewport} checks)`);await context.close();
  }
  console.log(`PASS ${checks} schedule UI checks`);

} finally {
  await browser?.close();
  if (server && server.exitCode === null) {
    const stopped = new Promise(resolve => server.once("exit", resolve));
    server.kill("SIGTERM");
    await stopped;
  }
  await rm(dir, { recursive: true, force: true });
}
