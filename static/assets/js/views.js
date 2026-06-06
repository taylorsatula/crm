import {
  actionBand,
  actionButton,
  cloneTemplate,
  denseRow,
  emptyNode,
  plainRow,
  qs,
  renderList,
  setHtml,
  setText,
} from "./dom.js";
import { addressLine, customerName, dateTime, makeAddressLink, makePhoneLink, money } from "./format.js";

export function renderTodayRows(container, rows) {
  renderList(container, rows, renderTicketPacketRow, "No appointments today");
}

export function renderTicketRows(container, rows) {
  renderList(container, rows, renderTicketPacketRow, "No appointments");
}

export function renderCustomerRows(container, customers, appointmentMap) {
  container.replaceChildren();
  if (!customers || !customers.length) {
    const li = document.createElement("li");
    li.className = "empty-state";
    li.textContent = "No customers";
    container.append(li);
    return;
  }
  customers.forEach((customer) => {
    const li = document.createElement("li");
    li.className = "customer-row";

    // Name column - clickable to open customer
    const nameCol = document.createElement("span");
    nameCol.className = "customer-name";
    nameCol.textContent = customerName(customer);
    nameCol.addEventListener("click", () => {
      document.dispatchEvent(new CustomEvent("open-customer", { detail: customer.id }));
    });

    // Phone column - tel: link
    const phoneCol = document.createElement("span");
    phoneCol.className = "customer-phone";
    if (customer.phone) {
      const phoneLink = document.createElement("a");
      phoneLink.href = `tel:${customer.phone.replace(/\D/g, "")}`;
      phoneLink.textContent = customer.phone;
      phoneCol.append(phoneLink);
    } else {
      phoneCol.textContent = "";
    }

    // Address column - Google Maps link
    const addrCol = document.createElement("span");
    addrCol.className = "customer-address";
    if (customer.address) {
      const addrLink = document.createElement("a");
      addrLink.href = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(customer.address)}`;
      addrLink.target = "_blank";
      addrLink.textContent = customer.address;
      addrCol.append(addrLink);
    } else {
      addrCol.textContent = "";
    }

    // Appointment date column
    const apptCol = document.createElement("span");
    apptCol.className = "customer-appt";
    if (appointmentMap && appointmentMap.has(customer.id)) {
      const apptDate = appointmentMap.get(customer.id);
      apptCol.textContent = apptDate.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    } else {
      apptCol.textContent = "—";
    }

    li.append(nameCol, phoneCol, addrCol, apptCol);
    container.append(li);
  });
}

export function renderCustomerDossier(dossier) {
  const view = cloneTemplate("template-customer-dossier");
  const customer = dossier.customer;
  setText(view, "name", customerName(customer));
  setHtml(view, "phone", customer.phone ? makePhoneLink(customer.phone) : document.createTextNode("—"));
  setHtml(view, "email", customer.email ? (() => { const a = document.createElement("a"); a.href = `mailto:${customer.email}`; a.textContent = customer.email; return a; })() : document.createTextNode("—"));
  const primaryAddr = dossier.addresses.find((a) => a.is_primary) || dossier.addresses[0];
  setHtml(view, "address", primaryAddr ? makeAddressLink(primaryAddr) : document.createTextNode("—"));
  setText(view, "preferred-contact", customer.preferred_contact_method);
  setText(view, "preferred-time", customer.preferred_time_of_day);
  setHtml(view, "actions", actionBand([
    actionButton("Book", { customerCommand: "book", customerId: customer.id }, true),
    actionButton("Message", { customerCommand: "message", customerId: customer.id }),
    actionButton("Note", { customerCommand: "note", customerId: customer.id }),
    actionButton("Edit", { customerCommand: "edit", customerId: customer.id }),
  ]));

  setHtml(view, "attributes", listFacts(
    dossier.attributes,
    (attr) => `${attr.key}: ${typeof attr.value === "object" ? JSON.stringify(attr.value) : attr.value}`,
    (attr) => actionBand([
      actionButton("Remove", {
        customerCommand: "removeAttribute",
        customerId: customer.id,
        attributeId: attr.id,
      }),
    ]),
    "No attributes"
  ));
  setHtml(view, "notes", listFacts(
    dossier.notes,
    (note) => `${dateTime(note.created_at)} - ${note.content}`,
    (note) => actionBand([
      actionButton("Remove", {
        customerCommand: "removeNote",
        customerId: customer.id,
        noteId: note.id,
      }),
    ]),
    "No notes"
  ));
  setHtml(view, "tickets", rowList(
    dossier.recent_tickets,
    (ticket) => denseRow({
      primary: `${dateTime(ticket.scheduled_at)} - ${ticket.status}`,
      secondary: ticket.notes || "No office notes",
      meta: ticket.confirmation_status,
      action: "Open ticket",
      dataset: { openTicket: ticket.id },
    }),
    "No recent tickets"
  ));
  setHtml(view, "invoices", rowList(dossier.open_invoices, renderInvoiceRow, "No open invoices"));
  setHtml(view, "messages", rowList(
    dossier.pending_messages.length ? dossier.pending_messages : dossier.messages.slice(0, 5),
    renderMessageRow,
    "No pending messages"
  ));
  return view;
}

export function renderTicketPacket(packet) {
  const view = cloneTemplate("template-ticket-packet");
  const ticket = packet.ticket;
  setText(view, "title", `${customerName(packet.customer)} - ${packet.scope_summary}`);
  setText(view, "scheduled", dateTime(ticket.scheduled_at));
  setText(view, "duration", ticket.scheduled_duration_minutes ? `${ticket.scheduled_duration_minutes} minutes` : "None");
  setText(view, "status", ticket.status);
  setText(view, "confirmation", ticket.confirmation_status);
  setText(view, "price-estimated", ticket.is_price_estimated ? "Yes" : "No");
  setText(view, "clock", packet.clock_state);
  setHtml(view, "actions", actionBand(ticketActions(packet)));
  {
    const custRow = cloneTemplate("template-plain-row");
    const custContent = qs(custRow, '[data-slot="content"]');
    custContent.append(document.createTextNode(customerName(packet.customer)));
    if (packet.customer.phone) {
      custContent.append(makePhoneLink(packet.customer.phone));
    }
    if (packet.customer.email) {
      const emailLink = document.createElement("a");
      emailLink.href = `mailto:${packet.customer.email}`;
      emailLink.textContent = packet.customer.email;
      custContent.append(emailLink);
    }
    if (packet.customer.preferred_contact_method) {
      const prefSpan = document.createElement("span");
      prefSpan.textContent = `Preferred: ${packet.customer.preferred_contact_method}`;
      custContent.append(prefSpan);
    }
    setHtml(custRow, "actions", actionBand([
      actionButton("Open customer", { openCustomer: packet.customer.id }),
    ]));
    setHtml(view, "customer", custRow);
  }
  {
    const addrRow = cloneTemplate("template-plain-row");
    const addrContent = qs(addrRow, '[data-slot="content"]');
    addrContent.append(makeAddressLink(packet.address));
    if (packet.address.notes) {
      const notesSpan = document.createElement("span");
      notesSpan.textContent = packet.address.notes;
      addrContent.append(notesSpan);
    }
    setHtml(view, "address", addrRow);
  }
  setHtml(view, "scope", renderLineItems(packet));
  setHtml(view, "notes", renderTicketNotes(packet));
  setHtml(view, "messages", rowList(packet.pending_messages, renderMessageRow, "No pending messages"));
  setHtml(view, "invoice", renderInvoiceReadiness(packet));
  return view;
}

export function renderCloseout(packet, handlers) {
  const view = cloneTemplate("template-closeout-wizard");
  const ticket = packet.ticket;

  // Pre-fill duration from actual (clocked out) or scheduled
  const defaultDuration = ticket.actual_duration_minutes || ticket.scheduled_duration_minutes || 60;

  // Step 1: Summary
  const summaryEl = qs(view, '[data-slot="summary"]');
  summaryEl.innerHTML = [
    `<strong>${customerName(packet.customer)}</strong>`,
    addressLine(packet.address),
    `Scope: ${packet.scope_summary}`,
    `Price: ${money(packet.total_price_cents)}`,
  ].filter(Boolean).join("<br>");

  // Pre-fill duration input
  const durationInput = view.querySelector('[name="confirmed_duration_minutes"]');
  durationInput.value = defaultDuration;

  // Step 1: Complete button
  const reviewActions = qs(view, '[data-slot="review-actions"]');
  const completeBtn = actionButton("Complete", {}, true);
  completeBtn.type = "button";
  reviewActions.append(actionBand([completeBtn]));

  completeBtn.addEventListener("click", async () => {
    const duration = parseInt(durationInput.value, 10);
    if (!duration || duration < 1) {
      handlers.onNotice("Duration must be at least 1 minute", true);
      return;
    }
    const finalNote = view.querySelector('[name="final_note"]').value.trim() || null;

    completeBtn.disabled = true;
    try {
      await handlers.onComplete(ticket.id, { confirmed_duration_minutes: duration, final_note: finalNote });
      const invoice = await handlers.onCreateInvoice(ticket.id);
      populatePaymentStep(view, invoice, handlers);
      qs(view, '[data-step="review"]').classList.add("closeout-step-hidden");
      qs(view, '[data-step="payment"]').classList.remove("closeout-step-hidden");
    } catch (error) {
      handlers.onNotice(`Closeout failed: ${error.message || error}`, true);
      completeBtn.disabled = false;
    }
  });

  return view;
}

function populateDisposition(view, packet, handlers) {
  const dispositionEl = qs(view, '[data-slot="disposition"]');

  // Book Next
  const bookNextBtn = actionButton("Book Next", {}, true);
  bookNextBtn.type = "button";
  bookNextBtn.addEventListener("click", () => {
    handlers.onBookNext(packet);
  });
  dispositionEl.append(bookNextBtn);

  // Schedule Follow-Up
  const followUpBtn = actionButton("Schedule Follow-Up", {}, false);
  followUpBtn.type = "button";
  followUpBtn.addEventListener("click", () => {
    handlers.onFollowUp(packet);
  });
  dispositionEl.append(followUpBtn);

  // Do Not Follow-Up
  const noFollowUpBtn = actionButton("Do Not Follow-Up", {}, false);
  noFollowUpBtn.type = "button";
  noFollowUpBtn.style.color = "#c00";
  noFollowUpBtn.addEventListener("click", () => {
    handlers.onDoNotFollowUp(packet);
  });
  dispositionEl.append(noFollowUpBtn);
}

function populatePaymentStep(view, invoice, handlers) {
  const invoiceSummary = qs(view, '[data-slot="invoice-summary"]');
  invoiceSummary.innerHTML = [
    `<strong>${invoice.invoice_number}</strong>`,
    `Total: ${money(invoice.total_amount_cents)}`,
  ].join("<br>");

  const paymentActions = qs(view, '[data-slot="payment-actions"]');
  const buttons = [
    { label: "Cash", method: "cash", recordsPayment: true },
    { label: "Check", method: "check", recordsPayment: true },
    { label: "Card", method: "card", recordsPayment: true },
    { label: "Email invoice", method: "email", recordsPayment: false },
  ];

  buttons.forEach(({ label, method, recordsPayment }) => {
    const btn = actionButton(label, {}, false);
    btn.type = "button";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        if (recordsPayment) {
          await handlers.onRecordPayment(invoice.id, invoice.total_amount_cents, method);
        } else {
          await handlers.onSendInvoice(invoice.id);
        }
        qs(view, '[data-step="payment"]').classList.add("closeout-step-hidden");
        qs(view, '[data-step="disposition"]').classList.remove("closeout-step-hidden");
        populateDisposition(view, handlers.packet, handlers);
      } catch (error) {
        handlers.onNotice(`Payment failed: ${error.message || error}`, true);
        btn.disabled = false;
      }
    });
    paymentActions.append(btn);
  });
}

export function renderInvoiceRow(invoice) {
  const balance = invoice.total_amount_cents - invoice.amount_paid_cents;
  return denseRow({
    primary: `${invoice.invoice_number} - ${invoice.status}`,
    secondary: `Total ${money(invoice.total_amount_cents)} / balance ${money(balance)}`,
    meta: invoice.sent_at ? `sent ${dateTime(invoice.sent_at)}` : `created ${dateTime(invoice.created_at)}`,
    action: "Open invoice",
    dataset: { openInvoice: invoice.id },
  });
}

export function renderInvoiceDetail(invoice) {
  const detail = document.createElement("article");
  detail.className = "detail-stack";
  detail.append(
    renderMoneyCluster(invoice),
    sectionWith("Linked work", [
      plainRow([
        "Linked appointment",
        "Linked customer",
        invoice.notes || "",
      ], actionBand([
        actionButton("Open ticket", { openTicket: invoice.ticket_id }),
        actionButton("Open customer", { openCustomer: invoice.customer_id }),
      ])),
    ])
  );
  return detail;
}

export function renderMessageRow(message) {
  const linked = message.ticket_id ? `ticket ${message.ticket_id}` : `customer ${message.customer_id}`;
  return denseRow({
    primary: `${message.message_type} - ${message.status}`,
    secondary: message.subject || message.body || linked,
    meta: dateTime(message.scheduled_for),
    action: "Open message",
    dataset: { openMessage: message.id },
  });
}

export function renderMessageDetail(message) {
  const view = cloneTemplate("template-message-cluster");
  setText(view, "type", message.message_type);
  setText(view, "recipient", message.customer_id);
  setText(view, "linked", message.ticket_id ? `Ticket ${message.ticket_id}` : `Customer ${message.customer_id}`);
  setText(view, "scheduled", dateTime(message.scheduled_for));
  setText(view, "status", message.status);
  setText(view, "preview", [message.subject, message.body].filter(Boolean).join(" - "));
  const actions = [];
  if (message.status === "pending") {
    actions.push(actionButton("Cancel message", { messageCommand: "cancel", messageId: message.id }, true));
  }
  if (message.ticket_id) {
    actions.push(actionButton("Open ticket", { openTicket: message.ticket_id }));
  }
  actions.push(actionButton("Open customer", { openCustomer: message.customer_id }));
  setHtml(view, "actions", actionBand(actions));
  return view;
}

export function renderCatalogRows(container, services) {
  renderList(container, services, (service) => denseRow({
    primary: service.name,
    secondary: servicePriceLabel(service),
    meta: `${service.pricing_type} / ${service.is_active ? "active" : "inactive"} / order ${service.display_order}`,
    action: "Open service",
    dataset: { openService: service.id },
  }), "No services");
}

export function renderServiceDetail(service) {
  const row = cloneTemplate("template-service-row");
  setText(row, "name", service.name);
  setText(row, "pricing", servicePriceLabel(service));
  setText(row, "state", service.is_active ? "Active" : "Inactive");
  setText(row, "order", `Order ${service.display_order}`);
  setHtml(row, "actions", actionBand([
    actionButton("Edit service", { serviceCommand: "edit", serviceId: service.id }, true),
    actionButton(service.is_active ? "Deactivate" : "Activate", { serviceCommand: "toggle", serviceId: service.id }),
    actionButton("Delete service", { serviceCommand: "delete", serviceId: service.id }),
  ]));
  return row;
}

function renderTicketPacketRow(packet, options = {}) {
  const ticket = packet.ticket;
  const meta = [
    ticket.status,
    ticket.confirmation_status !== "confirmed" ? `confirmation: ${ticket.confirmation_status}` : "",
    packet.clock_state === "in_progress" ? "clocked in" : "",
    packet.pending_message_count ? `${packet.pending_message_count} pending messages` : "",
  ].filter(Boolean).join(" / ");
  return denseRow({
    primary: `${dateTime(ticket.scheduled_at)} - ${customerName(packet.customer)}`,
    secondary: `${addressLine(packet.address)} - ${packet.scope_summary}`,
    meta,
    action: options.action || "Open ticket",
    dataset: options.dataset || { openTicket: ticket.id },
  });
}

function ticketActions(packet) {
  const ticket = packet.ticket;
  const actions = [
    actionButton("Edit", { ticketCommand: "edit", ticketId: ticket.id }, true),
  ];
  if (packet.clock_state === "in_progress") {
    actions.push(actionButton("Clock out", { ticketCommand: "clockOut", ticketId: ticket.id }, true));
  } else if (ticket.status !== "cancelled" && ticket.status !== "completed") {
    actions.push(actionButton("Clock in", { ticketCommand: "clockIn", ticketId: ticket.id }, true));
  }
  return actions;
}

function renderLineItems(packet) {
  const list = document.createElement("div");
  list.className = "stack-list";
  if (!packet.line_items.length) {
    list.append(emptyNode("No line items"));
    return list;
  }
  packet.line_items.forEach((item) => {
    const row = cloneTemplate("template-line-item-row");
    setText(row, "description", item.description || item.service_name);
    setText(row, "quantity", `Qty ${item.quantity}`);
    setText(row, "price", money(item.total_price_cents));
    setHtml(row, "actions", actionBand([
      actionButton("Edit", {
        lineItemCommand: "edit",
        lineItemId: item.id,
        ticketId: packet.ticket.id,
      }),
      actionButton("Remove", {
        lineItemCommand: "delete",
        lineItemId: item.id,
        ticketId: packet.ticket.id,
      }),
    ]));
    list.append(row);
  });
  return list;
}

function renderTicketNotes(packet) {
  const list = document.createElement("div");
  list.className = "stack-list";
  if (packet.job_notes) {
    list.append(plainRow([`Office notes: ${packet.job_notes}`]));
  }
  if (packet.notes.length) {
    packet.notes.forEach((note) => list.append(plainRow([
      `${dateTime(note.created_at)} - ${note.content}`,
    ], actionBand([
      actionButton("Remove", {
        ticketCommand: "removeNote",
        ticketId: packet.ticket.id,
        noteId: note.id,
      }),
    ]))));
  }
  if (!packet.job_notes && !packet.notes.length) {
    list.append(emptyNode("No notes"));
  }
  return list;
}

function renderInvoiceReadiness(packet) {
  if (packet.invoice_summary) {
    return renderMoneyCluster(packet.invoice_summary);
  }
  return plainRow([
    packet.line_items.length ? "No invoice yet" : "Add scope before invoicing",
    packet.line_items.length ? `Ready total ${money(packet.total_price_cents)}` : "",
  ], packet.line_items.length ? actionBand([
    actionButton("Create invoice", { ticketCommand: "invoice", ticketId: packet.ticket.id }, true),
  ]) : null);
}

function renderMoneyCluster(invoice) {
  const view = cloneTemplate("template-money-cluster");
  const balance = invoice.total_amount_cents - invoice.amount_paid_cents;
  setText(view, "invoice-number", invoice.invoice_number || "Invoice");
  setText(view, "status", invoice.status);
  setText(view, "subtotal", money(invoice.subtotal_cents));
  setText(view, "tax", money(invoice.tax_amount_cents));
  setText(view, "total", money(invoice.total_amount_cents));
  setText(view, "paid", money(invoice.amount_paid_cents));
  setText(view, "balance", money(balance));
  setHtml(view, "actions", actionBand(invoiceActionButtons(invoice)));
  return view;
}

function invoiceActionButtons(invoice) {
  const actions = [];
  if (invoice.status === "draft") {
    actions.push(actionButton("Send invoice", { invoiceCommand: "send", invoiceId: invoice.id }, true));
  }
  if (invoice.status === "sent" || invoice.status === "partial") {
    actions.push(actionButton("Record payment", { invoiceCommand: "payment", invoiceId: invoice.id }, true));
  }
  if (invoice.status !== "paid" && invoice.status !== "void") {
    actions.push(actionButton("Void invoice", { invoiceCommand: "void", invoiceId: invoice.id }));
  }
  actions.push(actionButton("Open ticket", { openTicket: invoice.ticket_id }));
  actions.push(actionButton("Open customer", { openCustomer: invoice.customer_id }));
  return actions;
}

function listFacts(items, labeler, actioner, emptyText) {
  const list = document.createElement("div");
  list.className = "stack-list";
  if (!items || !items.length) {
    list.append(emptyNode(emptyText));
    return list;
  }
  items.forEach((item) => list.append(plainRow([labeler(item)], actioner ? actioner(item) : null)));
  return list;
}

function rowList(items, renderer, emptyText) {
  const list = document.createElement("div");
  list.className = "dense-list";
  if (!items || !items.length) {
    list.append(emptyNode(emptyText));
    return list;
  }
  items.forEach((item) => list.append(renderer(item)));
  return list;
}

function sectionWith(title, children) {
  const section = document.createElement("section");
  section.className = "cluster";
  const heading = document.createElement("h2");
  heading.textContent = title;
  section.append(heading);
  children.filter(Boolean).forEach((child) => section.append(child));
  return section;
}

function servicePriceLabel(service) {
  if (service.pricing_type === "fixed") {
    return `Fixed ${money(service.default_price_cents)}`;
  }
  if (service.pricing_type === "per_unit") {
    return `${money(service.unit_price_cents)} per ${service.unit_label || "unit"}`;
  }
  return "Flexible price";
}
