function activateRenderTab(tab) {
  document.querySelectorAll("[data-render-tab]").forEach((candidate) => {
    const active = candidate === tab;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-selected", active ? "true" : "false");
  });
}

document.body.addEventListener("click", async (event) => {
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
