export function qs(root, selector) {
  return root.querySelector(selector);
}

export function qsa(root, selector) {
  return Array.from(root.querySelectorAll(selector));
}

export function cloneTemplate(id) {
  const template = document.querySelector(`#${id}`);
  if (!template) {
    throw new Error(`Missing template ${id}`);
  }
  return template.content.firstElementChild.cloneNode(true);
}

export function setText(root, slot, value) {
  const node = qs(root, `[data-slot="${slot}"]`);
  if (node) {
    node.textContent = value === null || value === undefined || value === "" ? "None" : String(value);
  }
}

export function setHtml(root, slot, node) {
  const target = qs(root, `[data-slot="${slot}"]`);
  if (!target) {
    return;
  }
  target.replaceChildren();
  if (node) {
    if (target.classList.contains("action-band") && node.classList.contains("action-band")) {
      target.append(...Array.from(node.childNodes));
    } else {
      target.append(node);
    }
  }
}

export function emptyNode(text) {
  const p = document.createElement("p");
  p.className = "empty-state";
  p.textContent = text;
  return p;
}

export function actionButton(label, dataset, primary = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (primary) {
    button.className = "primary-button";
  }
  Object.entries(dataset || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      button.dataset[key] = value;
    }
  });
  return button;
}

export function actionBand(buttons) {
  const band = document.createElement("div");
  band.className = "action-band";
  buttons.filter(Boolean).forEach((button) => band.append(button));
  return band;
}

export function denseRow({ primary, secondary, meta, action, dataset }) {
  const row = cloneTemplate("template-dense-row");
  setText(row, "primary", primary);
  setText(row, "secondary", secondary);
  setText(row, "meta", meta);
  setText(row, "action", action);
  Object.entries(dataset || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      row.dataset[key] = value;
    }
  });
  return row;
}

export function plainRow(parts, actions) {
  const row = cloneTemplate("template-plain-row");
  const content = qs(row, '[data-slot="content"]');
  parts.filter(Boolean).forEach((part, index) => {
    const node = document.createElement(index === 0 ? "strong" : "span");
    node.textContent = part;
    content.append(node);
  });
  if (actions) {
    setHtml(row, "actions", actions);
  }
  return row;
}

export function renderList(container, items, renderer, emptyText) {
  container.replaceChildren();
  if (!items || !items.length) {
    container.append(emptyNode(emptyText));
    return;
  }
  items.forEach((item) => container.append(renderer(item)));
}

export function clearPatch() {
  const host = document.querySelector("#patch-host");
  host.replaceChildren();
}

export function openPatch({ title, hostText, body, submitLabel, onSubmit }) {
  const host = document.querySelector("#patch-host");
  const panel = cloneTemplate("template-patch-panel");
  const form = document.createElement("form");
  form.className = "field-stack";
  form.dataset.patchForm = "true";
  let submitting = false;

  setText(panel, "title", title);
  setText(panel, "host", hostText);

  const bodyTarget = qs(panel, '[data-slot="body"]');
  if (Array.isArray(body)) {
    body.forEach((node) => form.append(node));
  } else if (body) {
    form.append(body);
  }

  const submitButton = actionButton(submitLabel || "Save", {}, true);
  const cancelButton = actionButton("Cancel", { patchCancel: "true" });
  submitButton.type = "submit";
  form.append(actionBand([
    submitButton,
    cancelButton,
  ]));
  bodyTarget.append(form);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting) {
      return;
    }
    submitting = true;
    submitButton.disabled = true;
    cancelButton.disabled = true;
    try {
      await onSubmit(form);
    } finally {
      if (form.isConnected) {
        submitting = false;
        submitButton.disabled = false;
        cancelButton.disabled = false;
      }
    }
  });

  host.replaceChildren(panel);
  const firstInput = qs(form, "input, select, textarea, button");
  if (firstInput) {
    firstInput.focus();
  }
}
