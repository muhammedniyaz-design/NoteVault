"""
NoteVault - A SaaS-style personal note & document organizer.

Demonstrates:
- SaaS: multiple users register/login and use one shared hosted app via a browser,
  each with their own private data.
- PaaS: designed to be deployed to a Platform-as-a-Service (Render) which handles
  the server, OS, runtime, and scaling for us.
"""

import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# App & configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# Render/most PaaS platforms provide DATABASE_URL for a managed Postgres DB.
# Fall back to a local SQLite file for local development.
db_url = os.environ.get("DATABASE_URL", "sqlite:///notevault.db")
if db_url.startswith("postgres://"):  # SQLAlchemy needs postgresql://
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"

CATEGORIES = ["General", "Lecture Notes", "Assignments", "Ideas", "Reference"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    notes = db.relationship("Note", backref="author", lazy=True,
                             cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default="General")
    tags = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def tag_list(self):
        return [t.strip() for t in self.tags.split(",") if t.strip()]


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("That username is already taken.", "danger")
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Note (core app) routes
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    query = Note.query.filter_by(user_id=current_user.id)

    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(Note.title.ilike(like), Note.content.ilike(like), Note.tags.ilike(like))
        )
    if category:
        query = query.filter_by(category=category)

    notes = query.order_by(Note.updated_at.desc()).all()
    return render_template(
        "dashboard.html", notes=notes, categories=CATEGORIES,
        search=search, active_category=category
    )


@app.route("/note/new", methods=["GET", "POST"])
@login_required
def new_note():
    if request.method == "POST":
        note = Note(
            title=request.form.get("title", "").strip() or "Untitled",
            content=request.form.get("content", "").strip(),
            category=request.form.get("category", "General"),
            tags=request.form.get("tags", "").strip(),
            user_id=current_user.id,
        )
        db.session.add(note)
        db.session.commit()
        flash("Note created.", "success")
        return redirect(url_for("dashboard"))

    return render_template("note_form.html", note=None, categories=CATEGORIES)


@app.route("/note/<int:note_id>/edit", methods=["GET", "POST"])
@login_required
def edit_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        flash("You don't have access to that note.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        note.title = request.form.get("title", "").strip() or "Untitled"
        note.content = request.form.get("content", "").strip()
        note.category = request.form.get("category", "General")
        note.tags = request.form.get("tags", "").strip()
        db.session.commit()
        flash("Note updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template("note_form.html", note=note, categories=CATEGORIES)


@app.route("/note/<int:note_id>/delete", methods=["POST"])
@login_required
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id == current_user.id:
        db.session.delete(note)
        db.session.commit()
        flash("Note deleted.", "info")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Simple health check endpoint (handy for PaaS uptime checks)
# ---------------------------------------------------------------------------
@app.route("/healthz")
def healthz():
    return {"status": "ok"}


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
