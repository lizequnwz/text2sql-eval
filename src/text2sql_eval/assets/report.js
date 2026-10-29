"use strict";

(() => {
  const report = JSON.parse(document.getElementById("report-data").textContent);
  const metricDefinitions = [
    {key: "row_count_match", label: "Row count match", description: "The complete result row counts are equal."},
    {key: "sampled_result_consistency", label: "Sampled consistency", description: "No contradiction found in the supplied sample."},
    {key: "sql_semantic", label: "SQL semantics", description: "The judge considers the SQL to satisfy the question."},
  ];
  const statuses = ["PASS", "FAIL", "REVIEW", "ERROR"];
  const statusIcons = {PASS: "✓", FAIL: "×", REVIEW: "?", ERROR: "!"};
  const statusRank = {ERROR: 0, REVIEW: 1, FAIL: 2, PASS: 3};
  const number = new Intl.NumberFormat(undefined, {maximumFractionDigits: 0});
  const percentage = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});
  const formatRate = value => value === null ? "—" : percentage.format(value);
  const byId = id => document.getElementById(id);
  const records = report.cases.map((data, index) => ({
    data,
    index,
    search: [data.case_id, data.question, data.target_sql, data.generated_sql,
      ...metricDefinitions.flatMap(metric => {
        const score = data.scores[metric.key];
        return [score.reason, ...(score.judgment?.evidence || [])];
      })].join(" ").toLocaleLowerCase(),
  }));
  const state = {search: "", metric: "all", status: "all", disagreement: false, page: 1,
    sort: null, direction: "ascending", expanded: null};
  const pageSize = 25;

  function element(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = String(text);
    return result;
  }

  function statusBadge(status) {
    const badge = element("span", `status status-${status}`);
    const icon = element("span", "status-icon", statusIcons[status]);
    icon.setAttribute("aria-hidden", "true");
    badge.append(icon, document.createTextNode(status));
    return badge;
  }

  function renderOverview() {
    document.title = report.title;
    byId("report-title").textContent = report.title;
    byId("total-cases").textContent = `${number.format(records.length)} cases · fixed evaluation set`;
    const version = element("p");
    version.append(document.createTextNode("Producer "), element("strong", "", `v${report.package_version}`));
    const rendered = element("p", "", `Report rendered ${new Date(report.rendered_at).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC")}`);
    byId("run-meta").append(version, rendered);
    const cards = byId("metric-cards");
    metricDefinitions.forEach((metric, index) => {
      const summary = report.summary[metric.key];
      const card = element("article", "metric-card");
      const top = element("div", "metric-topline");
      top.append(element("span", "metric-index", `0${index + 1}`), element("h3", "metric-name", metric.label));
      card.append(top, element("p", "metric-number", formatRate(summary.pass_rate)),
        element("p", "metric-count", `${number.format(summary.passed)} of ${number.format(summary.cases)} cases passed`),
        element("p", "metric-description", metric.description));
      const bar = element("div", "status-bar");
      bar.setAttribute("aria-hidden", "true");
      const legend = element("div", "metric-legend");
      const countKeys = {PASS: "passed", FAIL: "failed", REVIEW: "review", ERROR: "errors"};
      statuses.forEach(status => {
        const count = summary[countKeys[status]];
        const segment = element("span", `segment-${status}`);
        segment.style.width = `${summary.cases ? count / summary.cases * 100 : 0}%`;
        bar.append(segment);
        const item = element("span", "legend-item");
        const dot = element("span", `legend-dot status-${status}`);
        dot.setAttribute("aria-hidden", "true");
        item.append(dot, document.createTextNode(`${number.format(count)} ${status.toLowerCase()}`));
        legend.append(item);
      });
      const coverage = element("p", "coverage-line");
      coverage.append(element("span", "", "Decision coverage"), element("strong", "", formatRate(summary.decision_coverage)));
      card.append(bar, legend, coverage);
      cards.append(card);
    });
  }

  function isDisagreement(record) {
    const sample = record.data.scores.sampled_result_consistency.status;
    const semantics = record.data.scores.sql_semantic.status;
    return (sample === "PASS" && semantics === "FAIL") || (sample === "FAIL" && semantics === "PASS");
  }

  function selectedRecords() {
    const filtered = records.filter(record => {
      if (state.search && !record.search.includes(state.search)) return false;
      if (state.disagreement && !isDisagreement(record)) return false;
      if (state.status !== "all") {
        const keys = state.metric === "all" ? metricDefinitions.map(metric => metric.key) : [state.metric];
        if (!keys.some(key => record.data.scores[key].status === state.status)) return false;
      }
      return true;
    });
    if (state.sort) {
      const direction = state.direction === "ascending" ? 1 : -1;
      filtered.sort((left, right) => {
        let comparison;
        if (state.sort === "case_id" || state.sort === "question") {
          comparison = left.data[state.sort].localeCompare(right.data[state.sort], undefined, {numeric: true});
        } else {
          comparison = statusRank[left.data.scores[state.sort].status] - statusRank[right.data.scores[state.sort].status];
        }
        return comparison * direction || left.index - right.index;
      });
    }
    return filtered;
  }

  function tableRow(record) {
    const row = element("tr", `case-row${state.expanded === record.index ? " is-expanded" : ""}`);
    row.id = `case-${record.index}`;
    const idCell = element("td");
    const opener = element("button", "case-opener");
    opener.type = "button";
    opener.dataset.caseIndex = String(record.index);
    opener.setAttribute("aria-expanded", String(state.expanded === record.index));
    opener.setAttribute("aria-controls", `case-detail-${record.index}`);
    opener.setAttribute("aria-label", `Review case ${record.data.case_id}`);
    const chevron = element("span", "chevron", state.expanded === record.index ? "⌄" : "›");
    chevron.setAttribute("aria-hidden", "true");
    opener.append(chevron, element("span", "case-id-text", record.data.case_id));
    opener.addEventListener("click", () => toggleCase(record.index));
    idCell.append(opener);
    row.append(idCell, element("td", "case-question", record.data.question));
    metricDefinitions.forEach(metric => {
      const cell = element("td", "status-cell");
      cell.append(statusBadge(record.data.scores[metric.key].status));
      row.append(cell);
    });
    return row;
  }

  function sqlPanel(label, sql) {
    const panel = element("section", "compare-panel");
    const heading = element("div", "panel-header");
    heading.append(element("h5", "", label), element("span", "panel-marker", "SQL"));
    const pre = element("pre", "sql-code");
    pre.tabIndex = 0;
    pre.setAttribute("aria-label", label);
    pre.append(element("code", "", sql || "No generated SQL is available."));
    panel.append(heading, pre);
    return panel;
  }

  function previewPanel(label, result) {
    const panel = element("section", "compare-panel");
    const heading = element("div", "panel-header");
    heading.append(element("h5", "", label), element("span", "panel-marker", "Execution preview"));
    panel.append(heading);
    if (result.execution_error !== null) {
      const error = element("div", "execution-error");
      error.append(statusBadge("ERROR"), element("p", "", result.execution_error));
      panel.append(error);
      return panel;
    }
    const stats = element("div", "preview-stats");
    const total = element("span");
    total.append(element("strong", "", number.format(result.total_rows)), document.createTextNode(" total rows"));
    stats.append(total, element("span", "", `${number.format(result.shown_rows)} shown`),
      element("span", "", `${number.format(result.provided_rows)} supplied`));
    if (result.truncated) stats.append(element("span", "preview-flag", "Preview truncated"));
    panel.append(stats);
    if (!result.shown_rows) {
      panel.append(element("p", "empty-preview", result.total_rows === 0
        ? "The query completed successfully and returned no rows."
        : "No preview rows were supplied. The complete output contains records."));
      return panel;
    }
    const wrapper = element("div", "table-scroll");
    wrapper.tabIndex = 0;
    wrapper.setAttribute("role", "region");
    wrapper.setAttribute("aria-label", `${label}: scroll to read all columns`);
    const table = element("table", "preview-table");
    table.append(element("caption", "sr-only", `${label}: ${result.shown_rows} independent preview rows`));
    const head = element("thead");
    const headingRow = element("tr");
    result.columns.forEach(column => {
      const th = element("th", "", column);
      th.scope = "col";
      headingRow.append(th);
    });
    head.append(headingRow);
    const body = element("tbody");
    result.display_rows.forEach((values, rowIndex) => {
      const tr = element("tr");
      values.forEach((value, columnIndex) => {
        const isNull = result.rows[rowIndex][columnIndex] === null;
        const td = element("td", isNull ? "value-null" : "", value);
        if (isNull) td.setAttribute("aria-label", "Database NULL");
        tr.append(td);
      });
      body.append(tr);
    });
    table.append(head, body);
    wrapper.append(table);
    panel.append(wrapper);
    return panel;
  }

  function metadataBlock(metadata) {
    const disclosure = element("details", "metadata");
    disclosure.append(element("summary", "", "Judge metadata"));
    const list = element("dl");
    const entries = [
      ["Model", metadata.model],
      ["Elapsed time", `${metadata.elapsed_seconds.toFixed(2)} seconds`],
      ["Token usage", metadata.token_usage === null ? "Not supplied" : Object.entries(metadata.token_usage).map(([key, value]) => `${key.replaceAll("_", " ")}: ${number.format(value)}`).join(" · ")],
      ["Prompt SHA-256", metadata.prompt_sha256],
    ];
    entries.forEach(([label, value]) => {
      list.append(element("dt", "", label), element("dd", label === "Prompt SHA-256" ? "hash" : "", value));
    });
    disclosure.append(list);
    return disclosure;
  }

  function metricDetail(metric, score) {
    const card = element("section", "metric-detail");
    const heading = element("div", "metric-detail-head");
    heading.append(element("h5", "", metric.label), statusBadge(score.status));
    card.append(heading, element("p", "reason-text", score.reason));
    if (score.judgment) {
      card.append(element("p", "evidence-label", "Evidence"));
      if (score.judgment.evidence.length) {
        const evidence = element("ul", "evidence-list");
        score.judgment.evidence.forEach(item => evidence.append(element("li", "", item)));
        card.append(evidence);
      } else {
        card.append(element("p", "muted", "No evidence items supplied."));
      }
      const note = score.judgment.needs_review
        ? `Review required. Provisional ${score.judgment.verdict} is not counted as a decision.`
        : `Automatic decision · score ${score.score}`;
      card.append(element("p", `decision-note${score.judgment.needs_review ? " is-review" : ""}`, note));
    } else {
      card.append(element("p", "decision-note", score.status === "ERROR"
        ? `No correctness verdict was made.${score.error_type ? ` Error category: ${score.error_type}.` : ""}`
        : `Deterministic comparison · score ${score.score}`));
    }
    if (score.metadata) card.append(metadataBlock(score.metadata));
    return card;
  }

  function detailsRow(record) {
    const row = element("tr", "detail-row");
    const cell = element("td");
    cell.colSpan = 5;
    const detail = element("article", "case-detail");
    detail.id = `case-detail-${record.index}`;
    detail.setAttribute("aria-labelledby", `case-detail-title-${record.index}`);
    const heading = element("div", "detail-header");
    const title = element("h3", "", `Case ${record.data.case_id}`);
    title.id = `case-detail-title-${record.index}`;
    title.tabIndex = -1;
    const close = element("button", "button button-secondary detail-close", "Close details");
    close.type = "button";
    close.addEventListener("click", () => closeCase(true));
    heading.append(title, close);
    detail.append(heading, element("p", "detail-question", record.data.question));
    const facts = element("div", "detail-facts");
    if (record.data.dialect) facts.append(element("span", "plain-chip", `Dialect: ${record.data.dialect}`));
    if (isDisagreement(record)) facts.append(element("span", "plain-chip", "LLM judges disagree: one pass, one fail"));
    if (facts.childNodes.length) detail.append(facts);
    if (record.data.context) {
      const context = element("details", "context-block");
      context.append(element("summary", "", "Context and assumptions"), element("p", "", record.data.context));
      detail.append(context);
    }
    const sql = element("section", "detail-section");
    sql.append(element("h4", "", "SQL comparison"));
    const sqlGrid = element("div", "compare-grid");
    sqlGrid.append(sqlPanel("Target SQL", record.data.target_sql), sqlPanel("Generated SQL", record.data.generated_sql));
    sql.append(sqlGrid);
    const previews = element("section", "detail-section");
    previews.append(element("h4", "", "Execution previews"), element("p", "preview-note", "Independent previews in their returned order. Row positions do not indicate matched records."));
    const previewGrid = element("div", "compare-grid");
    previewGrid.append(previewPanel("Target result", record.data.target_result), previewPanel("Generated result", record.data.generated_result));
    previews.append(previewGrid);
    const judgments = element("section", "detail-section");
    judgments.append(element("h4", "", "Metric decisions and evidence"));
    const judgmentGrid = element("div", "metric-detail-grid");
    metricDefinitions.forEach(metric => judgmentGrid.append(metricDetail(metric, record.data.scores[metric.key])));
    judgments.append(judgmentGrid);
    detail.append(sql, previews, judgments);
    cell.append(detail);
    row.append(cell);
    return row;
  }

  function renderCases() {
    const selected = selectedRecords();
    const pages = Math.max(1, Math.ceil(selected.length / pageSize));
    state.page = Math.min(state.page, pages);
    const start = (state.page - 1) * pageSize;
    const shown = selected.slice(start, start + pageSize);
    const body = byId("case-table-body");
    const fragment = document.createDocumentFragment();
    if (!shown.length) {
      const row = element("tr");
      const cell = element("td", "empty-state");
      cell.colSpan = 5;
      cell.append(element("strong", "", records.length ? "No matching cases" : "No evaluation cases"),
        element("p", "", records.length ? "Try a different search or reset the filters." : "This report contains an empty evaluation set. Rates are undefined."));
      row.append(cell);
      fragment.append(row);
    }
    shown.forEach(record => {
      fragment.append(tableRow(record));
      if (record.index === state.expanded) fragment.append(detailsRow(record));
    });
    body.replaceChildren(fragment);
    const range = selected.length ? `${number.format(start + 1)}–${number.format(start + shown.length)}` : "0";
    const countText = `Showing ${range} of ${number.format(selected.length)} matching cases · ${number.format(records.length)} total`;
    if (byId("result-count").textContent !== countText) byId("result-count").textContent = countText;
    byId("page-label").textContent = `Page ${state.page} of ${pages} · 25 cases per page`;
    byId("prev-page").disabled = state.page <= 1;
    byId("next-page").disabled = state.page >= pages;
    document.querySelectorAll("[data-sort]").forEach(button => {
      const selectedSort = button.dataset.sort === state.sort;
      button.closest("th").setAttribute("aria-sort", selectedSort ? state.direction : "none");
      button.querySelector(".sort-symbol").textContent = selectedSort ? (state.direction === "ascending" ? "↑" : "↓") : "↕";
    });
  }

  function setHash(index) {
    const hash = index === null ? `${window.location.pathname}${window.location.search}` : `#case-${index}`;
    window.history.replaceState(null, "", hash);
  }

  function closeCase(restoreFocus) {
    const previous = state.expanded;
    state.expanded = null;
    setHash(null);
    renderCases();
    if (restoreFocus && previous !== null) document.querySelector(`[data-case-index="${previous}"]`)?.focus();
  }

  function toggleCase(index) {
    if (state.expanded === index) {
      closeCase(true);
      return;
    }
    state.expanded = index;
    setHash(index);
    renderCases();
    const title = byId(`case-detail-title-${index}`);
    title.focus({preventScroll: true});
    title.scrollIntoView({block: "nearest"});
  }

  function syncFilters() {
    byId("case-search").value = state.search;
    byId("metric-filter").value = state.metric;
    byId("status-filter").value = state.status;
    byId("disagreement-filter").checked = state.disagreement;
  }

  function filterChanged() {
    state.search = byId("case-search").value.trim().toLocaleLowerCase();
    state.metric = byId("metric-filter").value;
    state.status = byId("status-filter").value;
    state.disagreement = byId("disagreement-filter").checked;
    state.page = 1;
    state.expanded = null;
    setHash(null);
    renderCases();
  }

  function openHashCase() {
    const match = /^#case-(\d+)$/.exec(window.location.hash);
    if (!match) return;
    const index = Number(match[1]);
    if (!Number.isSafeInteger(index) || index >= records.length) return;
    state.search = "";
    state.metric = "all";
    state.status = "all";
    state.disagreement = false;
    state.expanded = index;
    syncFilters();
    const ordered = selectedRecords();
    state.page = Math.floor(ordered.findIndex(record => record.index === index) / pageSize) + 1;
    renderCases();
    byId(`case-detail-title-${index}`).focus({preventScroll: true});
    byId(`case-${index}`).scrollIntoView({block: "start"});
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const target = theme === "dark" ? "light" : "dark";
    byId("theme-toggle").textContent = `${target === "dark" ? "Dark" : "Light"} theme`;
    byId("theme-toggle").setAttribute("aria-label", `Switch to ${target} theme`);
  }

  renderOverview();
  renderCases();
  applyTheme(window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  byId("theme-toggle").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  byId("print-report").addEventListener("click", () => window.print());
  byId("case-search").addEventListener("input", filterChanged);
  byId("metric-filter").addEventListener("change", filterChanged);
  byId("status-filter").addEventListener("change", filterChanged);
  byId("disagreement-filter").addEventListener("change", filterChanged);
  byId("clear-filters").addEventListener("click", () => {
    state.search = "";
    state.metric = "all";
    state.status = "all";
    state.disagreement = false;
    state.page = 1;
    state.sort = null;
    state.expanded = null;
    setHash(null);
    syncFilters();
    renderCases();
  });
  document.querySelectorAll("[data-sort]").forEach(button => button.addEventListener("click", () => {
    const key = button.dataset.sort;
    state.direction = state.sort === key && state.direction === "ascending" ? "descending" : "ascending";
    state.sort = key;
    state.page = 1;
    state.expanded = null;
    setHash(null);
    renderCases();
  }));
  for (const [id, change] of [["prev-page", -1], ["next-page", 1]]) {
    byId(id).addEventListener("click", () => {
      state.page += change;
      state.expanded = null;
      setHash(null);
      renderCases();
      byId("cases-heading").scrollIntoView({block: "start"});
    });
  }
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && state.expanded !== null) {
      event.preventDefault();
      closeCase(true);
    }
  });
  window.addEventListener("hashchange", openHashCase);
  openHashCase();
})();
