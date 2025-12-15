async function updateTicketStatus(ticketId, newStatus) { // Reusable function for status updates
                ticketId = ticketId.trim();
        
                if (!ticketId) {
                    alert("Ticket Number was NOT found. Try again.");
                    return;
                }
        
                try {
                    let response = await fetch(`/ticket/${ticketId}/update_status/${newStatus}`, {
                        method: "POST",
                        headers: { "Accept": "application/json" }
                    });
        
                    if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        
                    let data = await response.json();
                    alert(data.message);
                    location.reload();  // Refresh dashboard after updating ticket.
                } catch (error) {
                    console.error("Error:", error);
                    alert("An error occurred while updating the ticket. Please try again.");
                }
            }
        
            function closeTicket() {
                let ticketId = document.getElementById("ticketIdInput").value;
                updateTicketStatus(ticketId, "Closed");
            }