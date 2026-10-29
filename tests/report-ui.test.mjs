// DOM-level interaction checks, not a substitute for real browser layout testing.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { JSDOM, VirtualConsole } from "jsdom";

const html = readFileSync(new URL("../reports/demo.html", import.meta.url), "utf8");
const source = JSON.parse(/<script type="application\/json" id="report-data">([\s\S]*?)<\/script>/.exec(html)[1]);

function page(t, {hash = "", data} = {}) {
  const errors = [];
  const console = new VirtualConsole();
  console.on("jsdomError", error => errors.push(error.message));
  const content = data ? html.replace(
    /(<script type="application\/json" id="report-data">)[\s\S]*?(<\/script>)/,
    (_, open, close) => open + JSON.stringify(data).replaceAll("<", "\\u003c") + close,
  ) : html;
  let prints = 0;
  const dom = new JSDOM(content, {
    runScripts: "dangerously",
    // A synthetic origin supplies URL/history semantics. No network resources are loaded.
    url: `https://report.test/evaluation.html${hash}`,
    virtualConsole: console,
    beforeParse(window) {
      window.matchMedia = () => ({matches: false});
      window.HTMLElement.prototype.scrollIntoView = () => {};
      window.print = () => { prints += 1; };
    },
  });
  t.after(() => dom.window.close());
  assert.deepEqual(errors, [], "The report script must initialize without DOM errors");
  const document = dom.window.document;
  return {
    window: dom.window, document, prints: () => prints,
    get: id => document.getElementById(id),
    rows: () => [...document.querySelectorAll("#case-table-body > .case-row")],
    change(id, value) {
      const control = document.getElementById(id);
      if (control.type === "checkbox") control.checked = value;
      else control.value = value;
      control.dispatchEvent(new dom.window.Event(control.tagName === "INPUT" && control.type !== "checkbox" ? "input" : "change", {bubbles: true}));
    },
  };
}

test("overview uses the fixed set while pagination and sorting change the list", t => {
  const p = page(t);
  const overview = p.get("metric-cards").textContent;
  assert.equal(p.rows().length, 25);
  assert.match(p.get("result-count").textContent, /36 matching cases/);
  p.get("next-page").click();
  assert.equal(p.rows().length, 11);
  assert.match(p.get("page-label").textContent, /Page 2 of 2/);
  p.get("prev-page").click();
  assert.equal(p.rows().length, 25);
  const sort = p.document.querySelector('[data-sort="case_id"]');
  sort.click();
  sort.click();
  assert.equal(p.rows()[0].querySelector(".case-id-text").textContent, "synthetic-036");
  assert.equal(sort.closest("th").getAttribute("aria-sort"), "descending");
  assert.equal(p.get("metric-cards").textContent, overview);
});

test("search, per-metric status and disagreement filters preserve overview totals", t => {
  const p = page(t);
  const overview = p.get("metric-cards").textContent;
  p.change("case-search", "synthetic-004");
  assert.equal(p.rows().length, 1);
  p.get("clear-filters").click();
  p.change("metric-filter", "sql_semantic");
  p.change("status-filter", "FAIL");
  const expected = source.cases.filter(item => item.scores.sql_semantic.status === "FAIL").length;
  assert.equal(p.rows().length, expected);
  assert.ok(p.rows().every(row => row.lastElementChild.textContent.includes("FAIL")));
  p.get("clear-filters").click();
  p.change("disagreement-filter", true);
  assert.equal(p.rows().length, 4);
  assert.ok(p.rows().every(row => row.children[3].textContent.includes("PASS") && row.children[4].textContent.includes("FAIL")));
  assert.equal(p.get("metric-cards").textContent, overview);
  p.change("case-search", "no matching question exists");
  assert.equal(p.rows().length, 0);
  assert.match(p.get("case-table-body").textContent, /No matching cases/);
});

test("case details retain independent previews and Escape restores keyboard focus", t => {
  const p = page(t);
  const opener = p.document.querySelector('[data-case-index="1"]');
  opener.click();
  assert.equal(p.document.querySelectorAll(".case-detail").length, 1);
  assert.equal(p.document.activeElement.id, "case-detail-title-1");
  assert.equal(p.window.location.hash, "#case-1");
  const tables = p.document.querySelectorAll(".preview-table");
  assert.equal(tables.length, 2);
  assert.equal(tables[0].querySelector("tbody tr td").textContent, "1");
  assert.equal(tables[1].querySelector("tbody tr td").textContent, "3");
  assert.match(p.document.querySelector(".preview-note").textContent, /Row positions do not indicate matched records/);
  assert.equal(p.document.querySelectorAll(".sql-code").length, 2);
  assert.equal(p.document.querySelectorAll(".metric-detail").length, 3);
  p.document.dispatchEvent(new p.window.KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  assert.equal(p.document.querySelectorAll(".case-detail").length, 0);
  assert.equal(p.document.activeElement.dataset.caseIndex, "1");
});

test("truncated cases display fifty rows per result with full counts", t => {
  const p = page(t);
  p.document.querySelector('[data-case-index="2"]').click();
  const tables = [...p.document.querySelectorAll(".preview-table")];
  assert.ok(tables.every(table => table.tBodies[0].rows.length === 50));
  assert.equal(p.document.querySelectorAll(".preview-flag").length, 2);
  assert.match(p.document.querySelector(".preview-stats").textContent, /1,200/);
});

test("case links open the correct page; theme and print controls work", t => {
  const p = page(t, {hash: "#case-35"});
  assert.equal(p.document.querySelector(".case-detail").id, "case-detail-35");
  assert.match(p.get("page-label").textContent, /Page 2 of 2/);
  assert.equal(p.document.documentElement.dataset.theme, "light");
  p.get("theme-toggle").click();
  assert.equal(p.document.documentElement.dataset.theme, "dark");
  assert.equal(p.get("theme-toggle").getAttribute("aria-label"), "Switch to light theme");
  p.get("print-report").click();
  assert.equal(p.prints(), 1);
});

test("reviews and execution errors remain distinct from confirmed SQL failures", t => {
  const p = page(t);
  p.document.querySelector('[data-case-index="7"]').click();
  assert.match(p.document.querySelector(".execution-error").textContent, /missing_amount/);
  assert.match(p.document.querySelector(".metric-detail-grid").textContent, /No correctness verdict was made/);
  p.document.querySelector('[data-case-index="8"]').click();
  assert.match(p.document.querySelector(".decision-note.is-review").textContent, /Provisional PASS is not counted/);
  const overview = source.summary.sql_semantic;
  assert.equal(overview.review, 4);
});

test("empty reports have undefined rates and no fabricated cases", t => {
  const data = structuredClone(source);
  data.cases = [];
  for (const metric of Object.values(data.summary)) {
    Object.assign(metric, {cases: 0, passed: 0, failed: 0, review: 0, errors: 0, pass_rate: null, decision_coverage: null});
  }
  const p = page(t, {data});
  assert.equal(p.rows().length, 0);
  assert.match(p.get("case-table-body").textContent, /No evaluation cases/);
  assert.ok([...p.document.querySelectorAll(".metric-number")].every(item => item.textContent === "—"));
});

test("SQL and cell strings become literal text, never executable DOM markup", t => {
  const data = structuredClone(source);
  const hostile = '<img src=x onerror="window.injected=true"><script>window.injected=true</script>';
  data.cases[0].question = hostile;
  data.cases[0].target_sql = hostile;
  data.cases[0].target_result.rows[0][1] = hostile;
  data.cases[0].target_result.display_rows[0][1] = hostile;
  const p = page(t, {data});
  p.document.querySelector('[data-case-index="0"]').click();
  assert.equal(p.document.querySelectorAll("img").length, 0);
  assert.equal(p.window.injected, undefined);
  assert.equal(p.document.querySelector(".detail-question").textContent, hostile);
  assert.equal(p.document.querySelector(".sql-code code").textContent, hostile);
  assert.ok([...p.document.querySelectorAll(".preview-table td")].some(cell => cell.textContent === hostile));
});
