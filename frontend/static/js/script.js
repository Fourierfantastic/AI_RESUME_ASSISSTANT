
const chatForm = document.getElementById("chat-form");
const questionInput = document.getElementById("question");
const chatMessages = document.getElementById("chat-messages");
const sendButton = document.getElementById("send-button");
const suggestions = document.querySelectorAll(".suggestion");

// Add a message to the chat window
function addMessage(text, sender) {
    const message = document.createElement("div");
    message.classList.add("message", `${sender}-message`);

    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent =
        sender === "user" ? "You" : "AI Assistant";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = text;

    message.appendChild(label);
    message.appendChild(bubble);
    chatMessages.appendChild(message);

    chatMessages.scrollTop = chatMessages.scrollHeight;

    return message;
}

// Send question to FastAPI backend
async function askAssistant(question) {
    addMessage(question, "user");

    const loadingMessage = addMessage(
        "Thinking...",
        "assistant"
    );

    sendButton.disabled = true;
    questionInput.disabled = true;

    try {
        const response = await fetch("http://127.0.0.1:8000/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                question: question
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Unable to get an answer."
            );
        }

        // Replace loading message with AI answer
        loadingMessage.querySelector(".message-bubble").textContent =
            data.answer || "No answer was returned.";

    } catch (error) {
        console.error("Chat error:", error);

        loadingMessage.querySelector(".message-bubble").textContent =
            "Sorry, I could not connect to the AI assistant. " +
            "Please check that the FastAPI backend is running.";

    } finally {
        sendButton.disabled = false;
        questionInput.disabled = false;
        questionInput.focus();
    }
}

// Handle form submission
chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const question = questionInput.value.trim();

    if (!question) {
        return;
    }

    questionInput.value = "";
    await askAssistant(question);
});

// Handle suggested questions
suggestions.forEach((button) => {
    button.addEventListener("click", async () => {
        if (sendButton.disabled) {
            return;
        }

        const question = button.dataset.question;

        if (question) {
            questionInput.value = "";
            await askAssistant(question);
        }
    });
});
