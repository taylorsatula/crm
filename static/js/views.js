import {
  actionBand,
  actionButton,
  cloneTemplate,
  denseRow,
  emptyNode,
  plainRow,
  renderList,
  setHtml,
  setText,
} from "./dom.js";
import { addressLine, customerContact, customerName, dateTime, money } from "./format.js";

export function renderTodayRows(container, rows) {
  renderList(container, rows, (packet) => renderTicketPacketRow(packet, {
    action: "Open job",
    dataset: { todayJob: packet.ticket.id },
  }), "No appointments today");
}

export function renderTicketRows(container, rows) {
  renderList(container, rows, renderTicketPacketRow, "No appointments");
}

export function renderCustomerRows(container, customers) {
  renderList(container, customers, (customer) => denseRow({
    primary: customerName(customer),
    secondary: customerContact(customer),
    meta: customer.preferred_contact_method ? `preferred: ${customer.preferred_contact_method}` : "",
    action: "Open customer",
    dataset: { openCustomer: customer.id },
  }), "No customers");
}

export function renderCustomerDossier(dossier) {
  const view = cloneTemplate("template-customer-dossier");
  const customer = dossier.customer;
  setText(view, "name", customerName(customer));
  setText(view, "phone", customer.phone);
  setText(view, "email", customer.email);
  setText(view, "preferred-contact", customer.preferred_contact_method);
  setText(view, "preferred-time", customer.preferred_time_of_day);
  setHtml(view, "actions", actionBand([
    actionButton("Book appointment", { customerCommand: "book", customerId: customer.id }, true),
    actionButton("Schedule message", { customerCommand: "message", customerId: customer.id }),
    actionButton("Edit contact", { customerCommand: "edit", customerId: customer.id }),
    actionButton("Add note", { customerCommand: "note", customerId: customer.id }),
    actionButton("Add attribute", { customerCommand: "attribute", customerId: customer.id }),
    actionButton("Add address", { customerCommand: "address", customerId: customer.id }),
  ]));

  setHtml(view, "addresses", renderAddresses(dossier));
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
  setHtml(view, "customer", plainRow([
    customerName(packet.customer),
    customerContact(packet.customer),
    packet.customer.preferred_contact_method ? `Preferred: ${packet.customer.preferred_contact_method}` : "",
  ], actionBand([
    actionButton("Open customer", { openCustomer: packet.customer.id }),
  ])));
  setHtml(view, "address", plainRow([
    addressLine(packet.address),
    packet.address.notes || "",
  ]));
  setHtml(view, "scope", renderLineItems(packet));
  setHtml(view, "notes", renderTicketNotes(packet));
  setHtml(view, "messages", rowList(packet.pending_messages, renderMessageRow, "No pending messages"));
  setHtml(view, "invoice", renderInvoiceReadiness(packet));
  return view;
}

export function renderJob(packet) {
  const article = document.createElement("article");
  article.className = "detail-stack";
  article.append(
    sectionWith("Job", [
      plainRow([
        `Arrival: ${dateTime(packet.ticket.scheduled_at)}`,
        `Address: ${addressLine(packet.address)}`,
        packet.address.notes ? `Access: ${packet.address.notes}` : "",
        `Customer: ${customerName(packet.customer)} / ${customerContact(packet.customer)}`,
      ], actionBand([
        actionButton("Clock in", { ticketCommand: "clockIn", ticketId: packet.ticket.id }, true),
        actionButton("Clock out", { ticketCommand: "clockOut", ticketId: packet.ticket.id }, true),
        actionButton("Add job note", { ticketCommand: "note", ticketId: packet.ticket.id }),
        actionButton("Open ticket", { openTicket: packet.ticket.id }),
      ])),
    ]),
    sectionWith("Scope", [renderLineItems(packet)]),
    sectionWith("Notes", [renderTicketNotes(packet)])
  );
  return article;
}

export function renderCloseout(packet) {
  const article = document.createElement("article");
  article.className = "detail-stack";
  article.append(
    sectionWith("Closeout", [
      plainRow([
        `Status: ${packet.ticket.status}`,
        `Final scope: ${packet.scope_summary}`,
        `Final price: ${money(packet.total_price_cents)}`,
        packet.ticket.actual_duration_minutes ? `Actual duration: ${packet.ticket.actual_duration_minutes} minutes` : "",
      ], actionBand([
        actionButton("Close job", { ticketCommand: "close", ticketId: packet.ticket.id }, true),
        packet.line_items.length ? actionButton("Create invoice", { ticketCommand: "invoice", ticketId: packet.ticket.id }) : null,
        actionButton("Add final note", { ticketCommand: "note", ticketId: packet.ticket.id }),
        actionButton("Edit scope", { ticketCommand: "scope", ticketId: packet.ticket.id }),
        actionButton("Schedule follow-up", { ticketCommand: "followup", ticketId: packet.ticket.id }),
      ])),
    ]),
    sectionWith("Final scope", [renderLineItems(packet)]),
    sectionWith("Job notes", [renderTicketNotes(packet)]),
    sectionWith("Customer attributes", [plainRow(["Attribute processing: captured or needs review after close"])])
  );
  return article;
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

function renderAddresses(dossier) {
  const list = document.createElement("div");
  list.className = "stack-list";
  const customerId = dossier.customer.id;
  if (!dossier.addresses.length) {
    list.append(emptyNode("No addresses"));
    return list;
  }
  dossier.addresses.forEach((address) => {
    list.append(plainRow([
      addressLine(address),
      address.notes || "",
      address.is_primary ? "Primary" : "",
    ], actionBand([
      actionButton("Use for booking", {
        customerCommand: "bookAddress",
        customerId,
        addressId: address.id,
      }, true),
      actionButton("Edit", {
        customerCommand: "editAddress",
        customerId,
        addressId: address.id,
      }),
      actionButton("Remove", {
        customerCommand: "removeAddress",
        customerId,
        addressId: address.id,
      }),
    ])));
  });
  return list;
}

function ticketActions(packet) {
  const ticket = packet.ticket;
  const actions = [
    actionButton("Update appointment", { ticketCommand: "update", ticketId: ticket.id }, true),
    actionButton("Add scope", { ticketCommand: "scope", ticketId: ticket.id }),
    actionButton("Schedule confirmation", { ticketCommand: "message", ticketId: ticket.id }),
    actionButton("Open job", { ticketCommand: "job", ticketId: ticket.id }),
    actionButton("Closeout", { ticketCommand: "closeout", ticketId: ticket.id }),
    actionButton("Add note", { ticketCommand: "note", ticketId: ticket.id }),
  ];
  if (packet.line_items.length) {
    actions.push(actionButton("Create invoice", { ticketCommand: "invoice", ticketId: ticket.id }));
  }
  if (ticket.status !== "cancelled" && ticket.status !== "completed") {
    actions.push(actionButton("Cancel appointment", { ticketCommand: "cancel", ticketId: ticket.id }));
  }
  actions.push(actionButton("Delete mistaken ticket", { ticketCommand: "delete", ticketId: ticket.id }));
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
