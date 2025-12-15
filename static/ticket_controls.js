/* Placeholder */

/* Update Ticket Status */
function updateTicketStatus(ticketId, newStatus) {
    if (!ticketId) {
        alert("Ticket Number was NOT found. Try again.");
        return;  // Proper indentation
    }

    fetch(`/ticket/${ticketId}/update_status/${newStatus}`, {  
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        alert(data.message);
        location.reload();  // Refresh page after update
    })
    .catch(error => console.error("Error:", error));
}
/* Submit Note */
async function submitNote(ticketNumber) {
    let noteContent = document.getElementById("noteContent").value.trim();
    if (!noteContent) {
        alert("Note content cannot be empty.");
        return;
    }
        
    try {
        let response = await fetch(`/ticket/${ticketNumber}/append_note`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({ note_content: noteContent }) // Ensure the key is "note_content"
        });
    
        let data = await response.json();  // Parse JSON response
        if (!response.ok) throw new Error(data.message || "Unknown error");
    
        alert(data.message);
        location.reload(); // Refresh to show the new note
    } catch (error) {
        console.error("Error:", error);
        alert("Failed to add note. Please try again.");
    }
}