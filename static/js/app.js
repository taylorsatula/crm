import { api } from "./api.js";
import { clearPatch, emptyNode, openPatch } from "./dom.js";
import {
  addressActions,
  attributeActions,
  invoiceActions,
  lineItemActions,
  messageActions,
  noteActions,
  serviceActions,
  ticketActions,
} from "./actions.js";
import { dateTime } from "./format.js";
import { createWorkflows } from "./workflows.js";
import {
  renderCatalogRows,
  renderCloseout,
  renderCustomerDossier,
  renderCustomerRows,
  renderInvoiceDetail,
  renderInvoiceRow,
  renderJob,
  renderMessageDetail,
  renderMessageRow,
  renderServiceDetail,
  renderTicketPacket,
  renderTicketRows,
  renderTodayRows,
} from "./views.js";

const SURFACE_KEY = "crm.surface";

const state = {
  surface: localStorage.getItem(SURFACE_KEY) || "today",
  user: null,
  controller: null,
  todayRows: [],
  ticketRows: [],
  customers: [],
  services: [],
  activeCustomer: null,
  activeTicket: null,
  activeInvoice: null,
  activeMessage: null,
  activeService: null,
};

const els = {
  authScreen: document.querySelector("#auth-screen"),
  appScreen: document.querySelector("#app-screen"),
  notice: document.querySelector("#notice"),
  loginForm: document.querySelector("#login-form"),
  navButtons: Array.from(document.querySelectorAll("[data-surface-link]")),
  surfaces: Array.from(document.querySelectorAll("[data-surface]")),
  todayList: document.querySelector("#today-list"),
  todayDetail: document.querySelector("#today-detail"),
  customersList: document.querySelector("#customers-list"),
  customerDetail: document.querySelector("#customer-detail"),
  customerSearchForm: document.querySelector("#customer-search-form"),
  ticketsList: document.querySelector("#tickets-list"),
  ticketDetail: document.querySelector("#ticket-detail"),
  invoicesList: document.querySelector("#invoices-list"),
  invoiceDetail: document.querySelector("#invoice-detail"),
  messagesList: document.querySelector("#messages-list"),
  messageDetail: document.querySelector("#message-detail"),
  catalogList: document.querySelector("#catalog-list"),
  catalogDetail: document.querySelector("#catalog-detail"),
  supportDetail: document.querySelector("#support-detail"),
};

const workflows = createWorkflows({
  openPatch,
  clearPatch,
  showNotice,
  loadSurface,
  loadCatalog,
  openCustomer,
  openTicket,
  openInvoice,
  getState: () => state,
  setSurface: setActiveSurface,
});

function showNotice(message, isError) {
  if (!message) {
    els.notice.hidden = true;
    els.notice.textContent = "";
    return;
  }
  els.notice.hidden = false;
  els.notice.dataset.error = isError ? "true" : "false";
  els.notice.textContent = message;
}

function apiErrorMessage(error) {
  if (error && error.code) {
    return `${error.message || "Request failed"} (${error.code})`;
  }
  return error && error.message ? error.message : "Request failed";
}

function abortActiveRequest() {
  if (state.controller) {
    state.controller.abort();
    state.controller = null;
  }
}

function nextSignal() {
  abortActiveRequest();
  state.controller = new AbortController();
  return state.controller.signal;
}

function showAuth(message) {
  abortActiveRequest();
  state.user = null;
  els.authScreen.hidden = false;
  els.appScreen.hidden = true;
  if (message) {
    showNotice(message, true);
  }
}

function showApp() {
  els.authScreen.hidden = true;
  els.appScreen.hidden = false;
  showNotice("");
  setActiveSurface(state.surface, true);
}

async function setActiveSurface(surface, force) {
  state.surface = surface;
  localStorage.setItem(SURFACE_KEY, surface);
  els.navButtons.forEach((button) => {
    const active = button.dataset.surfaceLink === surface;
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  els.surfaces.forEach((node) => {
    node.hidden = node.dataset.surface !== surface;
  });
  clearPatch();
  await loadSurface(surface, force);
}

async function loadSurface(surface, force) {
  if (!state.user) {
    return;
  }
  if (surface === "today") {
    await loadToday(force);
  } else if (surface === "customers") {
    await loadCustomers(force);
  } else if (surface === "tickets") {
    await loadTickets(force);
  } else if (surface === "invoices") {
    await loadInvoices("unpaid");
  } else if (surface === "messages") {
    await loadMessages("due");
  } else if (surface === "catalog") {
    await loadCatalog(force);
  }
}

async function loadToday() {
  const signal = nextSignal();
  els.todayList.replaceChildren(emptyNode("Loading"));
  try {
    state.todayRows = await api.control.today({ signal });
    renderTodayRows(els.todayList, state.todayRows);
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function loadCustomers() {
  const signal = nextSignal();
  els.customersList.replaceChildren(emptyNode("Loading"));
  try {
    state.customers = await api.data("customers", { limit: 50 }, { signal });
    renderCustomerRows(els.customersList, state.customers);
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function loadTickets() {
  const signal = nextSignal();
  els.ticketsList.replaceChildren(emptyNode("Loading"));
  try {
    state.ticketRows = await api.data("tickets", { filter: "upcoming", limit: 50 }, { signal });
    renderTicketRows(els.ticketsList, state.ticketRows);
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function loadInvoices(filter) {
  const signal = nextSignal();
  els.invoicesList.replaceChildren(emptyNode("Loading"));
  try {
    const invoices = await api.data("invoices", { filter, limit: 50 }, { signal });
    renderRows(els.invoicesList, invoices, renderInvoiceRow, "No invoices");
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function loadMessages(filter) {
  const signal = nextSignal();
  els.messagesList.replaceChildren(emptyNode("Loading"));
  try {
    const messages = await api.data("messages", { filter, limit: 50 }, { signal });
    renderRows(els.messagesList, messages, renderMessageRow, "No messages");
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function loadCatalog(force, options = {}) {
  const signal = nextSignal();
  els.catalogList.replaceChildren(emptyNode("Loading"));
  try {
    state.services = await api.data("services", {}, { signal });
    renderCatalogRows(els.catalogList, state.services);
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
    if (options.rethrow) {
      throw error;
    }
  }
}

function renderRows(container, items, renderer, emptyText) {
  container.replaceChildren();
  if (!items || !items.length) {
    container.append(emptyNode(emptyText));
    return;
  }
  items.forEach((item) => container.append(renderer(item)));
}

function confirmAction({ title, hostText, bodyText, submitLabel, onConfirm }) {
  const body = document.createElement("p");
  body.textContent = bodyText;
  openPatch({
    title,
    hostText,
    body,
    submitLabel,
    onSubmit: async () => {
      try {
        await onConfirm();
        clearPatch();
      } catch (error) {
        showNotice(apiErrorMessage(error), true);
      }
    },
  });
}

async function openCustomer(customerId) {
  const signal = nextSignal();
  els.customerDetail.replaceChildren(emptyNode("Loading"));
  try {
    const dossier = await api.control.customerDossier(customerId, { signal });
    state.activeCustomer = dossier;
    els.customerDetail.replaceChildren(renderCustomerDossier(dossier));
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function openTicket(ticketId, target) {
  const signal = nextSignal();
  const container = target || els.ticketDetail;
  container.replaceChildren(emptyNode("Loading"));
  try {
    const packet = await api.control.ticketPacket(ticketId, { signal });
    state.activeTicket = packet;
    container.replaceChildren(renderTicketPacket(packet));
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function openInvoice(invoiceId) {
  const signal = nextSignal();
  els.invoiceDetail.replaceChildren(emptyNode("Loading"));
  try {
    const invoice = await api.data("invoices", { id: invoiceId }, { signal });
    state.activeInvoice = invoice;
    els.invoiceDetail.replaceChildren(renderInvoiceDetail(invoice));
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

async function openMessage(messageId) {
  const signal = nextSignal();
  els.messageDetail.replaceChildren(emptyNode("Loading"));
  try {
    const message = await api.data("messages", { id: messageId }, { signal });
    state.activeMessage = message;
    els.messageDetail.replaceChildren(renderMessageDetail(message));
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
}

function openService(serviceId) {
  const service = state.services.find((item) => item.id === serviceId);
  if (!service) {
    return;
  }
  state.activeService = service;
  els.catalogDetail.replaceChildren(renderServiceDetail(service));
}

async function renderTodayJob(ticketId) {
  const packet = await api.control.ticketPacket(ticketId);
  state.activeTicket = packet;
  els.todayDetail.replaceChildren(renderJob(packet));
}

async function runTicketCommand(command, button) {
  const ticketId = button.dataset.ticketId;
  const packet = state.activeTicket && state.activeTicket.ticket.id === ticketId
    ? state.activeTicket
    : await api.control.ticketPacket(ticketId);

  if (command === "update") {
    workflows.updateAppointment({ packet });
  } else if (command === "scope") {
    await workflows.scope({ packet });
  } else if (command === "message" || command === "followup") {
    workflows.scheduleMessage({ customer: packet.customer, ticket: packet.ticket });
  } else if (command === "job") {
    await setActiveSurface("today", false);
    els.todayDetail.replaceChildren(renderJob(packet));
  } else if (command === "closeout") {
    await setActiveSurface("tickets", false);
    els.ticketDetail.replaceChildren(renderCloseout(packet));
  } else if (command === "invoice") {
    workflows.createInvoice({ packet });
  } else if (command === "note") {
    workflows.addNote({ ownerType: "ticket", ownerId: ticketId });
  } else if (command === "removeNote") {
    confirmAction({
      title: "Remove note",
      hostText: "Ticket note",
      bodyText: "Remove this note from the ticket?",
      submitLabel: "Remove note",
      onConfirm: async () => {
        await noteActions.delete(button.dataset.noteId);
        showNotice("Note removed", false);
        await openTicket(ticketId);
      },
    });
  } else if (command === "cancel") {
    confirmAction({
      title: "Cancel appointment",
      hostText: `${packet.customer.display_name || "Customer"} - ${dateTime(packet.ticket.scheduled_at)}`,
      bodyText: "Cancel this appointment?",
      submitLabel: "Cancel appointment",
      onConfirm: async () => {
        await ticketActions.cancel(ticketId);
        showNotice("Appointment cancelled", false);
        await openTicket(ticketId);
        await loadToday(true);
        await loadTickets(true);
      },
    });
  } else if (command === "delete") {
    confirmAction({
      title: "Delete ticket",
      hostText: `${packet.customer.display_name || "Customer"} - ${dateTime(packet.ticket.scheduled_at)}`,
      bodyText: "Delete this mistaken ticket? This removes it from normal ticket lists.",
      submitLabel: "Delete ticket",
      onConfirm: async () => {
        await ticketActions.delete(ticketId);
        showNotice("Ticket deleted", false);
        els.ticketDetail.replaceChildren(emptyNode("Open a ticket."));
        await loadToday(true);
        await loadTickets(true);
      },
    });
  } else if (command === "clockIn") {
    const updated = await ticketActions.clockIn(ticketId);
    showNotice(`In progress since ${dateTime(updated.clock_in_at)}`, false);
    await renderTodayJob(ticketId);
    await loadToday(true);
  } else if (command === "clockOut") {
    const updated = await ticketActions.clockOut(ticketId);
    showNotice(`Clocked out at ${dateTime(updated.clock_out_at)}`, false);
    await renderTodayJob(ticketId);
    await loadToday(true);
  } else if (command === "close") {
    await ticketActions.close(ticketId);
    showNotice("Ticket status changed to Completed", false);
    await openTicket(ticketId);
  }
}

async function runCustomerCommand(command, button) {
  const customerId = button.dataset.customerId;
  const dossier = state.activeCustomer && state.activeCustomer.customer.id === customerId
    ? state.activeCustomer
    : await api.control.customerDossier(customerId);
  const customer = dossier.customer;

  if (command === "book") {
    const address = dossier.addresses.find((item) => item.is_primary) || dossier.addresses[0];
    if (!address) {
      workflows.address({
        customerId,
        afterSave: async ({ address: savedAddress }) => {
          await openCustomer(customerId);
          workflows.bookAppointment({ customer, address: savedAddress });
        },
      });
      return;
    }
    workflows.bookAppointment({ customer, address });
  } else if (command === "bookAddress") {
    const address = dossier.addresses.find((item) => item.id === button.dataset.addressId);
    workflows.bookAppointment({ customer, address });
  } else if (command === "edit") {
    workflows.editCustomer({ customer });
  } else if (command === "address") {
    workflows.address({ customerId });
  } else if (command === "editAddress") {
    const address = dossier.addresses.find((item) => item.id === button.dataset.addressId);
    workflows.address({ customerId, address });
  } else if (command === "message") {
    workflows.scheduleMessage({ customer });
  } else if (command === "note") {
    workflows.addNote({ ownerType: "customer", ownerId: customerId });
  } else if (command === "attribute") {
    workflows.addAttribute({ customerId });
  } else if (command === "removeAddress") {
    confirmAction({
      title: "Remove address",
      hostText: customer.display_name || "Customer",
      bodyText: "Remove this service address?",
      submitLabel: "Remove address",
      onConfirm: async () => {
        await addressActions.delete(button.dataset.addressId);
        showNotice("Address removed", false);
        await openCustomer(customerId);
      },
    });
  } else if (command === "removeAttribute") {
    confirmAction({
      title: "Remove attribute",
      hostText: customer.display_name || "Customer",
      bodyText: "Remove this customer attribute?",
      submitLabel: "Remove attribute",
      onConfirm: async () => {
        await attributeActions.delete(button.dataset.attributeId);
        showNotice("Attribute removed", false);
        await openCustomer(customerId);
      },
    });
  } else if (command === "removeNote") {
    confirmAction({
      title: "Remove note",
      hostText: customer.display_name || "Customer",
      bodyText: "Remove this customer note?",
      submitLabel: "Remove note",
      onConfirm: async () => {
        await noteActions.delete(button.dataset.noteId);
        showNotice("Note removed", false);
        await openCustomer(customerId);
      },
    });
  }
}

async function runInvoiceCommand(command, invoiceId) {
  const invoice = state.activeInvoice && state.activeInvoice.id === invoiceId
    ? state.activeInvoice
    : await api.data("invoices", { id: invoiceId });
  if (command === "send") {
    const updated = await invoiceActions.send(invoiceId);
    showNotice("Invoice sent", false);
    state.activeInvoice = updated;
    els.invoiceDetail.replaceChildren(renderInvoiceDetail(updated));
  } else if (command === "void") {
    confirmAction({
      title: "Void invoice",
      hostText: invoice.invoice_number,
      bodyText: "Void this invoice?",
      submitLabel: "Void invoice",
      onConfirm: async () => {
        const updated = await invoiceActions.void(invoiceId);
        showNotice("Invoice voided", false);
        state.activeInvoice = updated;
        els.invoiceDetail.replaceChildren(renderInvoiceDetail(updated));
      },
    });
  } else if (command === "payment") {
    workflows.recordPayment({ invoice });
  }
}

async function runMessageCommand(command, messageId) {
  if (command === "cancel") {
    confirmAction({
      title: "Cancel message",
      hostText: "Scheduled message",
      bodyText: "Cancel this scheduled message?",
      submitLabel: "Cancel message",
      onConfirm: async () => {
        await messageActions.cancel(messageId);
        showNotice("Message canceled", false);
        await loadMessages("pending");
        els.messageDetail.replaceChildren(emptyNode("Open a message."));
      },
    });
  }
}

async function runServiceCommand(command, serviceId) {
  const service = state.services.find((item) => item.id === serviceId);
  if (!service) {
    return;
  }
  if (command === "edit") {
    workflows.service({ service });
  } else if (command === "toggle") {
    await serviceActions.toggleActive(service);
    showNotice(service.is_active ? "Service deactivated" : "Service activated", false);
    await loadCatalog(true);
  } else if (command === "delete") {
    confirmAction({
      title: "Delete service",
      hostText: service.name,
      bodyText: "Delete this catalog service?",
      submitLabel: "Delete service",
      onConfirm: async () => {
        await serviceActions.delete(service.id);
        showNotice("Service deleted", false);
        els.catalogDetail.replaceChildren(emptyNode("Open a service."));
        await loadCatalog(true);
      },
    });
  }
}

async function runLineItemCommand(command, button) {
  if (command === "delete") {
    confirmAction({
      title: "Remove scope item",
      hostText: "Ticket scope",
      bodyText: "Remove this scope line item?",
      submitLabel: "Remove item",
      onConfirm: async () => {
        await lineItemActions.delete(button.dataset.lineItemId);
        showNotice("Line item removed", false);
        await openTicket(button.dataset.ticketId);
      },
    });
    return;
  }
  if (command === "edit") {
    const packet = state.activeTicket && state.activeTicket.ticket.id === button.dataset.ticketId
      ? state.activeTicket
      : await api.control.ticketPacket(button.dataset.ticketId);
    const item = packet.line_items.find((lineItem) => lineItem.id === button.dataset.lineItemId);
    await workflows.scope({ packet, item });
  }
}

async function checkHealth() {
  els.supportDetail.replaceChildren(emptyNode("Checking"));
  try {
    const result = await api.health.ready();
    renderHealth(result);
  } catch (error) {
    const data = error && error.payload && error.payload.error && error.payload.error.data;
    if (data) {
      renderHealth(data);
    }
    showNotice(apiErrorMessage(error), true);
  }
}

function renderHealth(data) {
  const section = document.createElement("section");
  section.className = "cluster detail-stack";
  const heading = document.createElement("h2");
  heading.textContent = "Health";
  section.append(heading, healthRow(`Status: ${data.status || "unknown"}`));
  Object.entries(data.checks || {}).forEach(([name, check]) => {
    section.append(healthRow([name, check.status, check.message || ""].filter(Boolean).join(" - ")));
  });
  els.supportDetail.replaceChildren(section);
}

function healthRow(text) {
  const p = document.createElement("p");
  p.textContent = text;
  return p;
}

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(els.loginForm);
  try {
    const result = await api.auth.requestLink(form.get("email"));
    showNotice(result.needs_signup ? "Signup needed" : "Link sent", false);
  } catch (error) {
    showNotice(apiErrorMessage(error), true);
  }
});

els.customerSearchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const signal = nextSignal();
  const form = new FormData(els.customerSearchForm);
  els.customersList.replaceChildren(emptyNode("Loading"));
  try {
    const customers = await api.data("customers", {
      search: form.get("search"),
      limit: 50,
    }, { signal });
    renderCustomerRows(els.customersList, customers);
  } catch (error) {
    if (error.name !== "AbortError") {
      showNotice(apiErrorMessage(error), true);
    }
  }
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) {
    return;
  }

  try {
    if (button.dataset.patchCancel !== undefined) {
      clearPatch();
      return;
    }
    if (button.dataset.surfaceLink) {
      await setActiveSurface(button.dataset.surfaceLink, false);
      return;
    }
    if (button.dataset.invoiceFilter) {
      await loadInvoices(button.dataset.invoiceFilter);
      return;
    }
    if (button.dataset.messageFilter) {
      await loadMessages(button.dataset.messageFilter);
      return;
    }
    if (button.dataset.action === "refresh") {
      await loadSurface(state.surface, true);
      return;
    }
    if (button.dataset.action === "book-appointment") {
      await setActiveSurface("customers", false);
      workflows.createCustomerThenBook();
      return;
    }
    if (button.dataset.action === "new-customer") {
      workflows.newCustomer({
        afterSave: async ({ customer }) => {
          await openCustomer(customer.id);
        },
      });
      return;
    }
    if (button.dataset.action === "new-service") {
      workflows.service({ service: null });
      return;
    }
    if (button.dataset.action === "check-health") {
      await checkHealth();
      return;
    }
    if (button.dataset.action === "logout") {
      await api.auth.logout();
      showAuth("");
      return;
    }
    if (button.dataset.openCustomer) {
      await setActiveSurface("customers", false);
      await openCustomer(button.dataset.openCustomer);
      return;
    }
    if (button.dataset.openTicket) {
      await setActiveSurface("tickets", false);
      await openTicket(button.dataset.openTicket);
      return;
    }
    if (button.dataset.openInvoice) {
      await setActiveSurface("invoices", false);
      await openInvoice(button.dataset.openInvoice);
      return;
    }
    if (button.dataset.openMessage) {
      await setActiveSurface("messages", false);
      await openMessage(button.dataset.openMessage);
      return;
    }
    if (button.dataset.openService) {
      openService(button.dataset.openService);
      return;
    }
    if (button.dataset.customerCommand) {
      await runCustomerCommand(button.dataset.customerCommand, button);
      return;
    }
    if (button.dataset.ticketCommand) {
      await runTicketCommand(button.dataset.ticketCommand, button);
      return;
    }
    if (button.dataset.lineItemCommand) {
      await runLineItemCommand(button.dataset.lineItemCommand, button);
      return;
    }
    if (button.dataset.invoiceCommand) {
      await runInvoiceCommand(button.dataset.invoiceCommand, button.dataset.invoiceId);
      return;
    }
    if (button.dataset.messageCommand) {
      await runMessageCommand(button.dataset.messageCommand, button.dataset.messageId);
      return;
    }
    if (button.dataset.serviceCommand) {
      await runServiceCommand(button.dataset.serviceCommand, button.dataset.serviceId);
    }
  } catch (error) {
    showNotice(apiErrorMessage(error), true);
  }
});

async function boot() {
  try {
    state.user = await api.auth.me();
    showApp();
  } catch (error) {
    if (error.code === "NOT_AUTHENTICATED" || error.code === "SESSION_EXPIRED") {
      try {
        state.user = await api.auth.devAutobypass();
        showApp();
      } catch (bypassError) {
        showAuth("");
        showNotice(apiErrorMessage(bypassError), true);
      }
      return;
    }
    showAuth(apiErrorMessage(error));
  }
}

boot();
