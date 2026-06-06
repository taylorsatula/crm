import { api } from "./api.js";

export const customerActions = {
  create(payload) {
    return api.action("customer", "create", payload);
  },
  update(id, payload) {
    return api.action("customer", "update", { id, ...payload });
  },
  delete(id) {
    return api.action("customer", "delete", { id });
  },
};

export const addressActions = {
  create(customerId, payload) {
    return api.action("address", "create", { customer_id: customerId, ...payload });
  },
  update(id, payload) {
    return api.action("address", "update", { id, ...payload });
  },
  delete(id) {
    return api.action("address", "delete", { id });
  },
};

export const ticketActions = {
  create({ customerId, addressId, appointment }) {
    return api.action("ticket", "create", {
      customer_id: customerId,
      address_id: addressId,
      ...appointment,
    });
  },
  update(id, appointment) {
    return api.action("ticket", "update", { id, ...appointment });
  },
  cancel(id) {
    return api.action("ticket", "cancel", { id });
  },
  delete(id) {
    return api.action("ticket", "delete", { id });
  },
  clockIn(id) {
    return api.action("ticket", "clock_in", { id });
  },
  clockOut(id) {
    return api.action("ticket", "clock_out", { id });
  },
  close(id) {
    return api.action("ticket", "close", { id });
  },
  closeout(id, payload) {
    return api.action("ticket", "closeout", { id, ...payload });
  },
};

export const lineItemActions = {
  create(ticketId, serviceId, payload) {
    return api.action("line_item", "create", {
      ticket_id: ticketId,
      service_id: serviceId,
      ...payload,
    });
  },
  update(id, payload) {
    return api.action("line_item", "update", { id, ...payload });
  },
  delete(id) {
    return api.action("line_item", "delete", { id });
  },
};

export const invoiceActions = {
  createFromTicket(ticketId, payload) {
    return api.action("invoice", "create_from_ticket", { ticket_id: ticketId, ...payload });
  },
  send(id) {
    return api.action("invoice", "send", { id });
  },
  void(id) {
    return api.action("invoice", "void", { id });
  },
  recordPayment(id, amountCents) {
    return api.action("invoice", "record_payment", { id, amount_cents: amountCents });
  },
};

export const noteActions = {
  createForCustomer(customerId, content) {
    return api.action("note", "create", { customer_id: customerId, ticket_id: null, content });
  },
  createForTicket(ticketId, content) {
    return api.action("note", "create", { customer_id: null, ticket_id: ticketId, content });
  },
  delete(id) {
    return api.action("note", "delete", { id });
  },
};

export const attributeActions = {
  createManual(customerId, payload) {
    return api.action("attribute", "create", {
      customer_id: customerId,
      source_type: "manual",
      ...payload,
    });
  },
  delete(id) {
    return api.action("attribute", "delete", { id });
  },
};

export const messageActions = {
  schedule(payload) {
    return api.action("message", "schedule", payload);
  },
  cancel(id) {
    return api.action("message", "cancel", { id });
  },
};

export const serviceActions = {
  create(payload) {
    return api.action("catalog", "create", payload);
  },
  update(id, payload) {
    return api.action("catalog", "update", { id, ...payload });
  },
  delete(id) {
    return api.action("catalog", "delete", { id });
  },
  toggleActive(service) {
    return api.action("catalog", "update", { id: service.id, is_active: !service.is_active });
  },
};
