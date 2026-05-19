# Ishani OS

Ishani OS is a local-first personal operating system for self-management, reflection, memory tracking, decision support, and weekly review.

## Product Overview

Ishani OS is designed as a private command center for clarity, stability, and follow-through. It is not a generic journal app or a chatbot-first product. The app helps a user capture useful context, notice repeating patterns, work through decisions, review the week, and safely recover deleted items through a Trash and Restore system.

The project is built as a full-stack Flask application with SQLite persistence, Jinja templates, HTML, CSS, and JavaScript. It runs locally and keeps the user's data on their machine.

## Why I Built It

I built Ishani OS to explore how software can support reflection and self-management without relying on hype-driven productivity language or sending personal context to a remote service by default.

The goal was to create a calm, practical workspace where a person can:

- See active priorities clearly.
- Save memories and reference notes locally.
- Slow down recurring thoughts and identify patterns.
- Make decisions based on real priorities.
- Review the week in a structured way.
- Move items out of active view without permanently losing them.

## Current Features

### Command Center

- Add, edit, prioritize, and update task status.
- See a suggested next useful move based on active tasks.
- Move tasks to Trash instead of permanently deleting them.

### Pattern Check

- Save reflection entries with emotion, pattern, need, reality check, and next step fields.
- Review recent pattern checks.
- Move reflections to Trash and restore them later.

### Memory Vault

- Save local text memories with a title and content.
- Upload `.txt` files into memory.
- Rename saved memories.
- Search saved memories from the workspace.
- Move memories to Trash and restore them later.

### Decision Guide

- Enter a decision and receive a priority signal such as stability, growth, balance, or unclear.
- Save decision history.
- Review previous decisions.
- Move decision records to Trash and restore them later.

### Weekly Review

- Generate a weekly review from active tasks and saved reflections.
- Save weekly review snapshots.
- Review saved weekly history.
- Move weekly reviews to Trash and restore them later.

### Workspace

- Create threads and folders.
- Rename and move threads.
- Store conversation history locally in SQLite.
- Search saved memories and recent workspace messages.
- Upload and read `.txt`, `.pdf`, and `.docx` files.
- Optional local Ollama integration through a locally running model.

### Trash and Restore

- Soft-delete system using `deleted_at` timestamps.
- Deleted items are hidden from regular pages.
- Trash groups deleted items by module.
- Restore removes `deleted_at` and returns items to active views.

## Tech Stack

- Python
- Flask
- SQLite
- Jinja templates
- HTML
- CSS
- JavaScript
- Optional local Ollama integration
- `pdfplumber` for PDF text extraction
- `python-docx` for DOCX text extraction

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/ishani-os.git
cd ishani-os
```

Create and activate a virtual environment:

```powershell
python -m venv venv
venv\Scripts\activate
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

## How To Run Locally

Start the Flask app:

```powershell
python app.py
```

Open the local app:

```text
http://127.0.0.1:5000
```

The app creates or migrates the local SQLite database on startup. Existing tables are preserved, and missing columns are added safely.

## Example Workflows

### Add and Restore a Task

1. Open Command Center.
2. Add a task such as `Finish portfolio README`.
3. Set the priority to `High`.
4. Move the task to Trash.
5. Open Trash and restore it.

### Save a Memory

1. Open Memory Vault.
2. Add a title such as `Internship notes`.
3. Paste useful context into the content field.
4. Rename the memory later if the title becomes unclear.

### Run a Pattern Check

1. Open Pattern Check.
2. Write what actually happened and what your mind may be adding.
3. Save the reflection.
4. Review recent entries to notice repeating patterns.

### Work Through a Decision

1. Open Decision Guide.
2. Describe the decision and what you are protecting.
3. Review the priority signal and recommendation.
4. Save the decision to history.

### Save a Weekly Review

1. Open Weekly Review.
2. Review wins, lessons, and next-week priorities.
3. Save the weekly review snapshot.
4. Restore it from Trash if it is moved out of active view by mistake.

## Project Structure

```text
ishani-os/
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── static/
│   ├── script.js
│   └── style.css
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── memory.html
│   ├── pattern.html
│   ├── decision.html
│   ├── review.html
│   ├── reset.html
│   ├── chat.html
│   └── trash.html
└── assets/
    └── screenshots/
        └── README.md
```

Local runtime files such as `database.db`, `uploads/`, `venv/`, `.env`, and private screenshots should not be committed.

## Screenshots

Screenshots are not included yet. Suggested screenshots to add:

- Command Center
- Memory Vault
- Pattern Check
- Decision Guide
- Weekly Review
- Trash and Restore

Place public, non-private screenshots in:

```text
assets/screenshots/
```

See [assets/screenshots/README.md](assets/screenshots/README.md) for placeholder notes.

## Privacy and Local-First Note

Ishani OS is designed to run locally with SQLite. Personal data, uploaded files, and the local database should stay on the user's machine and should not be committed to GitHub.

If using the optional Ollama workflow, model responses are generated through a local Ollama server configured at:

```text
http://localhost:11434
```

## Future Improvements

- Add authentication for multi-user or deployed environments.
- Add export options for memories, reviews, and decisions.
- Add richer folder management for memories.
- Add permanent delete as a clearly separate action from Trash.
- Add automated tests for routes, migrations, and restore behavior.
- Add screenshot documentation and a short demo video.
- Make the optional local model integration configurable from settings.

## Resume-Ready Highlights

- Built a full-stack Flask and SQLite application with persistent CRUD workflows across tasks, memories, reflections, decisions, weekly reviews, folders, and workspace threads.
- Implemented a soft-delete and restore system using `deleted_at` timestamps to protect user data from accidental permanent deletion.
- Designed a local-first, privacy-conscious product architecture for personal reflection and self-management.
- Created modular Jinja templates and a polished dark command-center interface with grounded UX writing.
- Added file-reading workflows for TXT, PDF, and DOCX content.
- Structured the app as a portfolio-ready project with clear feature boundaries and practical product thinking.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
