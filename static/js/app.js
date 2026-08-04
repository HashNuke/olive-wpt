function activateRenderTab(tab) {
  document.querySelectorAll("[data-render-tab]").forEach((candidate) => {
    const active = candidate === tab;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-selected", active ? "true" : "false");
  });
}

function activateStatusTab(tab) {
  const status = tab.dataset.statusTab;
  const all = status === "ALL";
  const items = document.querySelectorAll("[data-status-item]");
  let visible = 0;
  document.querySelectorAll("[data-status-tab]").forEach((candidate) => {
    const active = candidate === tab;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-selected", active ? "true" : "false");
  });
  items.forEach((item) => {
    const show = all || item.dataset.statusItem === status;
    item.hidden = !show;
    if (show) visible += 1;
  });
  const summary = document.querySelector("[data-status-summary]");
  if (summary) {
    summary.textContent = all
      ? "Showing all " + visible + " tests."
      : "Showing " + visible + " " + status + " tests.";
  }
  const empty = document.querySelector("[data-status-empty]");
  if (empty) empty.hidden = visible !== 0;
}

document.body.addEventListener("click", async (event) => {
  const statusTab = event.target.closest("[data-status-tab]");
  if (statusTab) activateStatusTab(statusTab);

  const tab = event.target.closest("[data-render-tab]");
  if (tab && !tab.disabled) activateRenderTab(tab);

  const button = event.target.closest("[data-copy-path]");
  if (!button) return;

  const path = button.dataset.copyPath;
  try {
    await navigator.clipboard.writeText(path);
  } catch {
    const input = document.createElement("textarea");
    input.value = path;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  const originalLabel = button.textContent;
  button.textContent = "Copied";
  window.setTimeout(() => {
    button.textContent = originalLabel;
  }, 1500);
});
