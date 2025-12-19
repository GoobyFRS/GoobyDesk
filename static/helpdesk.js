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
        let response = await fetch(`/ticket/${ticketId}/update_status/${newStatus}`, {
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
        let response = await fetch(`/ticket/${ticketNumber}/append_note`, {
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
        alert("Failed to add note. Please try again.");
    }
}