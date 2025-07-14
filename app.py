from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3

from helpers import login_required

app = Flask(__name__)

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

def get_db():
    conn = sqlite3.connect("kwizzKreate.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def home():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, title FROM quizes WHERE user_id = ?", (user_id,))
    quizzes = cursor.fetchall()
    db.close()

    return render_template("home.html", quizzes=quizzes)


@app.route("/example", methods=["GET", "POST"])
def example():
    if request.method == "POST":
        return redirect("/") 
    else:
        return render_template("example.html")


@app.route("/new_kwizz", methods=["GET", "POST"])
@login_required
def new_kwizz():
    if request.method == "POST":
        questions = int(request.form.get("questions"))
        return render_template("new_kwizz.html", questions=questions)
    else:
        return render_template("index.html")


@app.route("/create", methods=["POST"])
@login_required
def create():
    print("Form received:", dict(request.form))  # DEBUG

    quiz_name = request.form.get("quiz_name")
    user_id = session.get("user_id")

    if not quiz_name or not user_id:
        return render_template("error.html", message="Missing quiz name or user session.")

    questions = []
    i = 1
    while True:
        q = request.form.get(f'question{i}')
        a = request.form.get(f'A{i}')
        b = request.form.get(f'B{i}')
        c = request.form.get(f'C{i}')
        d = request.form.get(f'D{i}')
        correct = request.form.get(f'correct_option{i}')

        if not q:
            break  # End of questions

        print(f"Processing question {i}: correct = '{correct}'")  # DEBUG

        if not all([a, b, c, d, correct]):
            return render_template("error.html", message=f"Incomplete data for question {i}.")

        correct = correct.strip().upper()
        if correct not in ['A', 'B', 'C', 'D']:
            return render_template("error.html", message=f"Invalid correct option '{correct}' for question {i}.")

        questions.append({
            "question": q,
            "A": a,
            "B": b,
            "C": c,
            "D": d,
            "correct": correct
        })

        i += 1

    if not questions:
        return render_template("error.html", message="No questions submitted.")

    db = get_db()
    cursor = db.cursor()

    cursor.execute("INSERT INTO quizes (user_id, title) VALUES (?, ?)", (user_id, quiz_name))
    quiz_id = cursor.lastrowid

    for q in questions:
        cursor.execute("""
            INSERT INTO questions 
            (quiz_id, question, option_a, option_b, option_c, option_d, correct_option) 
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (quiz_id, q["question"], q["A"], q["B"], q["C"], q["D"], q["correct"])
        )

    db.commit()
    db.close()

    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            return render_template("error.html", message="Missing username or password.")

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        db.close()

        if user is None or not check_password_hash(user["hash"], password):
            return render_template("error.html", message="Invalid username or password.")

        session["user_id"] = user["id"]
        return redirect("/")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not password or not confirmation:
            return render_template("error.html", message="All fields required.")

        if password != confirmation:
            return render_template("error.html", message="Passwords do not match.")

        db = get_db()
        cursor = db.cursor()

        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        if cursor.fetchone() is not None:
            db.close()
            return render_template("error.html", message="Username already taken.")

        hash_pw = generate_password_hash(password)
        cursor.execute("INSERT INTO users (username, hash) VALUES (?, ?)", (username, hash_pw))
        db.commit()

        # Log in new user
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        session["user_id"] = user["id"]
        db.close()

        return redirect("/")

    return render_template("register.html")


@app.route("/quiz/<int:quiz_id>")
@login_required
def quiz(quiz_id):
    user_id = session.get("user_id")
    db = get_db()
    cursor = db.cursor()

    # Verify quiz ownership & get title
    cursor.execute("SELECT title FROM quizes WHERE id = ? AND user_id = ?", (quiz_id, user_id))
    row = cursor.fetchone()
    if not row:
        db.close()
        return render_template("error.html", message="Quiz not found or access denied.")

    title = row["title"]

    # Get questions
    cursor.execute("""
        SELECT id, question, option_a, option_b, option_c, option_d
        FROM questions
        WHERE quiz_id = ?
    """, (quiz_id,))
    questions_raw = cursor.fetchall()
    db.close()

    questions = []
    for q in questions_raw:
        questions.append({
            "id": q["id"],
            "text": q["question"],
            "options": {
                "A": q["option_a"],
                "B": q["option_b"],
                "C": q["option_c"],
                "D": q["option_d"]
            }
        })

    return render_template("quiz.html", quiz={"title": title, "questions": questions})


@app.route("/results", methods=["POST"])
@login_required
def results():
    user_id = session.get("user_id")

    # The submitted form has q{question_id} = selected option
    # Get all question_ids from form keys starting with 'q'
    submitted_answers = {k: v for k, v in request.form.items() if k.startswith('q')}
    question_ids = [int(k[1:]) for k in submitted_answers.keys()]

    db = get_db()
    cursor = db.cursor()

    # Fetch correct answers for these question ids
    query = f"SELECT id, correct_option FROM questions WHERE id IN ({','.join(['?']*len(question_ids))})"
    cursor.execute(query, question_ids)
    correct_answers = {row["id"]: row["correct_option"] for row in cursor.fetchall()}

    score = 0
    total = len(question_ids)
    results = []

    for q_id in question_ids:
        user_answer = submitted_answers[f"q{q_id}"]
        correct_answer = correct_answers.get(q_id)

        is_correct = user_answer == correct_answer
        if is_correct:
            score += 1

        results.append({
            "question_id": q_id,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct
        })

    db.close()

    percent = (score / total) * 100 if total > 0 else 0

    return render_template("results.html", score=score, total=total, percent=percent, results=results)

@app.route("/remove_quiz/<int:quiz_id>", methods=["POST"])
@login_required
def remove_quiz(quiz_id):
    user_id = session.get("user_id")

    db = get_db()
    cursor = db.cursor()

    # Verify ownership
    cursor.execute("SELECT id FROM quizes WHERE id = ? AND user_id = ?", (quiz_id, user_id))
    quiz = cursor.fetchone()
    if not quiz:
        db.close()
        return render_template("error.html", message="Quiz not found or access denied.")

    # Delete questions first (foreign key constraints may require this)
    cursor.execute("DELETE FROM questions WHERE quiz_id = ?", (quiz_id,))
    # Delete the quiz itself
    cursor.execute("DELETE FROM quizes WHERE id = ?", (quiz_id,))

    db.commit()
    db.close()

    flash("Quiz deleted successfully.")
    return redirect("/")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")

        # For now, just show a success page or print to console
        print(f"Message from {name} ({email}): {message}")
        return render_template("contact.html", success=True)

    return render_template("contact.html", success=False)


@app.route("/about")
def about():
    return render_template("about.html")



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)