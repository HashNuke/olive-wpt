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

let toastTimer;

function showToast(message, error = false, duration = 2200) {
  const toast = document.querySelector("#toast");
  if (!toast) return;
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.toggle("toast-error", error);
  toast.hidden = false;
  if (duration > 0) {
    toastTimer = window.setTimeout(() => {
      toast.hidden = true;
    }, duration);
  }
}

function actionElement(event) {
  const element = event.detail && event.detail.elt;
  return element && element.closest ? element : null;
}

function actionMessage(element) {
  const action = element && element.getAttribute("hx-post");
  if (!action) return "Review updated";
  if (action.includes("/reconcile")) return "Results reconciled";
  if (action.includes("/approve?")) return "Render approved";
  if (action.includes("/unapprove?")) return "Render unapproved";
  if (action.includes("/reject?")) return "Render rejected";
  if (action.includes("/unreject?")) return "Rejection cleared";
  return "Review updated";
}

function setActionBusy(element, busy) {
  if (!element) return;
  const button = element.matches("button")
    ? element
    : element.querySelector("button[type=submit]");
  if (!button) return;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Saving…";
  } else if (button.dataset.originalLabel) {
    button.disabled = false;
    button.textContent = button.dataset.originalLabel;
    delete button.dataset.originalLabel;
  }
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

document.body.addEventListener("htmx:beforeRequest", (event) => {
  const element = actionElement(event);
  if (!element || !element.closest("#approval-controls")) return;
  setActionBusy(element, true);
  showToast("Saving…", false, 0);
});

document.body.addEventListener("htmx:afterRequest", (event) => {
  const element = actionElement(event);
  if (!element || !element.closest("#approval-controls")) return;
  const successful = event.detail.xhr && event.detail.xhr.status >= 200 && event.detail.xhr.status < 300;
  setActionBusy(element, false);
  showToast(
    successful ? actionMessage(element) : "Could not update review",
    !successful,
  );
  const action = element.getAttribute("hx-post") || "";
  if (successful && action.includes("/reconcile")) {
    window.setTimeout(() => window.location.reload(), 700);
  }
});

document.body.addEventListener("htmx:sendError", (event) => {
  const element = actionElement(event);
  if (!element || !element.closest("#approval-controls")) return;
  setActionBusy(element, false);
  showToast("Could not reach review server", true);
});
