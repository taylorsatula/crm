import {
  addressActions,
  attributeActions,
  customerActions,
  invoiceActions,
  lineItemActions,
  messageActions,
  noteActions,
  serviceActions,
  ticketActions,
} from "./actions.js";
import {
  createAddressEditor,
  createAppointmentEditor,
  createAttributeEditor,
  createCustomerContactEditor,
  createInvoiceCreateEditor,
  createMessageEditor,
  createNoteEditor,
  createPaymentEditor,
  createScopeLineItemEditor,
  createServiceEditor,
} from "./editors.js";
import { addressLine, customerName, dateInputToIso, dateInputValue, dateTime } from "./format.js";

export function createWorkflows(deps) {
  const {
    openPatch,
    clearPatch,
    showNotice,
    loadCatalog,
    openCustomer,
    openTicket,
    openInvoice,
    getState,
    setSurface,
  } = deps;

  function submit(handler) {
    return async () => {
      try {
        await handler();
      } catch (error) {
        showNotice(errorMessage(error), true);
      }
    };
  }

  return {
    newCustomer({ afterSave }) {
      const customerEditor = createCustomerContactEditor();
      const addressEditor = createAddressEditor({ primaryDefault: true });
      let createdCustomer = null;
      openPatch({
        title: "New customer",
        hostText: "Creating customer record",
        body: [
          fieldGroup("Contact", customerEditor.node),
          fieldGroup("Primary service address", addressEditor.node),
        ],
        submitLabel: "Create customer",
        onSubmit: submit(async () => {
          if (!createdCustomer) {
            createdCustomer = await customerActions.create(customerEditor.read());
            setControlsDisabled(customerEditor.node, true);
          }
          const address = await addressActions.create(createdCustomer.id, addressEditor.read());
          clearPatch();
          showNotice("Customer created", false);
          if (afterSave) {
            await afterSave({ customer: createdCustomer, address });
          }
        }),
      });
    },

    createCustomerThenBook() {
      this.newCustomer({
        afterSave: async ({ customer, address }) => {
          await openCustomer(customer.id);
          this.bookAppointment({ customer, address });
        },
      });
    },

    editCustomer({ customer }) {
      const editor = createCustomerContactEditor({ customer });
      openPatch({
        title: "Edit contact",
        hostText: customerName(customer),
        body: editor.node,
        submitLabel: "Save contact",
        onSubmit: submit(async () => {
          await customerActions.update(customer.id, editor.read());
          clearPatch();
          showNotice("Contact saved", false);
          await openCustomer(customer.id);
        }),
      });
    },

    address({ customerId, address, afterSave }) {
      const editor = createAddressEditor({ address });
      openPatch({
        title: address ? "Edit address" : "Add address",
        hostText: address ? addressLine(address) : "Service address",
        body: editor.node,
        submitLabel: "Save address",
        onSubmit: submit(async () => {
          let savedAddress;
          if (address) {
            savedAddress = await addressActions.update(address.id, editor.read());
          } else {
            savedAddress = await addressActions.create(customerId, editor.read());
          }
          clearPatch();
          showNotice("Address saved", false);
          if (afterSave) {
            await afterSave({ address: savedAddress });
          } else {
            await openCustomer(customerId);
          }
        }),
      });
    },

    bookAppointment({ customer, address }) {
      const editor = createAppointmentEditor();
      openPatch({
        title: "Book appointment",
        hostText: `${customerName(customer)} - ${addressLine(address)}`,
        body: editor.node,
        submitLabel: "Book appointment",
        onSubmit: submit(async () => {
          const ticket = await ticketActions.create({
            customerId: customer.id,
            addressId: address.id,
            appointment: editor.read(),
          });
          clearPatch();
          showNotice("Appointment booked", false);
          await setSurface("tickets", true);
          await openTicket(ticket.id);
        }),
      });
    },

    updateAppointment({ packet }) {
      const editor = createAppointmentEditor({ ticket: packet.ticket });
      openPatch({
        title: "Update appointment",
        hostText: `${customerName(packet.customer)} - ${addressLine(packet.address)}`,
        body: editor.node,
        submitLabel: "Update appointment",
        onSubmit: submit(async () => {
          await ticketActions.update(packet.ticket.id, editor.read());
          clearPatch();
          showNotice("Appointment updated", false);
          await openTicket(packet.ticket.id);
        }),
      });
    },

    async scope({ packet, item }) {
      const services = await ensureServices(loadCatalog, getState);
      const editor = createScopeLineItemEditor({ item, services });
      openPatch({
        title: item ? "Edit scope" : "Add scope",
        hostText: `${customerName(packet.customer)} - ${dateTime(packet.ticket.scheduled_at)}`,
        body: editor.node,
        submitLabel: item ? "Save scope" : "Add scope",
        onSubmit: submit(async () => {
          const { service_id: serviceId, ...payload } = editor.read();
          if (item) {
            await lineItemActions.update(item.id, payload);
          } else {
            await lineItemActions.create(packet.ticket.id, serviceId, payload);
          }
          clearPatch();
          showNotice(item ? "Scope saved" : "Scope added", false);
          await openTicket(packet.ticket.id);
        }),
      });
    },

    scheduleMessage({ customer, ticket }) {
      const editor = createMessageEditor();
      openPatch({
        title: "Schedule message",
        hostText: ticket ? `${customerName(customer)} - ${dateTime(ticket.scheduled_at)}` : customerName(customer),
        body: editor.node,
        submitLabel: "Schedule message",
        onSubmit: submit(async () => {
          const message = await messageActions.schedule({
            customer_id: customer.id,
            ticket_id: ticket ? ticket.id : null,
            ...editor.read(),
          });
          clearPatch();
          showNotice("Message scheduled", false);
          if (message.ticket_id) {
            await openTicket(message.ticket_id);
          } else {
            await openCustomer(message.customer_id);
          }
        }),
      });
    },

    addNote({ ownerType, ownerId }) {
      const editor = createNoteEditor();
      openPatch({
        title: "Add note",
        hostText: ownerType === "ticket" ? `Ticket ${ownerId}` : `Customer ${ownerId}`,
        body: editor.node,
        submitLabel: "Add note",
        onSubmit: submit(async () => {
          const { content } = editor.read();
          if (ownerType === "customer") {
            await noteActions.createForCustomer(ownerId, content);
            clearPatch();
            showNotice("Note added", false);
            await openCustomer(ownerId);
          } else {
            await noteActions.createForTicket(ownerId, content);
            clearPatch();
            showNotice("Note added", false);
            await openTicket(ownerId);
          }
        }),
      });
    },

    addAttribute({ customerId }) {
      const editor = createAttributeEditor();
      openPatch({
        title: "Add attribute",
        hostText: `Customer ${customerId}`,
        body: editor.node,
        submitLabel: "Add attribute",
        onSubmit: submit(async () => {
          await attributeActions.createManual(customerId, editor.read());
          clearPatch();
          showNotice("Attribute added", false);
          await openCustomer(customerId);
        }),
      });
    },

    createInvoice({ packet }) {
      const editor = createInvoiceCreateEditor();
      openPatch({
        title: "Create invoice",
        hostText: `${customerName(packet.customer)} - ${packet.scope_summary}`,
        body: editor.node,
        submitLabel: "Create invoice",
        onSubmit: submit(async () => {
          const invoice = await invoiceActions.createFromTicket(packet.ticket.id, editor.read());
          clearPatch();
          showNotice("Invoice created", false);
          await setSurface("invoices", true);
          await openInvoice(invoice.id);
        }),
      });
    },

    recordPayment({ invoice }) {
      const editor = createPaymentEditor({ invoice });
      openPatch({
        title: "Record payment",
        hostText: invoice.invoice_number,
        body: editor.node,
        submitLabel: "Record payment",
        onSubmit: submit(async () => {
          const updated = await invoiceActions.recordPayment(invoice.id, editor.read().amount_cents);
          clearPatch();
          showNotice("Payment recorded", false);
          await openInvoice(updated.id);
        }),
      });
    },

    service({ service }) {
      const editor = createServiceEditor({ service });
      openPatch({
        title: service ? "Edit service" : "New service",
        hostText: "Catalog setup",
        body: editor.node,
        submitLabel: "Save service",
        onSubmit: submit(async () => {
          if (service) {
            await serviceActions.update(service.id, editor.read());
            showNotice("Service updated", false);
          } else {
            await serviceActions.create(editor.read());
            showNotice("Service created", false);
          }
          clearPatch();
          await loadCatalog(true);
        }),
      });
    },

    bookNextFromTicket(packet) {
      // Pre-populate appointment from current ticket data
      const ticket = packet.ticket;
      const customer = packet.customer;
      const address = packet.address;

      // Compute suggested date: same time next week (or next business day)
      const scheduledDate = new Date(ticket.scheduled_at);
      const nextWeek = new Date(scheduledDate);
      nextWeek.setDate(nextWeek.getDate() + 7);

      const editor = createAppointmentEditor({ ticket });
      // Override scheduled_at to next week
      const scheduledAtInput = editor.node.querySelector('[name="scheduled_at"]');
      if (scheduledAtInput) {
        scheduledAtInput.value = dateInputValue(nextWeek.toISOString());
      }

      openPatch({
        title: "Book Next",
        hostText: `${customerName(customer)} - ${addressLine(address)}`,
        body: editor.node,
        submitLabel: "Book appointment",
        onSubmit: submit(async () => {
          const ticketData = await ticketActions.create({
            customerId: customer.id,
            addressId: address.id,
            appointment: editor.read(),
          });
          clearPatch();
          showNotice("Next appointment booked", false);
          await setSurface("tickets", true);
          await openTicket(ticketData.id);
        }),
      });
    },

    scheduleFollowUp(packet) {
      const ticket = packet.ticket;
      const customer = packet.customer;
      const address = packet.address;

      // Default: 11 months from now
      const defaultDate = new Date();
      defaultDate.setMonth(defaultDate.getMonth() + 11);

      const editor = createAppointmentEditor({ ticket });
      const scheduledAtInput = editor.node.querySelector('[name="scheduled_at"]');
      if (scheduledAtInput) {
        scheduledAtInput.value = dateInputValue(defaultDate.toISOString());
      }

      openPatch({
        title: "Schedule Follow-Up",
        hostText: `${customerName(customer)} - ${addressLine(address)}`,
        body: editor.node,
        submitLabel: "Schedule follow-up",
        onSubmit: submit(async () => {
          const ticketData = await ticketActions.create({
            customerId: customer.id,
            addressId: address.id,
            appointment: editor.read(),
          });
          clearPatch();
          showNotice("Follow-up scheduled", false);
          await setSurface("tickets", true);
          await openTicket(ticketData.id);
        }),
      });
    },

    doNotFollowUp(packet) {
      const customer = packet.customer;

      openPatch({
        title: "Do Not Follow-Up",
        hostText: `${customerName(customer)}`,
        body: (() => {
          const section = document.createElement("section");
          section.className = "field-stack";
          section.innerHTML = `
            <p>Record a reason for not following up with this customer. This will be saved to their file.</p>
            <label>Reason <textarea name="reason" rows="4" required></textarea></label>
          `;
          return section;
        })(),
        submitLabel: "Save & dismiss",
        onSubmit: submit(async () => {
          const reasonInput = document.querySelector('#patch-host [name="reason"]');
          const reason = reasonInput ? reasonInput.value.trim() : "";
          if (!reason) {
            showNotice("Reason is required", true);
            return;
          }

          // Persist as customer attribute
          await attributeActions.createManual(customer.id, {
            key: "do_not_follow_up",
            value: {
              reason: reason,
              noted_at: new Date().toISOString(),
            },
          });

          // Also add as a customer note for human readability
          await noteActions.createForCustomer(customer.id, `[Do Not Follow-Up] ${reason}`);

          clearPatch();
          showNotice("Do-not-follow-up recorded", false);
        }),
      });
    },
  };
}

async function ensureServices(loadCatalog, getState) {
  if (!getState().services.length) {
    await loadCatalog(true, { rethrow: true });
  }
  return getState().services;
}

function fieldGroup(title, node) {
  const fieldset = document.createElement("fieldset");
  fieldset.className = "field-stack";
  const legend = document.createElement("legend");
  legend.textContent = title;
  fieldset.append(legend, node);
  return fieldset;
}

function setControlsDisabled(root, disabled) {
  root.querySelectorAll("input, select, textarea").forEach((field) => {
    field.disabled = disabled;
  });
}

function errorMessage(error) {
  if (error && error.code) {
    return `${error.message || "Request failed"} (${error.code})`;
  }
  return error && error.message ? error.message : "Request failed";
}
