document.addEventListener("DOMContentLoaded", () => {
    initializeTheme();
    initializeThemeToggle();
    initializeMemoryRename();
});

/* ------------------------------
   Theme: load saved preference
--------------------------------*/
function initializeTheme() {
    const savedTheme = localStorage.getItem("theme");

    if (savedTheme === "light") {
        document.body.classList.remove("dark-mode");
    } else {
        document.body.classList.add("dark-mode");
    }
}

/* ------------------------------
   Theme: toggle button
--------------------------------*/
function initializeThemeToggle() {
    const toggle = document.getElementById("theme-toggle");

    if (!toggle) return;

    updateThemeToggleLabel(toggle);

    toggle.addEventListener("click", () => {
        document.body.classList.toggle("dark-mode");

        const isDark = document.body.classList.contains("dark-mode");
        localStorage.setItem("theme", isDark ? "dark" : "light");

        updateThemeToggleLabel(toggle);
    });
}

/* ------------------------------
   Update button label
--------------------------------*/
function updateThemeToggleLabel(toggle) {
    if (!toggle) return;

    const isDark = document.body.classList.contains("dark-mode");
    toggle.textContent = isDark ? "Light theme" : "Dark theme";
}

function initializeMemoryRename() {
    document.querySelectorAll(".rename-memory-btn").forEach((button) => {
        button.addEventListener("click", async () => {
            const memoryId = button.dataset.memoryId;
            const currentTitle = button.dataset.memoryTitle || "";
            const title = window.prompt("Rename memory:", currentTitle);

            if (!title || !title.trim()) return;

            try {
                const response = await fetch(`/rename-memory/${memoryId}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ title: title.trim() })
                });

                const data = await response.json();
                if (!data.success) {
                    alert(data.error || "Could not rename memory.");
                    return;
                }

                window.location.reload();
            } catch (error) {
                alert("Rename failed.");
            }
        });
    });
}
