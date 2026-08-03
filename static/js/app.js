document.body.addEventListener("htmx:afterRequest", (event) => {
  const tab = event.detail.elt;
  if (!tab.matches("[data-render-tab]")) return;

  document.querySelectorAll("[data-render-tab]").forEach((candidate) => {
    const active = candidate === tab;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-selected", active ? "true" : "false");
  });
});

document.body.addEventListener("click", async (event) => {
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
