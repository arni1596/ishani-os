from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
import sqlite3
import json
import tempfile
import re
from datetime import datetime
from pathlib import Path
from ollama import Client
import pdfplumber
from docx import Document

app = Flask(__name__)
client = Client(host="http://localhost:11434")

UPLOAD_FOLDER = Path("uploads")
UPLOAD_FOLDER.mkdir(exist_ok=True)

SOFT_DELETE_TABLES = {
    "tasks": "Dashboard",
    "memories": "Memory Vault",
    "reflections": "Pattern Check",
    "decision_history": "Decision Guide",
    "weekly_reviews": "Weekly Review",
    "chat_threads": "Workspace Threads",
    "chat_history": "Workspace Messages",
    "folders": "Workspace Folders",
}


def now_iso():
    return datetime.now().isoformat()


def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def column_exists(conn, table_name, column_name):
    if not table_exists(conn, table_name):
        return False
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def add_column_if_missing(conn, table_name, column_name, column_definition):
    if table_exists(conn, table_name) and not column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def init_db():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry TEXT NOT NULL,
            emotion TEXT NOT NULL,
            pattern TEXT NOT NULL,
            need TEXT NOT NULL,
            reality_check TEXT NOT NULL,
            next_step TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES folders (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            folder_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (folder_id) REFERENCES folders (id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS decision_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input TEXT NOT NULL,
            priority TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            questions TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS weekly_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wins TEXT NOT NULL,
            lessons TEXT NOT NULL,
            next_week TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        )
    """)

    # migrations for older databases
    add_column_if_missing(conn, "memories", "folder_id", "INTEGER")
    add_column_if_missing(conn, "chat_history", "thread_id", "INTEGER")
    add_column_if_missing(conn, "decision_history", "questions", "TEXT DEFAULT '[]'")

    for table in SOFT_DELETE_TABLES:
        add_column_if_missing(conn, table, "deleted_at", "TEXT")

    conn.commit()
    conn.close()


init_db()


def generate_thread_title(text):
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return "Untitled Thread"
    return cleaned[:60] + ("..." if len(cleaned) > 60 else "")


def save_chat_message(role, content, thread_id=None):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO chat_history (thread_id, role, content, created_at, deleted_at) VALUES (?, ?, ?, ?, NULL)",
        (thread_id, role, content, now_iso())
    )
    if thread_id is not None:
        conn.execute(
            "UPDATE chat_threads SET updated_at = ? WHERE id = ?",
            (now_iso(), thread_id)
        )
    conn.commit()
    conn.close()


def get_recent_chat_history(limit=12, thread_id=None):
    conn = get_db_connection()
    if thread_id is not None:
        rows = conn.execute("""
            SELECT role, content
            FROM chat_history
            WHERE thread_id = ? AND deleted_at IS NULL
            ORDER BY id DESC
            LIMIT ?
        """, (thread_id, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT role, content
            FROM chat_history
            WHERE deleted_at IS NULL
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    conn.close()
    rows = list(rows)[::-1]
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def create_thread(title, folder_id=None):
    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO chat_threads (title, folder_id, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, NULL)",
        (title, folder_id, now_iso(), now_iso())
    )
    thread_id = cur.lastrowid
    conn.commit()
    conn.close()
    return thread_id


def get_thread(thread_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM chat_threads WHERE id = ? AND deleted_at IS NULL",
        (thread_id,)
    ).fetchone()
    conn.close()
    return row


def get_thread_messages(thread_id):
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, role, content, created_at
        FROM chat_history
        WHERE thread_id = ? AND deleted_at IS NULL
        ORDER BY id ASC
    """, (thread_id,)).fetchall()
    conn.close()
    return rows


def analyze_entry(text):
    lowered = text.lower()
    emotion = "unclear"
    pattern = "nothing obvious yet"
    need = "more clarity"
    reality_check = "separate what happened from what you are assuming"
    next_step = "choose one small next move"

    if any(word in lowered for word in ["overwhelmed", "behind", "too much", "stressed"]):
        emotion = "overwhelmed"
        pattern = "pressure spiral"
        need = "less mental load"
        reality_check = "the issue may be overload, not failure"
        next_step = "cut the problem down and do one thing under 10 minutes"

    if any(word in lowered for word in ["angry", "mad", "annoyed", "furious"]):
        emotion = "angry"
        pattern = "reactive state"
        need = "space before responding"
        reality_check = "strong emotion does not always mean clear judgment"
        next_step = "wait before replying and write what actually upset you"

    if any(word in lowered for word in ["sad", "hurt", "alone", "rejected"]):
        emotion = "sad"
        pattern = "emotional overload"
        need = "grounding and reassurance"
        reality_check = "pain can make things feel more final than they are"
        next_step = "do one stabilizing thing before trying to solve everything"

    if any(word in lowered for word in ["always", "never", "everything", "nothing"]):
        reality_check = "your wording sounds extreme. ask what is specifically true"

    return {
        "emotion": emotion,
        "pattern": pattern,
        "need": need,
        "reality_check": reality_check,
        "next_step": next_step
    }


def get_next_best_action(tasks):
    high_tasks = [task for task in tasks if task["priority"] == "High" and task["status"] == "Not Started"]
    if high_tasks:
        return f"Start this first: {high_tasks[0]['title']}"
    medium_tasks = [task for task in tasks if task["priority"] == "Medium" and task["status"] == "Not Started"]
    if medium_tasks:
        return f"Good next move: {medium_tasks[0]['title']}"
    if tasks:
        return "Update your task statuses so the dashboard stays useful."
    return "Add one real priority when you are ready."


def get_memory_context(limit=5):
    conn = get_db_connection()
    memories = conn.execute("""
        SELECT * FROM memories
        WHERE deleted_at IS NULL
        ORDER BY id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    if not memories:
        return ""
    lines = []
    for memory in memories:
        preview = memory["content"][:220].replace("\n", " ").strip()
        lines.append(f"- {memory['title']}: {preview}")
    return "\n".join(lines)


def build_system_prompt():
    memory_context = get_memory_context()
    return (
        "You are Ishani OS, a private local workspace for clarity and follow-through. "
        "Speak clearly, directly, and practically. "
        "No fluff. No generic assistant tone. Do not describe yourself as AI. "
        "No fake demo text. No placeholder examples unless the user asks for examples. "
        "Stay in the current conversation context unless the user clearly changes topics. "
        "Follow-up questions must continue the same topic. "
        "If the user is asking about a child, tailor the response to the child's age. "
        "Keep answers clean, readable, useful, and human. "
        "Use short sections and only use bullets when actually helpful. "
        "Avoid clutter and avoid walls of text. "
        "If the user is emotional, be grounded, not cheesy.\n\n"
        f"Memory context:\n{memory_context}"
    )


def build_tool_message(tool, user_message):
    tool_prefix = ""
    if tool == "summarize":
        tool_prefix = "Summarize this clearly and simply:\n\n"
    elif tool == "plan":
        tool_prefix = "Create a practical step-by-step plan for this:\n\n"
    elif tool == "rewrite":
        tool_prefix = "Rewrite this better in a natural, clear, human way:\n\n"
    elif tool == "brainstorm":
        tool_prefix = "Brainstorm strong, useful, creative ideas for this:\n\n"
    return f"{tool_prefix}{user_message}" if tool_prefix else user_message


def parse_json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    except (TypeError, json.JSONDecodeError):
        pass
    return [value]


def serialize_weekly_review(row):
    return {
        "id": row["id"],
        "wins": parse_json_list(row["wins"]),
        "lessons": parse_json_list(row["lessons"]),
        "next_week": parse_json_list(row["next_week"]),
        "created_at": row["created_at"],
        "deleted_at": row["deleted_at"] if "deleted_at" in row.keys() else None,
    }


def serialize_folder_tree():
    conn = get_db_connection()
    folders = conn.execute("""
        SELECT id, name, parent_id, created_at
        FROM folders
        WHERE deleted_at IS NULL
        ORDER BY name COLLATE NOCASE ASC
    """).fetchall()
    threads = conn.execute("""
        SELECT id, title, folder_id, created_at, updated_at
        FROM chat_threads
        WHERE deleted_at IS NULL
        ORDER BY updated_at DESC
    """).fetchall()
    conn.close()

    folder_map = {}
    roots = []
    for folder in folders:
        folder_map[folder["id"]] = {
            "id": folder["id"],
            "name": folder["name"],
            "parent_id": folder["parent_id"],
            "children": [],
            "threads": []
        }
    for folder in folders:
        if folder["parent_id"] and folder["parent_id"] in folder_map:
            folder_map[folder["parent_id"]]["children"].append(folder_map[folder["id"]])
        else:
            roots.append(folder_map[folder["id"]])

    unfiled_threads = []
    for thread in threads:
        item = {"id": thread["id"], "title": thread["title"], "updated_at": thread["updated_at"]}
        if thread["folder_id"] and thread["folder_id"] in folder_map:
            folder_map[thread["folder_id"]]["threads"].append(item)
        else:
            unfiled_threads.append(item)

    return {"folders": roots, "unfiled_threads": unfiled_threads}


@app.route("/")
def dashboard():
    conn = get_db_connection()
    tasks = conn.execute("""
        SELECT * FROM tasks
        WHERE deleted_at IS NULL
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    next_action = get_next_best_action(tasks)
    return render_template("dashboard.html", tasks=tasks, next_action=next_action)


@app.route("/add-task", methods=["POST"])
def add_task():
    title = request.form["title"].strip()
    priority = request.form["priority"]
    if title:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO tasks (title, priority, status, deleted_at) VALUES (?, ?, ?, NULL)",
            (title, priority, "Not Started")
        )
        conn.commit()
        conn.close()
    return redirect(url_for("dashboard"))


@app.route("/update-task/<int:task_id>", methods=["POST"])
def update_task(task_id):
    title = request.form["title"].strip()
    priority = request.form["priority"]
    status = request.form["status"]
    conn = get_db_connection()
    conn.execute(
        "UPDATE tasks SET title = ?, priority = ?, status = ? WHERE id = ? AND deleted_at IS NULL",
        (title, priority, status, task_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/delete-task/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    conn = get_db_connection()
    conn.execute("UPDATE tasks SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now_iso(), task_id))
    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))


@app.route("/memory")
def memory():
    conn = get_db_connection()
    memories = conn.execute("""
        SELECT * FROM memories
        WHERE deleted_at IS NULL
        ORDER BY id DESC
    """).fetchall()
    conn.close()
    return render_template("memory.html", memories=memories)


@app.route("/add-memory", methods=["POST"])
def add_memory():
    title = request.form["title"].strip()
    content = request.form["content"].strip()
    if title and content:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO memories (title, content, created_at, deleted_at) VALUES (?, ?, ?, NULL)",
            (title, content, now_iso())
        )
        conn.commit()
        conn.close()
    return redirect(url_for("memory"))


@app.route("/delete-memory/<int:memory_id>", methods=["POST"])
def delete_memory(memory_id):
    conn = get_db_connection()
    conn.execute("UPDATE memories SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now_iso(), memory_id))
    conn.commit()
    conn.close()
    return redirect(url_for("memory"))


@app.route("/rename-memory/<int:memory_id>", methods=["POST"])
def rename_memory(memory_id):
    data = request.get_json(silent=True) or request.form
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"success": False, "error": "Title is required."}), 400
    conn = get_db_connection()
    conn.execute("UPDATE memories SET title = ? WHERE id = ? AND deleted_at IS NULL", (title, memory_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/upload-memory", methods=["POST"])
def upload_memory():
    file = request.files.get("file")
    if file and file.filename:
        try:
            text = file.read().decode("utf-8", errors="ignore")
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO memories (title, content, created_at, deleted_at) VALUES (?, ?, ?, NULL)",
                (file.filename, text[:8000], now_iso())
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
    return redirect(url_for("memory"))


@app.route("/reset")
def reset():
    conn = get_db_connection()
    reflections = conn.execute("""
        SELECT * FROM reflections
        WHERE deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 5
    """).fetchall()
    conn.close()
    return render_template("reset.html", reflections=reflections)


@app.route("/pattern-check", methods=["GET", "POST"])
def pattern_check():
    result = None
    entry = ""
    if request.method == "POST":
        entry = request.form["entry"].strip()
        if entry:
            result = analyze_entry(entry)
            conn = get_db_connection()
            conn.execute("""
                INSERT INTO reflections (entry, emotion, pattern, need, reality_check, next_step, created_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """, (
                entry, result["emotion"], result["pattern"], result["need"],
                result["reality_check"], result["next_step"], now_iso()
            ))
            conn.commit()
            conn.close()

    conn = get_db_connection()
    recent_reflections = conn.execute("""
        SELECT * FROM reflections
        WHERE deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return render_template("pattern.html", result=result, entry=entry, recent_reflections=recent_reflections)


@app.route("/delete-reflection/<int:reflection_id>", methods=["POST"])
def delete_reflection(reflection_id):
    conn = get_db_connection()
    conn.execute("UPDATE reflections SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now_iso(), reflection_id))
    conn.commit()
    conn.close()
    return redirect(url_for("pattern_check"))


DECISION_PRIORITY_WEIGHTS = {
    "stability": {
        "stable": 3,
        "stability": 3,
        "stabilize": 3,
        "stabilizing": 3,
        "reliable": 3,
        "reliability": 3,
        "secure": 2,
        "security": 2,
        "consistent": 2,
        "consistency": 2,
        "foundation": 2,
        "prepare": 2,
        "prepared": 2,
        "ready": 2,
        "quality": 2,
        "polish": 1,
        "polished": 1,
        "maintain": 2,
        "maintenance": 2,
    },
    "growth": {
        "grow": 3,
        "growth": 3,
        "expand": 3,
        "improve": 2,
        "improvement": 2,
        "build": 2,
        "building": 2,
        "feature": 2,
        "features": 2,
        "opportunity": 3,
        "learn": 2,
        "learning": 2,
        "advance": 2,
        "advancement": 2,
        "progress": 2,
        "develop": 2,
        "development": 2,
    },
    "balance": {
        "balance": 3,
        "balanced": 3,
        "stress": 3,
        "stressed": 3,
        "stressful": 3,
        "overwhelmed": 3,
        "overload": 3,
        "burnout": 3,
        "time": 1,
        "manageable": 2,
        "bandwidth": 3,
        "capacity": 3,
        "sustain": 2,
        "sustainable": 2,
        "energy": 2,
        "pressure": 2,
    },
    "timing": {
        "timing": 3,
        "deadline": 3,
        "urgent": 3,
        "urgency": 3,
        "soon": 2,
        "wait": 2,
        "later": 2,
        "now": 2,
        "schedule": 2,
        "scheduled": 2,
        "sequence": 2,
        "sequencing": 2,
        "due": 3,
        "first": 2,
        "next": 1,
    },
}

DECISION_TIE_BREAK_ORDER = {
    "timing": 0,
    "balance": 1,
    "stability": 2,
    "growth": 3,
}

DECISION_RECOMMENDATIONS = {
    "stability": "This looks like a stability decision. Focus on the option that makes the system more reliable, prepared, and easier to maintain.",
    "growth": "This looks like a growth decision. Focus on the option that creates learning, progress, or a stronger future opportunity.",
    "balance": "This looks like a balance decision. Focus on what protects your time, energy, and capacity.",
    "timing": "This looks like a timing decision. Focus on urgency, deadlines, sequence, and what needs to happen first.",
    "needs more context": "This decision needs a little more context. Add what matters most right now: stability, growth, balance, or timing.",
}


def normalize_decision_text(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def combine_decision_form_text(form):
    fields = [
        "user_input",
        "decision_title",
        "title",
        "options",
        "notes",
        "tradeoffs",
        "priority",
        "description",
    ]
    parts = []
    for field in fields:
        value = (form.get(field) or "").strip()
        if value:
            parts.append(value)
    return " ".join(parts)


def tokenize_decision_text(text):
    return re.findall(r"\b[a-z0-9']+\b", normalize_decision_text(text))


def score_decision_priorities(text):
    tokens = tokenize_decision_text(text)
    token_set = set(tokens)
    scores = {category: 0 for category in DECISION_PRIORITY_WEIGHTS}
    matched_signals = {category: [] for category in DECISION_PRIORITY_WEIGHTS}
    balance_signals_without_time = set(DECISION_PRIORITY_WEIGHTS["balance"]) - {"time"}
    has_balance_context = bool(token_set & balance_signals_without_time)

    for token in tokens:
        for category, weights in DECISION_PRIORITY_WEIGHTS.items():
            if token not in weights or token in matched_signals[category]:
                continue
            if category == "balance" and token == "time" and not has_balance_context:
                continue

            scores[category] += weights[token]
            matched_signals[category].append(token)

    return scores, matched_signals


def classify_decision_priority(text):
    scores, matched_signals = score_decision_priorities(text)
    total_score = sum(scores.values())

    if total_score == 0:
        return {
            "primary": "needs more context",
            "secondary": None,
            "confidence": "Needs more context",
            "scores": scores,
            "matched_signals": matched_signals,
        }

    ordered_priorities = sorted(
        scores,
        key=lambda category: (-scores[category], DECISION_TIE_BREAK_ORDER[category])
    )
    primary = ordered_priorities[0]
    primary_score = scores[primary]
    secondary = None

    for category in ordered_priorities[1:]:
        secondary_score = scores[category]
        if secondary_score >= 2 and secondary_score >= primary_score * 0.3:
            secondary = category
            break

    confidence_ratio = primary_score / total_score
    if confidence_ratio >= 0.70:
        confidence = "High confidence"
    elif confidence_ratio >= 0.45:
        confidence = "Medium confidence"
    else:
        confidence = "Low confidence"

    return {
        "primary": primary,
        "secondary": secondary,
        "confidence": confidence,
        "scores": scores,
        "matched_signals": matched_signals,
    }


def format_priority_label(priority):
    return priority.title() if priority != "needs more context" else "Needs more context"


def format_detected_signals(analysis):
    primary = analysis["primary"]
    secondary = analysis["secondary"]

    if primary == "needs more context":
        return DECISION_RECOMMENDATIONS[primary]

    if secondary:
        primary_signals = ", ".join(analysis["matched_signals"][primary])
        secondary_signals = ", ".join(analysis["matched_signals"][secondary])
        return (
            f"Detected signals: {format_priority_label(primary)}: {primary_signals}; "
            f"{format_priority_label(secondary)}: {secondary_signals}."
        )

    signals = ", ".join(analysis["matched_signals"][primary])
    return f"Detected signals: {signals}."


def build_decision_recommendation(analysis):
    primary = analysis["primary"]
    secondary = analysis["secondary"]

    if primary == "needs more context":
        return (
            "Primary priority: Needs more context. "
            "Confidence: Needs more context. "
            f"Recommendation: {DECISION_RECOMMENDATIONS[primary]}"
        )

    parts = [
        f"Primary priority: {format_priority_label(primary)}.",
    ]
    if secondary:
        parts.append(f"Secondary priority: {format_priority_label(secondary)}.")
    parts.extend([
        f"Confidence: {analysis['confidence']}.",
        format_detected_signals(analysis),
        f"Recommendation: {DECISION_RECOMMENDATIONS[primary]}",
    ])
    return " ".join(parts)


@app.route("/decision", methods=["GET", "POST"])
def decision():
    result = None
    user_input = ""
    conn = get_db_connection()

    if request.method == "POST":
        user_input = request.form["user_input"].strip()
        decision_text = combine_decision_form_text(request.form)
        analysis = classify_decision_priority(decision_text)
        priority = format_priority_label(analysis["primary"])

        questions = [
            "What choice supports your real priority right now?",
            "What are you protecting: stability, growth, balance, or timing?",
            "What is the biggest risk with each path?",
            "What are you already leaning toward?",
            "What choice can you actually live with six months from now?"
        ]

        recommendation = build_decision_recommendation(analysis)

        result = {"priority": priority, "questions": questions, "recommendation": recommendation}
        conn.execute("""
            INSERT INTO decision_history (user_input, priority, recommendation, questions, created_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, NULL)
        """, (user_input, priority, recommendation, json.dumps(questions), now_iso()))
        conn.commit()

    decision_history = conn.execute("""
        SELECT * FROM decision_history
        WHERE deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return render_template("decision.html", result=result, user_input=user_input, decision_history=decision_history)


@app.route("/delete-decision/<int:decision_id>", methods=["POST"])
def delete_decision(decision_id):
    conn = get_db_connection()
    conn.execute("UPDATE decision_history SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now_iso(), decision_id))
    conn.commit()
    conn.close()
    return redirect(url_for("decision"))


def build_review_data():
    conn = get_db_connection()
    tasks = conn.execute("SELECT * FROM tasks WHERE deleted_at IS NULL").fetchall()
    reflections = conn.execute("SELECT * FROM reflections WHERE deleted_at IS NULL ORDER BY id DESC").fetchall()
    conn.close()

    wins = []
    lessons = []
    next_week = []

    if tasks:
        wins.append(f"You have {len(tasks)} active task(s) in the system.")
    else:
        wins.append("You kept the command center clear enough to use.")

    if reflections:
        wins.append(f"You logged {len(reflections)} reflection entrie(s).")
        lessons.append(f"Most recent pattern: {reflections[0]['pattern']}")
    else:
        lessons.append("No reflection patterns logged yet. Notice what needs your attention this week.")

    high_open = [task["title"] for task in tasks if task["priority"] == "High" and task["status"] == "Not Started"]
    if high_open:
        lessons.append("High-priority work is still sitting open.")
        next_week.append("Finish one high-priority task earlier in the day.")
    else:
        next_week.append("Keep protecting your high-priority work first.")

    next_week.append("Use Pattern Check when a thought starts repeating.")
    next_week.append("Keep the task list short enough to protect follow-through.")
    return {"wins": wins, "lessons": lessons, "next_week": next_week}


@app.route("/review")
def review():
    review_data = build_review_data()
    conn = get_db_connection()
    review_rows = conn.execute("""
        SELECT * FROM weekly_reviews
        WHERE deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    review_history = [serialize_weekly_review(row) for row in review_rows]
    return render_template("review.html", review=review_data, review_history=review_history)


@app.route("/save-weekly-review", methods=["POST"])
def save_weekly_review():
    review_data = build_review_data()
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO weekly_reviews (wins, lessons, next_week, created_at, deleted_at)
        VALUES (?, ?, ?, ?, NULL)
    """, (
        json.dumps(review_data["wins"]),
        json.dumps(review_data["lessons"]),
        json.dumps(review_data["next_week"]),
        now_iso()
    ))
    conn.commit()
    conn.close()
    return redirect(url_for("review"))


@app.route("/delete-weekly-review/<int:review_id>", methods=["POST"])
def delete_weekly_review(review_id):
    conn = get_db_connection()
    conn.execute("UPDATE weekly_reviews SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now_iso(), review_id))
    conn.commit()
    conn.close()
    return redirect(url_for("review"))


@app.route("/ai-chat")
def ai_chat():
    return render_template("chat.html")


@app.route("/workspace")
def workspace():
    return render_template("chat.html")


@app.route("/folders-data")
def folders_data():
    return jsonify(serialize_folder_tree())


@app.route("/create-folder", methods=["POST"])
def create_folder():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    parent_id = data.get("parent_id")
    if not name:
        return jsonify({"success": False, "error": "Folder name is required."}), 400
    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO folders (name, parent_id, created_at, deleted_at) VALUES (?, ?, ?, NULL)",
        (name, parent_id, now_iso())
    )
    folder_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"success": True, "folder_id": folder_id})


@app.route("/rename-folder/<int:folder_id>", methods=["POST"])
def rename_folder(folder_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Folder name is required."}), 400
    conn = get_db_connection()
    conn.execute("UPDATE folders SET name = ? WHERE id = ? AND deleted_at IS NULL", (name, folder_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/delete-folder/<int:folder_id>", methods=["POST"])
def delete_folder(folder_id):
    conn = get_db_connection()
    child = conn.execute(
        "SELECT id FROM folders WHERE parent_id = ? AND deleted_at IS NULL LIMIT 1",
        (folder_id,)
    ).fetchone()
    if child:
        conn.close()
        return jsonify({"success": False, "error": "Move or restore subfolders first."}), 400
    conn.execute("UPDATE chat_threads SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
    conn.execute("UPDATE folders SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (now_iso(), folder_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/create-thread", methods=["POST"])
def create_thread_route():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "New Thread").strip()
    folder_id = data.get("folder_id")
    thread_id = create_thread(title=title, folder_id=folder_id)
    return jsonify({"success": True, "thread_id": thread_id})


@app.route("/thread/<int:thread_id>")
def load_thread(thread_id):
    thread = get_thread(thread_id)
    if not thread:
        return jsonify({"success": False, "error": "Thread not found."}), 404
    messages = get_thread_messages(thread_id)
    return jsonify({
        "success": True,
        "thread": {"id": thread["id"], "title": thread["title"], "folder_id": thread["folder_id"]},
        "messages": [
            {"id": row["id"], "role": row["role"], "content": row["content"], "created_at": row["created_at"]}
            for row in messages
        ]
    })


@app.route("/rename-thread/<int:thread_id>", methods=["POST"])
def rename_thread(thread_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"success": False, "error": "Title is required."}), 400
    conn = get_db_connection()
    conn.execute("UPDATE chat_threads SET title = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (title, now_iso(), thread_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/delete-thread/<int:thread_id>", methods=["POST"])
def delete_thread(thread_id):
    conn = get_db_connection()
    timestamp = now_iso()
    conn.execute("UPDATE chat_threads SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (timestamp, thread_id))
    conn.execute("UPDATE chat_history SET deleted_at = ? WHERE thread_id = ? AND deleted_at IS NULL", (timestamp, thread_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/move-thread/<int:thread_id>", methods=["POST"])
def move_thread(thread_id):
    data = request.get_json(silent=True) or {}
    folder_id = data.get("folder_id")
    conn = get_db_connection()
    conn.execute("UPDATE chat_threads SET folder_id = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (folder_id, now_iso(), thread_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/move-thread-order/<int:thread_id>/<direction>", methods=["POST"])
def move_thread_order(thread_id, direction):
    conn = get_db_connection()
    thread = conn.execute(
        "SELECT id, updated_at FROM chat_threads WHERE id = ? AND deleted_at IS NULL",
        (thread_id,)
    ).fetchone()
    if not thread:
        conn.close()
        return jsonify({"success": False, "error": "Thread not found."}), 404
    if direction == "up":
        other = conn.execute("""
            SELECT id, updated_at FROM chat_threads
            WHERE deleted_at IS NULL AND updated_at > ?
            ORDER BY updated_at ASC
            LIMIT 1
        """, (thread["updated_at"],)).fetchone()
    else:
        other = conn.execute("""
            SELECT id, updated_at FROM chat_threads
            WHERE deleted_at IS NULL AND updated_at < ?
            ORDER BY updated_at DESC
            LIMIT 1
        """, (thread["updated_at"],)).fetchone()
    if other:
        conn.execute("UPDATE chat_threads SET updated_at = ? WHERE id = ?", (other["updated_at"], thread["id"]))
        conn.execute("UPDATE chat_threads SET updated_at = ? WHERE id = ?", (thread["updated_at"], other["id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/search-memory", methods=["POST"])
def search_memory():
    data = request.get_json(silent=True) or {}
    q = (data.get("query") or "").strip().lower()
    conn = get_db_connection()
    memories = conn.execute("""
        SELECT * FROM memories
        WHERE deleted_at IS NULL
        ORDER BY id DESC
    """).fetchall()
    chats = conn.execute("""
        SELECT ch.id, ch.role, ch.content, ch.thread_id, ct.title AS thread_title
        FROM chat_history ch
        LEFT JOIN chat_threads ct ON ch.thread_id = ct.id
        WHERE ch.deleted_at IS NULL
          AND (ct.id IS NULL OR ct.deleted_at IS NULL)
        ORDER BY ch.id DESC
        LIMIT 80
    """).fetchall()
    conn.close()

    results = []
    if not q:
        for memory in memories[:6]:
            results.append({"id": memory["id"], "type": "memory", "title": memory["title"], "preview": memory["content"][:180], "full_content": memory["content"]})
        for chat in chats[:6]:
            results.append({"id": chat["id"], "type": "chat", "thread_id": chat["thread_id"], "title": chat["thread_title"] or chat["role"].capitalize(), "preview": chat["content"][:180], "full_content": chat["content"]})
        return jsonify({"results": results[:12]})

    for memory in memories:
        if q in memory["title"].lower() or q in memory["content"].lower():
            results.append({"id": memory["id"], "type": "memory", "title": memory["title"], "preview": memory["content"][:180], "full_content": memory["content"]})
    for chat in chats:
        thread_title = (chat["thread_title"] or "").lower()
        content = (chat["content"] or "").lower()
        if q in thread_title or q in content:
            results.append({"id": chat["id"], "type": "chat", "thread_id": chat["thread_id"], "title": chat["thread_title"] or chat["role"].capitalize(), "preview": chat["content"][:180], "full_content": chat["content"]})
    return jsonify({"results": results[:12]})


@app.route("/delete-chat-memory/<item_type>/<int:item_id>", methods=["POST"])
def delete_chat_memory(item_type, item_id):
    conn = get_db_connection()
    timestamp = now_iso()
    if item_type == "chat":
        conn.execute("UPDATE chat_history SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (timestamp, item_id))
    elif item_type == "memory":
        conn.execute("UPDATE memories SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (timestamp, item_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    fast_mode = bool(data.get("fast_mode", False))
    tool = (data.get("tool") or "").strip()
    thread_id = data.get("thread_id")
    folder_id = data.get("folder_id")

    if not user_message:
        return jsonify({"error": "Type something first."}), 400
    if not thread_id:
        thread_id = create_thread(title=generate_thread_title(user_message), folder_id=folder_id)
    thread = get_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found."}), 404

    final_user_message = build_tool_message(tool, user_message)
    recent_history = get_recent_chat_history(limit=10, thread_id=thread_id)
    system_prompt = build_system_prompt()
    options = {"temperature": 0.4, "top_p": 0.9, "num_predict": 220 if fast_mode else 500}

    def generate():
        full_reply = ""
        try:
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(recent_history)
            messages.append({"role": "user", "content": final_user_message})
            stream = client.chat(model="llama3", messages=messages, options=options, stream=True)
            for chunk in stream:
                token = chunk["message"]["content"]
                full_reply += token
                yield f"data: {json.dumps({'token': token, 'thread_id': thread_id, 'thread_title': thread['title']})}\n\n"
            save_chat_message("user", user_message, thread_id=thread_id)
            save_chat_message("assistant", full_reply, thread_id=thread_id)
            yield f"data: {json.dumps({'done': True, 'thread_id': thread_id, 'thread_title': thread['title']})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    return Response(generate(), mimetype="text/event-stream")


@app.route("/analyze-file", methods=["POST"])
def analyze_file():
    file = request.files.get("file")
    question = (request.form.get("question") or "").strip()
    thread_id = request.form.get("thread_id")
    folder_id = request.form.get("folder_id")

    if not file or not file.filename:
        return jsonify({"reply": "Please attach a file first."}), 400
    if thread_id:
        try:
            thread_id = int(thread_id)
        except ValueError:
            thread_id = None
    else:
        thread_id = None
    if not thread_id:
        thread_id = create_thread(title=generate_thread_title(question or f"File: {file.filename}"), folder_id=folder_id)

    filename = file.filename.lower()
    extracted_text = ""
    try:
        if filename.endswith(".txt"):
            extracted_text = file.read().decode("utf-8", errors="ignore")
        elif filename.endswith(".pdf"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                file.save(tmp.name)
                temp_path = tmp.name
            with pdfplumber.open(temp_path) as pdf:
                extracted_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
            Path(temp_path).unlink(missing_ok=True)
        elif filename.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                file.save(tmp.name)
                temp_path = tmp.name
            doc = Document(temp_path)
            extracted_text = "\n".join(p.text for p in doc.paragraphs)
            Path(temp_path).unlink(missing_ok=True)
        else:
            return jsonify({"reply": "Unsupported file type. Use PDF, DOCX, or TXT."}), 400

        if not extracted_text.strip():
            return jsonify({"reply": "I could not extract readable text from that file."}), 400

        prompt = f"""
Analyze this file in a practical and human way.

User request:
{question if question else "Summarize the file and pull out the key points."}

What to do:
- give a clear summary
- pull the most important points
- explain anything confusing simply
- keep it useful and clean

File content:
{extracted_text[:12000]}
"""
        response = client.chat(
            model="llama3",
            messages=[{"role": "system", "content": build_system_prompt()}, {"role": "user", "content": prompt}],
            options={"temperature": 0.3, "top_p": 0.9, "num_predict": 700}
        )
        reply = response["message"]["content"]
        save_chat_message("user", f"[Uploaded file: {file.filename}] {question or 'Analyze this file'}", thread_id=thread_id)
        save_chat_message("assistant", reply, thread_id=thread_id)
        return jsonify({"reply": reply, "filename": file.filename, "thread_id": thread_id})
    except Exception as e:
        return jsonify({"reply": f"There was a problem analyzing that file: {str(e)}"}), 500


@app.route("/trash")
def trash():
    conn = get_db_connection()
    deleted = []
    for table, label in SOFT_DELETE_TABLES.items():
        if table_exists(conn, table):
            rows = conn.execute(f"SELECT * FROM {table} WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()
            if table == "weekly_reviews":
                rows = [serialize_weekly_review(row) for row in rows]
            deleted.append({"table": table, "label": label, "items": rows})
    conn.close()
    return render_template("trash.html", deleted=deleted)


@app.route("/restore/<table>/<int:item_id>", methods=["POST"])
def restore_item(table, item_id):
    if table not in SOFT_DELETE_TABLES:
        return jsonify({"success": False, "error": "Invalid table."}), 400
    conn = get_db_connection()
    conn.execute(f"UPDATE {table} SET deleted_at = NULL WHERE id = ?", (item_id,))
    if table == "chat_threads":
        conn.execute("UPDATE chat_history SET deleted_at = NULL WHERE thread_id = ?", (item_id,))
    elif table == "folders":
        conn.execute("UPDATE chat_threads SET deleted_at = NULL WHERE folder_id = ?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("trash"))


if __name__ == "__main__":
    app.run(debug=True)
