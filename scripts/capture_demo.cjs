const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { chromium } = require("playwright");

async function main() {
  const root = path.resolve(__dirname, "..");
  const screenshotDir = path.join(root, "docs", "screenshots");
  const videoDir = path.join(root, "docs", "demo");
  const framesDir = path.join(videoDir, "frames");
  fs.mkdirSync(screenshotDir, { recursive: true });
  fs.mkdirSync(videoDir, { recursive: true });
  fs.mkdirSync(framesDir, { recursive: true });

  const browserCandidates = [
    process.env.PLAYWRIGHT_BROWSER_PATH,
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  ].filter(Boolean);
  const installedBrowser = browserCandidates.find((candidate) => fs.existsSync(candidate));
  const browser = await chromium.launch({
    headless: true,
    ...(installedBrowser ? { executablePath: installedBrowser } : {}),
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  await context.route("**/*", (route) => {
    const url = route.request().url();
    if (url.startsWith("http://127.0.0.1:8000")) {
      route.continue();
    } else {
      route.abort();
    }
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error" && !text.includes("ERR_FAILED")) errors.push(text);
  });

  console.log("Opening local dashboard...");
  await page.goto("http://127.0.0.1:8000/", {
    waitUntil: "domcontentloaded",
    timeout: 15000,
  });
  await page.waitForTimeout(8000);
  await page.waitForFunction(
    () =>
      document.getElementById("sysCpu")?.textContent !== "--%" &&
      document.getElementById("netStatus")?.textContent !== "--",
    { timeout: 20000 }
  );
  await page.evaluate(() => {
    const maskPrivateData = () => {
      const name = document.getElementById("currentNetworkName");
      const meta = document.getElementById("currentNetworkMeta");
      const rename = document.getElementById("networkRenameInput");
      if (name) name.textContent = "Rede residencial";
      if (meta) meta.textContent = "sub-rede local protegida";
      if (rename) rename.value = "Rede residencial";
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        node.textContent = node.textContent.replace(
          /\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b/g,
          (address) => (address.endsWith(".1") ? "192.168.1.1" : "192.168.1.25")
        );
      }
    };
    maskPrivateData();
    window.setInterval(maskPrivateData, 100);
  });
  await page.addStyleTag({
    content: "*, *::before, *::after { animation: none !important; transition: none !important; }",
  });
  await page.screenshot({
    path: path.join(screenshotDir, "dashboard-overview.png"),
    fullPage: true,
    animations: "disabled",
    timeout: 10000,
  });
  await page.locator(".utility-grid").screenshot({
    path: path.join(screenshotDir, "system-monitor.png"),
    animations: "disabled",
    timeout: 10000,
  });
  await page.locator(".panel-topology").screenshot({
    path: path.join(screenshotDir, "network-topology.png"),
    animations: "disabled",
    timeout: 10000,
  });
  for (let index = 0; index < 12; index += 1) {
    await page.screenshot({
      path: path.join(framesDir, `frame-${String(index).padStart(3, "0")}.png`),
      animations: "disabled",
      timeout: 10000,
    });
    await page.waitForTimeout(150);
  }
  await page.locator('.safe-cmd[data-action="system_status"]').click();
  await page.waitForFunction(
    () => document.getElementById("safeTerminalOutput")?.textContent.includes("CPU:"),
    { timeout: 10000 }
  );
  await page.screenshot({
    path: path.join(screenshotDir, "safe-terminal.png"),
    fullPage: true,
    animations: "disabled",
    timeout: 10000,
  });
  for (let index = 12; index < 30; index += 1) {
    await page.screenshot({
      path: path.join(framesDir, `frame-${String(index).padStart(3, "0")}.png`),
      animations: "disabled",
      timeout: 10000,
    });
    await page.waitForTimeout(150);
  }

  await page.close();
  await context.close();
  await browser.close();

  console.log("Rendering video from captured frames...");
  const outputVideo = path.join(videoDir, "dashboard-demo.webm");
  const ffmpeg = spawnSync(
    "ffmpeg",
    [
      "-y",
      "-framerate",
      "5",
      "-i",
      path.join(framesDir, "frame-%03d.png"),
      "-c:v",
      "libvpx-vp9",
      "-pix_fmt",
      "yuv420p",
      outputVideo,
    ],
    { stdio: "inherit" }
  );
  if (ffmpeg.status !== 0) throw new Error("ffmpeg could not render the demo video.");

  if (errors.length) {
    console.error(errors.join("\n"));
    process.exitCode = 1;
  } else {
    console.log("Demo captured without browser console errors.");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
