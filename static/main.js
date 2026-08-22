/**
 * GoobyDesk - IT Helpdesk Platform
 * Consolidated JavaScript for ticket management operations created by Claude Sonnet 4.5
 */

/**
 * Updates the status of a ticket
 * @param {string} ticketId - The ID of the ticket to update
 * @param {string} newStatus - The new status to set (e.g., "Closed", "Open", "In Progress")
 * @returns {Promise<void>}
 */
async function updateTicketStatus(ticketId, newStatus) {
    // Sanitize input - remove whitespace
    ticketId = ticketId.trim();

    // Validate ticket ID exists
    if (!ticketId) {
        alert("Ticket Number was NOT found. Try again.");
        return;
    }

    try {
        // Send POST request to Flask backend to update ticket status
        let response = await fetch(`/itsm/ticket/${ticketId}/update_status/${newStatus}`, {
            method: "POST",
            headers: { "Accept": "application/json" }
        });

        // Check if request was successful
        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }

        // Parse JSON response from server
        let data = await response.json();

        // Show success message to user
        alert(data.message);

        // Refresh the page to reflect updated ticket status
        location.reload();
    } catch (error) {
        // Log error to console for debugging
        console.error("Error:", error);

        // Show user-friendly error message
        alert("An error occurred while updating the ticket. Please try again.");
    }
}

/**
 * Assigns a ticket to the currently logged-in technician
 * @param {string} ticketNumber - The ticket number to assign
 * @returns {Promise<void>}
 */
async function assignTicketToMe(ticketNumber) {
    try {
        let response = await fetch(`/itsm/ticket/${ticketNumber}/assign_to_me`, {
            method: "POST",
            headers: { "Accept": "application/json" }
        });

        let data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || "Unknown error");
        }

        alert(data.message);
        location.reload();
    } catch (error) {
        console.error("Error:", error);
        alert("An error occurred while assigning the ticket. Please try again.");
    }
}

/**
 * Assigns all selected queue tickets to the currently logged-in technician.
 * @returns {Promise<void>}
 */
async function assignSelectedTicketsToMe() {
    const selectedTickets = Array.from(document.querySelectorAll('input[name="ticket_numbers"]:checked'))
        .map((checkbox) => checkbox.value)
        .filter(Boolean);

    if (!selectedTickets.length) {
        alert("Select at least one ticket to assign.");
        return;
    }

    let assignedCount = 0;

    for (const ticketNumber of selectedTickets) {
        try {
            let response = await fetch(`/itsm/ticket/${ticketNumber}/assign_to_me`, {
                method: "POST",
                headers: { "Accept": "application/json" }
            });

            let data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || "Unknown error");
            }

            assignedCount += 1;
        } catch (error) {
            console.error("Error:", error);
        }
    }

    if (assignedCount > 0) {
        alert(`${assignedCount} ticket(s) assigned to you.`);
        location.reload();
        return;
    }

    alert("An error occurred while assigning the selected tickets. Please try again.");
}

/**
 * Closes a ticket by reading the ticket ID from the dashboard input field
 * This function is typically called from the dashboard view
 * @returns {void}
 */
function closeTicket() {
    // Get ticket ID from the input field on the dashboard
    let ticketId = document.getElementById("ticketIdInput").value;

    // Call the generic updateTicketStatus function with "Closed" status
    updateTicketStatus(ticketId, "Closed");
}

/**
 * Submits a new note/comment to an existing ticket
 * @param {string} ticketNumber - The ticket number to append the note to
 * @returns {Promise<void>}
 */
async function submitNote(ticketNumber) {
    // Get note content from textarea and remove leading/trailing whitespace
    let noteContent = document.getElementById("noteContent").value.trim();

    // Validate that note is not empty
    if (!noteContent) {
        alert("Note content cannot be empty.");
        return;
    }

    try {
        // Send POST request to Flask backend to append note
        let response = await fetch(`/itsm/ticket/${ticketNumber}/append_note`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            // Encode form data - key must match Flask's expected parameter name
            body: new URLSearchParams({ note_content: noteContent })
        });

        // Parse JSON response from server
        let data = await response.json();

        // Check if request was successful
        if (!response.ok) {
            throw new Error(data.message || "Unknown error");
        }

        // Show success message to user
        alert(data.message);

        // Refresh the page to display the newly added note
        location.reload();
    } catch (error) {
        // Log error to console for debugging
        console.error("Error:", error);

        // Show user-friendly error message
        alert("Failed to append note. Please try again.");
    }
}

/**
 * Submit a new note to a customer profile
 * @param {string} customerUuid
 */
async function submitCustomerNote(customerUuid) {
    let noteContent = document.getElementById("customer_note_content").value.trim();
    if (!noteContent) {
        alert("Note content cannot be empty.");
        return;
    }

    try {
        let response = await fetch(`/crm/customer/${customerUuid}/append_note`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({ note_content: noteContent })
        });
        let data = await response.json();
        if (!response.ok) throw new Error(data.message || "Unknown error");
        alert(data.message);
        location.reload();
    } catch (error) {
        console.error(error);
        alert("Failed to add note. Please try again.");
    }
}

/**
 * Submit a new note to an employee profile
 * @param {string} employeeUuid
 */
async function submitEmployeeNote(employeeUuid) {
    let noteContent = document.getElementById("employee_note_content").value.trim();
    if (!noteContent) {
        alert("Note content cannot be empty.");
        return;
    }

    try {
        let response = await fetch(`/hr/employee/${employeeUuid}/append_note`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({ note_content: noteContent })
        });
        let data = await response.json();
        if (!response.ok) throw new Error(data.message || "Unknown error");
        alert(data.message);
        location.reload();
    } catch (error) {
        console.error(error);
        alert("Failed to add note. Please try again.");
    }
}

/**
 * GoobyDesk - Javascript Alerts and Pop-ups
 * Auto-hides dismissible .alert banners a few seconds after they appear.
 */
setTimeout(function() {
    let alerts = document.querySelectorAll(".alert");
    alerts.forEach(alert => alert.style.display = "none");
}, 5000);  // Hides after 5 seconds

document.addEventListener("DOMContentLoaded", function() {
    const customerSelect = document.getElementById("customer_id");
    const customerUuidInput = document.getElementById("customer_uuid");

    if (!customerSelect || !customerUuidInput) {
        return;
    }

    const syncCustomerSelection = function() {
        const selectedOption = customerSelect.options[customerSelect.selectedIndex];
        const selectedUuid = selectedOption ? selectedOption.dataset.customerUuid || "" : "";
        customerUuidInput.value = selectedUuid;
    };

    customerSelect.addEventListener("change", syncCustomerSelection);
    syncCustomerSelection();
});
