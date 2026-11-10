// Record a walkthrough of the running Command Center and convert it to docs/assets/demo.gif.
// Prereq: API on :8000 and `next start` on :3000. Usage: node scripts/record_demo.js
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

(async () => {
  const outDir = path.join(__dirname, "..", "docs", "assets");
  const tmp = fs.mkdtempSync(path.join(require("os").tmpdir(), "atlas-demo-"));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 860 }, recordVideo: { dir: tmp, size: { width: 1440, height: 860 } } });
  const page = await ctx.newPage();
  const go = async (p, wait = 2600) => { await page.goto("http://localhost:3000" + p, { waitUntil: "networkidle" }); await page.waitForTimeout(wait); };
  await go("/", 4500);
  await page.mouse.move(700, 420); await page.waitForTimeout(600);
  await go("/rails", 2600);
  await page.mouse.wheel(0, 500); await page.waitForTimeout(1400);
  await go("/stress", 800);
  await page.click("text=Run paired experiment");
  await page.waitForSelector("text=Δ LV VALUE SETTLED", { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(2500);
  await page.mouse.wheel(0, 450); await page.waitForTimeout(1600);
  await go("/optimization", 2800);
  await go("/research", 2400);
  await page.mouse.wheel(0, 700); await page.waitForTimeout(1600);
  await go("/decision", 1000);
  await page.click("text=Which institutions are most exposed?"); await page.waitForTimeout(2200);
  await page.selectOption("select >> nth=1", { index: 1 }).catch(() => {}); await page.waitForTimeout(2200);
  await go("/audit", 1000);
  await page.click("text=Verify chain + replay");
  await page.waitForSelector("text=/VERIFIED/i", { timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(2500);
  await ctx.close(); await browser.close();
  const video = fs.readdirSync(tmp).find((f) => f.endsWith(".webm"));
  const src = path.join(tmp, video);
  const palette = path.join(tmp, "palette.png");
  const filters = "fps=5,scale=900:-1:flags=lanczos";
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", src, "-vf", `${filters},palettegen=max_colors=80:stats_mode=diff`, palette]);
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", src, "-i", palette, "-lavfi", `${filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`, path.join(outDir, "demo.gif")]);
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", src, "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-vf", "scale=1440:-2", path.join(outDir, "demo.mp4")]);
  console.log("wrote", path.join(outDir, "demo.gif"), fs.statSync(path.join(outDir, "demo.gif")).size, "bytes");
})();
