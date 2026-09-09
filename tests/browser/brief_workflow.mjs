// Native Chrome DevTools checks; Node 22+ and an installed Chromium browser.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const [browserPath, profile, briefUrl] = process.argv.slice(2);
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const browser = spawn(browserPath, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank",
], { windowsHide: true, stdio: "ignore" });
let socket;
const pending = new Map();
let sequence = 0;

async function until(check, message, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await check();
    if (value) return value;
    await delay(100);
  }
  throw new Error(message);
}

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => reject(new Error(`Timed out: ${method}`)), 15000);
    pending.set(id, {
      resolve: (value) => { clearTimeout(timer); resolve(value); },
      reject: (error) => { clearTimeout(timer); reject(error); },
    });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const response = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
  return response.result.value;
}

async function navigate(url, selector) {
  await command("Page.navigate", { url });
  await until(() => evaluate(`document.readyState === 'complete' && !!document.querySelector(${JSON.stringify(selector)})`), `Page did not load: ${url}`);
}

try {
  const port = await until(async () => {
    try { return (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]; }
    catch { return null; }
  }, "Headless browser did not start");
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find((target) => target.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  const pageErrors = [];
  const confirmMessages = [];
  let dialogChoice = false;
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.method === "Page.javascriptDialogOpening") {
      confirmMessages.push(message.params.message);
      command("Page.handleJavaScriptDialog", { accept: dialogChoice }).catch(error => pageErrors.push(error.message));
    }
    if (message.method === "Runtime.exceptionThrown") pageErrors.push(message.params.exceptionDetails);
    if (!message.id) return;
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  await command("Page.enable");
  await command("Runtime.enable");
  const expected = ["Original idea", "Product foundation", "Audience and user outcomes", "Core experience and features", "Data and integrations", "Constraints and risks", "Acceptance criteria"];
  const layouts = [];
  for (const width of [1600, 1024, 820, 390, 320]) {
    await command("Emulation.setDeviceMetricsOverride", { width, height: 1000, deviceScaleFactor: 1, mobile: false });
    await navigate(briefUrl, ".brief-module-grid");
    const layout = await evaluate(`(() => {
      const grid = document.querySelector('.brief-module-grid');
      const cards = [...grid.children];
      const advanced = document.querySelector('.advanced-editing-panel');
      return {
        headings: cards.map(card => card.querySelector('h2').textContent.trim()),
        columns: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
        rects: cards.map(card => { const r = card.getBoundingClientRect(); return {x:r.x, y:r.y, width:r.width, bottom:r.bottom}; }),
        overflow: document.documentElement.scrollWidth > innerWidth,
        cardOverflow: cards.some(card => card.scrollWidth > card.clientWidth),
        advancedVisible: advanced.checkVisibility() && !advanced.closest('details') && !advanced.querySelector('summary'),
        advancedAfterGrid: advanced.getBoundingClientRect().top >= grid.getBoundingClientRect().bottom,
        summariesRemoved: !document.body.textContent.includes('Brief health') && !document.body.textContent.includes('Core brief details are present') && !document.body.textContent.includes('Workflow summary'),
        gridWidth: grid.getBoundingClientRect().width,
        links: [...advanced.querySelectorAll('a')].map(a => a.textContent.trim().split('\\n')[0]),
        editCount: cards.filter(card => card.textContent.includes('Edit section')).length,
      };
    })()`);
    assert.deepEqual(layout.headings, expected);
    assert.equal(layout.columns, width > 680 ? 2 : 1, `Columns at ${width}px`);
    assert.equal(layout.overflow, false, `Page overflow at ${width}px`);
    assert.equal(layout.cardOverflow, false, `Card overflow at ${width}px`);
    assert.ok(layout.advancedVisible && layout.advancedAfterGrid && layout.summariesRemoved);
    assert.deepEqual(layout.links, ["Background Information", "Build Instructions"]);
    assert.equal(layout.editCount, 7);
    const accessibility = await command("Accessibility.getFullAXTree");
    assert.deepEqual(accessibility.nodes
      .filter(node => node.role?.value === "heading" && expected.includes(node.name?.value))
      .map(node => node.name.value), expected);
    assert.ok(Math.abs(layout.rects[0].width - layout.gridWidth) < 1, 'Original Idea must span the full row');
    if (width > 680) {
      for (const index of [1, 3, 5]) {
        const left = layout.rects[index], right = layout.rects[index + 1];
        assert.ok(Math.abs(left.width - right.width) < 1);
        assert.equal(left.y, right.y);
        assert.equal(left.bottom, right.bottom, `Unequal card heights at ${width}px`);
        assert.ok(right.x > left.x);
        assert.ok(left.y >= layout.rects[index - 1].bottom);
      }
    } else {
      assert.ok(layout.rects.every(rect => rect.x === layout.rects[0].x));
    }
    await evaluate(`document.querySelector('[data-edit-section]').focus()`);
    for (let index = 1; index < expected.length; index++) {
      await command("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
      await command("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
      assert.equal(await evaluate(`document.activeElement.closest('.brief-section').querySelector('h2').textContent.trim()`), expected[index]);
    }
    if ([1600, 390].includes(width)) {
      await evaluate("window.scrollTo(0, 0)");
      const screenshot = await command("Page.captureScreenshot", { format: "png" });
      await writeFile(join(profile, `brief-${width}.png`), Buffer.from(screenshot.data, "base64"));
    }
    layouts.push({ width, columns: layout.columns });
  }

  const baseUrl = briefUrl.replace(/\/brief$/, "");
  const moduleKeys = ['original_idea', 'product_foundation', 'audience', 'core_experience', 'data_integrations', 'constraints_risks', 'acceptance'];
  const edits = ['project.description', 'product_intent.problem_statement', 'product_intent.user_goal', 'build_target.core_features', 'build_target.data_entities', 'product_intent.known_constraints', 'definition_of_done.functional_acceptance_criteria'];
  async function openSection(key) {
    await evaluate(`document.querySelector('[data-edit-section="${key}"]').click()`);
    await until(() => evaluate(`document.querySelector('#brief-editor').open && !document.querySelector('#brief-editor-save').disabled && document.querySelector('#brief-editor-fields').children.length > 0`), `Could not open ${key}`);
    await evaluate(`Promise.all(document.querySelector('#brief-editor').getAnimations().map(animation => animation.finished))`);
  }
  async function escape() {
    await command('Input.dispatchKeyEvent', {type:'keyDown', key:'Escape', code:'Escape', windowsVirtualKeyCode:27});
    await command('Input.dispatchKeyEvent', {type:'keyUp', key:'Escape', code:'Escape', windowsVirtualKeyCode:27});
  }
  // Navigation always opens Overview, even after another tab was used.
  await navigate(new URL('/agents', briefUrl).href, '.agent-card');
  const openHref = await evaluate(`(() => {
    const link = [...document.querySelectorAll('.agent-card a')].find(a => a.textContent.trim() === 'Open agent' && a.href === ${JSON.stringify(baseUrl)});
    if (!link) return null;
    link.click(); return link.href;
  })()`);
  assert.equal(openHref, baseUrl);
  await until(() => evaluate(`document.querySelector('.rail-nav [aria-current="page"]')?.textContent.trim() === 'Overview'`), 'Overview did not activate');
  await navigate(briefUrl, '.brief-module-grid');
  await evaluate('window.briefNavigationMarker = true');
  for (let index = 0; index < moduleKeys.length; index++) {
    const key = moduleKeys[index];
    await openSection(key);
    assert.equal(await evaluate(`document.querySelector('#brief-editor-title').textContent`), expected[index]);
    const panel = await evaluate(`(() => {
      const dialog = document.querySelector('#brief-editor');
      const r = dialog.getBoundingClientRect();
      return {width:r.width, right:r.right, viewport:innerWidth, focusInside:dialog.contains(document.activeElement), overflow:dialog.scrollWidth > dialog.clientWidth};
    })()`);
    assert.equal(panel.focusInside, true);
    assert.equal(panel.overflow, false);
    assert.ok(Math.abs(panel.right - panel.viewport) < 1);
    assert.ok(Math.abs(panel.width - panel.viewport) < 1, 'Mobile panel must use the full width');
    const ax = await command('Accessibility.getFullAXTree');
    assert.ok(ax.nodes.some(node => node.role?.value === 'dialog' && node.name?.value === expected[index]));
    const snapshot = await evaluate(`fetch('${baseUrl}/brief/sections/${key}'.replace('/agents/', '/api/agents/')).then(r => r.json()).then(r => r.data.module)`);
    const loaded = await evaluate(`[...document.querySelector('#brief-editor-fields').children].map(field => ({key:field.dataset.fieldKey, values:[...field.querySelectorAll('textarea')].map(input => input.value)}))`);
    assert.deepEqual(loaded, snapshot.fields.map(field => ({key:field.key, values:field.type === 'list' ? field.items.map(item => item.text) : [field.value]})));
    // Native modal behavior prevents even scripted focus from reaching the page.
    await evaluate(`document.querySelector('.rail-nav a').focus()`);
    assert.ok(await evaluate(`document.querySelector('#brief-editor').contains(document.activeElement)`));
    await evaluate(`document.querySelector('#brief-editor-save').focus()`);
    await command('Input.dispatchKeyEvent', {type:'keyDown', key:'Tab', code:'Tab', windowsVirtualKeyCode:9});
    await command('Input.dispatchKeyEvent', {type:'keyUp', key:'Tab', code:'Tab', windowsVirtualKeyCode:9});
    assert.equal(await evaluate(`document.activeElement.getAttribute('aria-label')`), 'Close editing panel');
    await evaluate(`(() => {
      const field = document.querySelector('[data-field-key="${edits[index]}"]');
      if (!field.querySelector('textarea')) field.querySelector('[data-add-brief-item]').click();
      field.querySelector('textarea').value = 'Saved ${key} from panel';
      document.querySelector('#brief-editor-save').click();
    })()`);
    await until(() => evaluate(`!document.querySelector('#brief-editor').open`), `Save did not close ${key}`);
    assert.ok(await evaluate(`window.briefNavigationMarker && document.querySelector('#brief-modules').textContent.includes('Saved ${key} from panel')`));
    await until(() => evaluate(`document.activeElement.dataset.editSection === '${key}'`), 'Focus did not return to opener');
    assert.ok(await evaluate(`document.querySelector('.flash-stack').textContent.includes('Changes saved')`));
  }
  await navigate(briefUrl, '.brief-module-grid');
  for (const key of moduleKeys) assert.ok(await evaluate(`document.querySelector('#brief-modules').textContent.includes('Saved ${key} from panel')`));
  // Cancel and Escape discard only after a warning; declining keeps the draft.
  await openSection('original_idea');
  await evaluate(`document.querySelector('[data-field-key="project.description"] textarea').value = 'Unsaved description'`);
  dialogChoice = false;
  await escape();
  assert.ok(await evaluate(`document.querySelector('#brief-editor').open`));
  assert.ok(confirmMessages.at(-1).includes('unsaved changes'));
  dialogChoice = true;
  await evaluate(`document.querySelector('.brief-editor-actions [data-close-brief-editor]').click()`);
  await until(() => evaluate(`!document.querySelector('#brief-editor').open`), 'Cancel did not close');
  await openSection('original_idea');
  assert.equal(await evaluate(`document.querySelector('[data-field-key="project.description"] textarea').value`), 'Saved original_idea from panel');
  const confirmations = confirmMessages.length;
  await escape();
  await until(() => evaluate(`!document.querySelector('#brief-editor').open`), 'Escape did not close clean panel');
  assert.equal(confirmMessages.length, confirmations);
  // A failed save keeps edits and announces an error in the open dialog.
  await openSection('original_idea');
  await evaluate(`(() => {
    window.realFetch = window.fetch;
    window.fetch = (url, options) => options?.method === 'PATCH' ? Promise.resolve(new Response(JSON.stringify({ok:false,error:{message:'Test save failed'}}), {status:400, headers:{'Content-Type':'application/json'}})) : window.realFetch(url, options);
    document.querySelector('[data-field-key="project.description"] textarea').value = 'Keep this failed draft';
    document.querySelector('#brief-editor-save').click();
  })()`);
  await until(() => evaluate(`document.querySelector('#brief-editor-message').textContent === 'Test save failed'`), 'Save error was not displayed');
  assert.ok(await evaluate(`document.querySelector('#brief-editor').open && document.querySelector('[data-field-key="project.description"] textarea').value === 'Keep this failed draft'`));
  await evaluate('window.fetch = window.realFetch');
  dialogChoice = true;
  await escape();
  await command('Emulation.setDeviceMetricsOverride', {width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await openSection('constraints_risks');
  const desktopPanel = await evaluate(`(() => { const r = document.querySelector('#brief-editor').getBoundingClientRect(); return {width:r.width, right:r.right}; })()`);
  assert.equal(desktopPanel.width, 620);
  assert.equal(desktopPanel.right, 1600);
  const panelScreenshot = await command('Page.captureScreenshot', {format:'png'});
  await writeFile(join(profile, 'brief-editor.png'), Buffer.from(panelScreenshot.data, 'base64'));
  await escape();

  await navigate(`${baseUrl}/background`, "[data-generate-instructions]");
  await evaluate(`document.querySelector('[data-generate-instructions]').click()`);
  await until(() => evaluate(`location.pathname.endsWith('/instructions') && !!document.querySelector('#contract-editor')`), "Generate did not open Build Instructions");
  assert.ok(await evaluate(`document.body.textContent.includes('Who approves route changes?')`));
  // A pending edit must survive generation even before the autosave timer fires.
  await evaluate(`(() => {
    window.generationPending = true;
    const input = document.querySelector('[data-section="product_intent"] [data-field="problem_statement"] textarea');
    input.value = 'Browser-edited dispatch problem';
    input.dispatchEvent(new Event('input', {bubbles:true}));
    document.querySelector('[data-generate-instructions]').click();
  })()`);
  await until(() => evaluate(`!window.generationPending && document.querySelector('[data-field="problem_statement"] textarea')?.value === 'Browser-edited dispatch problem'`), "Generation lost the pending instruction edit");

  await command("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await navigate(`${baseUrl}/workflow`, ".workflow-node");
  await evaluate(`document.querySelector('.workflow-node').click()`);
  await until(() => evaluate(`!document.querySelector('#node-form').classList.contains('hidden')`), "Step Details did not open");
  await evaluate(`(() => {
    const form = document.querySelector('#node-form');
    form.elements.label.value = 'Browser-edited workflow step';
    form.requestSubmit();
  })()`);
  await until(() => evaluate(`document.querySelector('#workflow-nodes').textContent.includes('Browser-edited workflow step')`), "Step did not save");
  await navigate(`${baseUrl}/workflow`, ".workflow-node");
  assert.ok(await evaluate(`document.querySelector('#workflow-nodes').textContent.includes('Browser-edited workflow step')`));
  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ layouts, keyboardOrder: "passed", generation: "passed", workflowEditing: "passed", screenshots: profile }));
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ id: ++sequence, method: "Browser.close" }));
    socket.close();
    await delay(250);
  }
  browser.kill();
}
