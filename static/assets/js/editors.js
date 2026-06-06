import { cloneTemplate, qs, setText } from "./dom.js";
import { dateInputToIso, dateInputValue, money, nullableNumber, nullableText } from "./format.js";

function field(root, name) {
  const input = qs(root, `[name="${name}"]`);
  if (!input) {
    throw new Error(`Missing editor field ${name}`);
  }
  return input;
}

function value(root, name) {
  return field(root, name).value;
}

function checked(root, name) {
  return field(root, name).checked;
}

function setValue(root, name, nextValue) {
  field(root, name).value = nextValue === null || nextValue === undefined ? "" : nextValue;
}

function setChecked(root, name, nextValue) {
  field(root, name).checked = Boolean(nextValue);
}

export function createCustomerContactEditor({ customer } = {}) {
  const node = cloneTemplate("template-customer-contact-fields");
  if (customer) {
    setValue(node, "first_name", customer.first_name);
    setValue(node, "last_name", customer.last_name);
    setValue(node, "business_name", customer.business_name);
    setValue(node, "phone", customer.phone);
    setValue(node, "email", customer.email);
    setValue(node, "preferred_contact_method", customer.preferred_contact_method);
    setValue(node, "preferred_time_of_day", customer.preferred_time_of_day);
    setValue(node, "notes", customer.notes);
  }

  return {
    node,
    read() {
      return {
        first_name: nullableText(value(node, "first_name")),
        last_name: nullableText(value(node, "last_name")),
        business_name: nullableText(value(node, "business_name")),
        phone: nullableText(value(node, "phone")),
        email: nullableText(value(node, "email")),
        notes: nullableText(value(node, "notes")),
        preferred_contact_method: nullableText(value(node, "preferred_contact_method")),
        preferred_time_of_day: nullableText(value(node, "preferred_time_of_day")),
      };
    },
  };
}

export function createAddressEditor({ address, primaryDefault = false } = {}) {
  const node = cloneTemplate("template-address-fields");
  if (address) {
    setValue(node, "label", address.label);
    setValue(node, "street", address.street);
    setValue(node, "street2", address.street2);
    setValue(node, "city", address.city);
    setValue(node, "state", address.state);
    setValue(node, "zip", address.zip);
    setValue(node, "notes", address.notes);
    setChecked(node, "is_primary", address.is_primary);
  } else {
    setChecked(node, "is_primary", primaryDefault);
  }

  return {
    node,
    read() {
      return {
        label: nullableText(value(node, "label")),
        street: String(value(node, "street") || "").trim(),
        street2: nullableText(value(node, "street2")),
        city: String(value(node, "city") || "").trim(),
        state: String(value(node, "state") || "").trim(),
        zip: String(value(node, "zip") || "").trim(),
        notes: nullableText(value(node, "notes")),
        is_primary: checked(node, "is_primary"),
      };
    },
  };
}

export function createAppointmentEditor({ ticket } = {}) {
  const node = cloneTemplate("template-appointment-fields");
  if (ticket) {
    setValue(node, "scheduled_at", dateInputValue(ticket.scheduled_at));
    setValue(node, "scheduled_duration_minutes", ticket.scheduled_duration_minutes);
    setChecked(node, "is_price_estimated", ticket.is_price_estimated);
    setValue(node, "notes", ticket.notes);
  }

  return {
    node,
    read() {
      return {
        scheduled_at: dateInputToIso(value(node, "scheduled_at")),
        scheduled_duration_minutes: nullableNumber(value(node, "scheduled_duration_minutes")),
        is_price_estimated: checked(node, "is_price_estimated"),
        notes: nullableText(value(node, "notes")),
      };
    },
  };
}

export function createScopeLineItemEditor({ item, services }) {
  const node = cloneTemplate("template-scope-line-item-fields");
  const select = field(node, "service_id");
  select.replaceChildren();

  services.filter((service) => service.is_active || (item && item.service_id === service.id)).forEach((service) => {
    const option = document.createElement("option");
    option.value = service.id;
    option.textContent = `${service.name} (${servicePriceLabel(service)})`;
    select.append(option);
  });

  function fillServicePrice() {
    const service = services.find((candidate) => candidate.id === select.value);
    if (!service) {
      return;
    }
    if (service.default_price_cents !== null && service.default_price_cents !== undefined) {
      setValue(node, "total_price_cents", service.default_price_cents);
      setValue(node, "unit_price_cents", "");
    } else if (service.unit_price_cents !== null && service.unit_price_cents !== undefined) {
      setValue(node, "unit_price_cents", service.unit_price_cents);
      const quantity = nullableNumber(value(node, "quantity")) || 1;
      setValue(node, "total_price_cents", quantity * service.unit_price_cents);
    }
  }

  select.addEventListener("change", fillServicePrice);
  field(node, "quantity").addEventListener("input", () => {
    const service = services.find((candidate) => candidate.id === select.value);
    if (service && service.unit_price_cents !== null && service.unit_price_cents !== undefined) {
      const quantity = nullableNumber(value(node, "quantity")) || 1;
      setValue(node, "total_price_cents", quantity * service.unit_price_cents);
    }
  });

  if (item) {
    setValue(node, "service_id", item.service_id);
    select.disabled = true;
    setValue(node, "description", item.description);
    setValue(node, "quantity", item.quantity || 1);
    setValue(node, "unit_price_cents", item.unit_price_cents);
    setValue(node, "total_price_cents", item.total_price_cents);
    setValue(node, "duration_minutes", item.duration_minutes);
  } else {
    fillServicePrice();
  }

  return {
    node,
    read() {
      return {
        service_id: value(node, "service_id"),
        description: nullableText(value(node, "description")),
        quantity: nullableNumber(value(node, "quantity")) || 1,
        unit_price_cents: nullableNumber(value(node, "unit_price_cents")),
        total_price_cents: nullableNumber(value(node, "total_price_cents")),
        duration_minutes: nullableNumber(value(node, "duration_minutes")),
      };
    },
  };
}

export function createServiceEditor({ service } = {}) {
  const node = cloneTemplate("template-service-fields");
  if (service) {
    setValue(node, "name", service.name);
    setValue(node, "description", service.description);
    setValue(node, "pricing_type", service.pricing_type);
    setValue(node, "default_price_cents", service.default_price_cents);
    setValue(node, "unit_price_cents", service.unit_price_cents);
    setValue(node, "unit_label", service.unit_label);
    setChecked(node, "is_active", service.is_active);
    setValue(node, "display_order", service.display_order);
  }

  return {
    node,
    read() {
      return {
        name: String(value(node, "name") || "").trim(),
        description: nullableText(value(node, "description")),
        pricing_type: value(node, "pricing_type"),
        default_price_cents: nullableNumber(value(node, "default_price_cents")),
        unit_price_cents: nullableNumber(value(node, "unit_price_cents")),
        unit_label: nullableText(value(node, "unit_label")),
        is_active: checked(node, "is_active"),
        display_order: nullableNumber(value(node, "display_order")) || 0,
      };
    },
  };
}

export function createMessageEditor({ message } = {}) {
  const node = cloneTemplate("template-message-fields");
  if (message) {
    setValue(node, "message_type", message.message_type);
    setValue(node, "scheduled_for", dateInputValue(message.scheduled_for));
    setValue(node, "subject", message.subject);
    setValue(node, "body", message.body);
  }

  return {
    node,
    read() {
      return {
        message_type: value(node, "message_type"),
        scheduled_for: dateInputToIso(value(node, "scheduled_for")),
        subject: nullableText(value(node, "subject")),
        body: nullableText(value(node, "body")),
      };
    },
  };
}

export function createNoteEditor() {
  const node = cloneTemplate("template-note-fields");
  return {
    node,
    read() {
      return {
        content: String(value(node, "content") || "").trim(),
      };
    },
  };
}

export function createAttributeEditor() {
  const node = cloneTemplate("template-attribute-fields");
  return {
    node,
    read() {
      return {
        key: String(value(node, "key") || "").trim(),
        value: String(value(node, "value") || "").trim(),
      };
    },
  };
}

export function createInvoiceCreateEditor() {
  const node = cloneTemplate("template-invoice-create-fields");
  return {
    node,
    read() {
      return {
        tax_rate_bps: nullableNumber(value(node, "tax_rate_bps")) || 0,
        notes: nullableText(value(node, "notes")),
      };
    },
  };
}

export function createPaymentEditor({ invoice }) {
  const node = cloneTemplate("template-payment-fields");
  const balance = invoice.total_amount_cents - invoice.amount_paid_cents;
  setText(node, "total", money(invoice.total_amount_cents));
  setText(node, "paid", money(invoice.amount_paid_cents));
  setText(node, "balance", money(balance));
  setValue(node, "amount_cents", balance > 0 ? balance : "");

  return {
    node,
    read() {
      return {
        amount_cents: nullableNumber(value(node, "amount_cents")),
      };
    },
  };
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
