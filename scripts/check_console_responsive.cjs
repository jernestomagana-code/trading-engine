// Read-only browser acceptance test. Temporary profile; no operator actions.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const baseUrl = process.env.ULTIMUS_CONSOLE_TEST_URL || 'http://127.0.0.1:8767/?qa=1';

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [320, 390, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 844 } });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
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
      const focusButton = page.locator('[data-focus-mode]');
      assert.equal(await focusButton.count(), 1, `${width}: focus mode remains available`);
      await focusButton.click();
      assert.equal(await focusButton.getAttribute('aria-pressed'), 'true', `${width}: focus mode announces state`);
      await focusButton.click();
      await page.getByRole('link', { name: 'Actividad', exact: true }).click();
      assert.equal(await page.locator('#case-phase').inputValue(), 'open', `${width}: current positions are the default case scope`);
      await page.locator('#activity-type').selectOption('alert');
      assert.equal(await page.locator('[data-activity-at]:visible').count() > 0, true, `${width}: alert activity filter`);
      await page.getByRole('link', { name: 'Oportunidades', exact: true }).click();
      const detail = page.locator('a[href^="#canslim-"]').first();
      if (await detail.count()) {
        await detail.click();
        assert.equal(await page.locator('[data-console-view="oportunidades"]').isVisible(), true, `${width}: CANSLIM deep link remains visible`);
      }
      await page.goBack();
      assert.equal(await page.locator('[data-console-view="oportunidades"]').isVisible(), true, `${width}: back navigation`);
      await page.goForward();
      assert.equal(await page.locator('[data-console-view="oportunidades"]').isVisible(), true, `${width}: forward navigation`);
      const semantics = await page.evaluate(() => ({
        duplicateIds: Array.from(document.querySelectorAll('[id]')).map(x => x.id).filter((id, index, all) => all.indexOf(id) !== index),
        unlabeledControls: Array.from(document.querySelectorAll('input,select,textarea')).filter(control => !control.labels?.length && !control.getAttribute('aria-label') && control.type !== 'hidden').length,
      }));
      assert.deepEqual(semantics.duplicateIds, [], `${width}: duplicate ids`);
      assert.equal(semantics.unlabeledControls, 0, `${width}: form controls have accessible names`);
      assert.deepEqual(errors, [], `${width}: browser errors`);
      console.log(JSON.stringify({ width, navigation: 'PASS', horizontalOverflow: false, browserErrors: errors.length }));
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
