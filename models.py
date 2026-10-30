from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    favorites = db.relationship("Favorite", backref="user", cascade="all, delete-orphan", lazy=True)
    reviews = db.relationship("Review", backref="author", lazy=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Game(db.Model):
    __tablename__ = "games"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    min_players = db.Column(db.Integer, default=1)
    max_players = db.Column(db.Integer, default=4)
    min_age = db.Column(db.Integer, default=6)
    min_duration = db.Column(db.Integer, default=30)
    max_duration = db.Column(db.Integer, default=60)
    genre = db.Column(db.String(50))
    publisher = db.Column(db.String(100))
    year = db.Column(db.Integer)

    favorites = db.relationship("Favorite", backref="game", cascade="all, delete-orphan", lazy=True)
    reviews = db.relationship(
        "Review", backref="game", cascade="all, delete-orphan", lazy=True
    )
    store_links = db.relationship(
        "StoreLink", backref="game", cascade="all, delete-orphan", lazy=True
    )

    @property
    def avg_rating(self):
        if not self.reviews:
            return None
        return round(sum(r.rating for r in self.reviews) / len(self.reviews), 1)


class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)  # ← новое

    helpful_votes = db.relationship(  # ← новое
        "ReviewHelpful", backref="review", cascade="all, delete-orphan", lazy=True
    )

    __table_args__ = (
        db.UniqueConstraint("game_id", "user_id", name="unique_user_game_review"),
    )


class StoreLink(db.Model):
    __tablename__ = "store_links"
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    store_name = db.Column(db.String(50), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    price = db.Column(db.Integer)  # рубли, можно None


class ReviewHelpful(db.Model):                                      # ← новая модель
    __tablename__ = "review_helpful"
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("review_id", "user_id", name="unique_review_helpful"),
    )

class Favorite(db.Model):
    __tablename__ = "favorites"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("user_id", "game_id", name="unique_user_favorite"),
    )