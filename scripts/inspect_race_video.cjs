// Offline frame extraction through installed Chromium; source video is read-only.
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const { chromium } = require(process.env.LICOR_PLAYWRIGHT_PATH || 'playwright');

(async () => {
  const [video, output, ...seconds] = process.argv.slice(2);
  const browser = await chromium.launch({
    executablePath: process.env.LICOR_CHROMIUM_PATH,
    headless: true,
  });
  try {
    const page = await browser.newPage({viewport: {width: 1920, height: 1080}});
    await page.goto(pathToFileURL(path.resolve(video)).href);
    await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2);
    console.log(await page.evaluate(() => {
      const v = document.querySelector('video');
      v.pause();
      return {duration: v.duration, width: v.videoWidth, height: v.videoHeight};
    }));
    fs.mkdirSync(output, {recursive: true});
    for (const timestamp of seconds.map(Number)) {
      await page.evaluate(async t => {
        const v = document.querySelector('video');
        if (t < 0 || t >= v.duration) throw Error('Timestamp out of bounds');
        await new Promise(resolve => {
          v.addEventListener('seeked', resolve, {once: true});
          v.currentTime = t;
        });
        v.controls = false;
        v.style.width = '1920px'; v.style.height = '1080px';
      }, timestamp);
      const target = path.join(output, `frame_${timestamp}.png`);
      if (fs.existsSync(target)) throw Error(`Output exists: ${target}`);
      await page.locator('video').screenshot({path: target});
      console.log(`Extracted ${timestamp}s`);
    }
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
