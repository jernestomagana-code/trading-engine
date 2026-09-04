// Read-only browser smoke test. Temporary browser profile; no operator actions.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 844 } });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('http://127.0.0.1:8765/console', { waitUntil: 'domcontentloaded' });
      for (const label of ['Hoy', 'Cartera', 'Oportunidades', 'Actividad', 'Más']) {
        await page.getByRole('link', { name: label, exact: true }).click();
        const state = await page.evaluate(() => ({
          active: Array.from(document.querySelectorAll('[data-console-view]')).filter(x => !x.hidden).length,
          width: document.documentElement.clientWidth,
          scroll: document.documentElement.scrollWidth,
        }));
        assert.equal(state.active, 1, `${width}/${label}: exactly one panel`);
        assert.ok(state.scroll <= state.width + 2, `${width}/${label}: horizontal overflow ${JSON.stringify(state)}`);
        if (label === 'Hoy' || label === 'Oportunidades') {
          await page.screenshot({ path: `/tmp/stock-ultimus-${width}-${label}.png` });
        }
      }
      await page.goBack();
      assert.equal(await page.locator('[data-console-view="historial"]').isVisible(), true, `${width}: back navigation`);
      assert.deepEqual(errors, [], `${width}: browser errors`);
      console.log(JSON.stringify({ width, navigation: 'PASS', horizontalOverflow: false, browserErrors: errors.length }));
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
