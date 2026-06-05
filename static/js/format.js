export function money(cents) {
  if (cents === null || cents === undefined || cents === "") {
    return "None";
  }
  return `$${(Number(cents) / 100).toFixed(2)}`;
}

export function dateTime(value) {
  if (!value) {
    return "None";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function dateInputValue(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

export function dateInputToIso(value) {
  return value ? new Date(value).toISOString() : null;
}

export function nullableText(value) {
  const text = String(value || "").trim();
  return text ? text : null;
}

export function nullableNumber(value) {
  const text = String(value || "").trim();
  return text ? Number(text) : null;
}

export function customerName(customer) {
  if (!customer) {
    return "Unknown customer";
  }
  return customer.display_name || customer.business_name ||
    [customer.first_name, customer.last_name].filter(Boolean).join(" ") ||
    "Unnamed customer";
}

export function customerContact(customer) {
  if (!customer) {
    return "No contact";
  }
  return [customer.phone, customer.email].filter(Boolean).join(" / ") || "No contact";
}

export function addressLine(address) {
  if (!address) {
    return "No address";
  }
  return address.one_line || [
    address.label,
    address.street,
    address.street2,
    address.city,
    address.state,
    address.zip,
  ].filter(Boolean).join(", ");
}
