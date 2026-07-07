const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const PRESETS = {
  quick: {
    crawl: false,
    gobuster: false,
    sitemap: false,
    maxPages: 50,
    depth: 3,
    crawlDelay: 0,
  },
  crawl: {
    crawl: true,
    gobuster: false,
    sitemap: true,
    maxPages: 200,
    depth: 5,
    crawlDelay: 0,
    resume: true,
    verbose: true,
  },
  full: {
    crawl: true,
    gobuster: true,
    sitemap: true,
    maxPages: 5000,
    depth: 10,
    crawlDelay: 0.5,
    wordlistExt: "html,php,asp,aspx",
    resume: true,
    verbose: true,
  },
};

function shellQuote(value) {
  if (!value) return '""';
  if (/^[A-Za-z0-9_./~-]+$/.test(value)) return value;
  return `"${value.replace(/"/g, '\\"')}"`;
}

function linesFromTextarea(id) {
  const el = $(id);
  if (!el || !el.value.trim()) return [];
  return el.value
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

function isRestoreMode() {
  return document.querySelector(".mode-tab.active")?.dataset.mode === "restore";
}

function buildCommand() {
  if (isRestoreMode()) {
    return buildRestoreCommand();
  }
  return buildSnapshotCommand();
}

function buildRestoreCommand() {
  const parts = ["snapshot", "-restore"];
  const dir = $("#outputDir").value.trim() || "./mirror";
  const port = $("#port").value;
  const host = $("#host").value.trim();
  const noOpen = $("#noOpen").checked;

  parts.push(shellQuote(dir));
  if (port && port !== "8080") parts.push("--port", port);
  if (host && host !== "127.0.0.1") parts.push("--host", shellQuote(host));
  if (noOpen) parts.push("--no-open");

  return parts.join(" ");
}

function buildSnapshotCommand() {
  const parts = ["snapshot"];
  const flags = [];

  if ($("#crawl").checked) flags.push("--crawl");
  if ($("#gobuster").checked) flags.push("--gobuster");
  if ($("#sitemap").checked) flags.push("--sitemap");
  if ($("#resume").checked) flags.push("--resume");
  if ($("#verbose").checked) flags.push("--verbose");
  if ($("#dryRun").checked) flags.push("--dry-run");
  if ($("#noAssets").checked) flags.push("--no-assets");
  if (!$("#robots").checked) flags.push("--no-robots");
  if (!$("#sameOrigin").checked) flags.push("--no-same-origin");

  const lang = $("#lang").value;
  if (lang && lang !== "html") flags.push("--lang", lang);

  const maxPages = $("#maxPages").value;
  if (maxPages && maxPages !== "50") flags.push("--max-pages", maxPages);

  const depth = $("#depth").value;
  if (depth && depth !== "3") flags.push("--depth", depth);

  const timeout = $("#timeout").value;
  if (timeout && timeout !== "15") flags.push("--timeout", timeout);

  const concurrency = $("#concurrency").value;
  if (concurrency && concurrency !== "16") flags.push("--concurrency", concurrency);

  const crawlDelay = $("#crawlDelay").value;
  if (crawlDelay && crawlDelay !== "0" && crawlDelay !== "0.0") {
    flags.push("--crawl-delay", crawlDelay);
  }

  const userAgent = $("#userAgent").value.trim();
  if (userAgent) flags.push("--user-agent", shellQuote(userAgent));

  const wordlistExt = $("#wordlistExt").value.trim();
  if (wordlistExt) flags.push("--wordlist-ext", shellQuote(wordlistExt));

  for (const cookie of linesFromTextarea("#cookies")) {
    flags.push("--cookie", shellQuote(cookie));
  }
  for (const header of linesFromTextarea("#headers")) {
    flags.push("--header", shellQuote(header));
  }
  for (const inc of linesFromTextarea("#includes")) {
    flags.push("--include", shellQuote(inc));
  }
  for (const exc of linesFromTextarea("#excludes")) {
    flags.push("--exclude", shellQuote(exc));
  }
  for (const wl of linesFromTextarea("#wordlists")) {
    flags.push("--wordlist", shellQuote(wl));
  }

  parts.push(...flags);

  let url = $("#url").value.trim();
  if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
  const out = $("#outputDir").value.trim() || "./mirror";

  parts.push(shellQuote(url || "https://example.com"));
  parts.push(shellQuote(out));

  return parts.join(" ");
}

function updateCommand() {
  const cmd = buildCommand();
  $("#command").textContent = cmd;

  const restoreHint = $("#restoreHint");
  if (isRestoreMode()) {
    restoreHint.classList.add("hidden");
  } else {
    restoreHint.classList.remove("hidden");
    const dir = $("#outputDir").value.trim() || "./mirror";
    $("#restoreCommand").textContent = `snapshot -restore ${shellQuote(dir)}`;
  }
}

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;

  $("#crawl").checked = !!p.crawl;
  $("#gobuster").checked = !!p.gobuster;
  $("#sitemap").checked = !!p.sitemap;
  $("#resume").checked = !!p.resume;
  $("#verbose").checked = !!p.verbose;
  if (p.maxPages != null) $("#maxPages").value = p.maxPages;
  if (p.depth != null) $("#depth").value = p.depth;
  if (p.crawlDelay != null) $("#crawlDelay").value = p.crawlDelay;
  if (p.wordlistExt != null) $("#wordlistExt").value = p.wordlistExt;

  setMode("snapshot");
  updateCommand();
}

function setMode(mode) {
  $$(".mode-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.mode === mode);
  });

  const snapshotOnly = $$(".snapshot-only");
  const restoreOnly = $$(".restore-only");

  snapshotOnly.forEach((el) => el.classList.toggle("hidden", mode === "restore"));
  restoreOnly.forEach((el) => el.classList.toggle("hidden", mode !== "restore"));

  updateCommand();
}

async function copyCommand() {
  const text = $("#command").textContent;
  await navigator.clipboard.writeText(text);
  const btn = $("#copyBtn");
  btn.textContent = "Copied!";
  btn.classList.add("copied");
  setTimeout(() => {
    btn.textContent = "Copy";
    btn.classList.remove("copied");
  }, 1500);
}

function init() {
  $$(".mode-tab").forEach((tab) => {
    tab.addEventListener("click", () => setMode(tab.dataset.mode));
  });

  $$(".preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyPreset(btn.dataset.preset));
  });

  $("#copyBtn").addEventListener("click", copyCommand);

  document.addEventListener("input", updateCommand);
  document.addEventListener("change", updateCommand);

  setMode("snapshot");
  updateCommand();
}

document.addEventListener("DOMContentLoaded", init);
