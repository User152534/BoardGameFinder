import os
from urllib.parse import urlparse, urljoin

import click
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user,
)

from models import db, User, Game, Review, ReviewHelpful, Favorite, StoreLink

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

database_url = os.environ.get("DATABASE_URL", "sqlite:///boardgames.db")
# Railway/Heroku выдают postgres://, а SQLAlchemy ждёт postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Сначала войдите в аккаунт."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def is_safe_url(target: str) -> bool:
    """Защита от open redirect: пускаем только на свой же хост."""
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


# ---------- Каталог ----------

@app.route("/")
def index():
    query = Game.query

    players = request.args.get("players", type=int)
    if players:
        query = query.filter(Game.min_players <= players, Game.max_players >= players)

    duration = request.args.get("duration", type=int)
    if duration:
        query = query.filter(Game.max_duration <= duration)

    age = request.args.get("age", type=int)
    if age:
        query = query.filter(Game.min_age <= age)

    genre = request.args.get("genre")
    if genre:
        query = query.filter(Game.genre == genre)

    games = query.order_by(Game.title).all()
    genres = [
        g[0]
        for g in db.session.query(Game.genre)
        .distinct()
        .filter(Game.genre.isnot(None))
        .order_by(Game.genre)
        .all()
    ]

    favorite_ids = set()
    if current_user.is_authenticated:
        favorite_ids = {
            f.game_id for f in Favorite.query.filter_by(user_id=current_user.id).all()
        }

    return render_template(
        "index.html", games=games, genres=genres, favorite_ids=favorite_ids
    )

# ---------- Страница игры ----------

@app.route("/game/<int:game_id>")
def game_detail(game_id: int):
    game = db.get_or_404(Game, game_id)

    user_review = None
    if current_user.is_authenticated:
        user_review = Review.query.filter_by(
            game_id=game.id, user_id=current_user.id
        ).first()

    is_favorite = False
    if current_user.is_authenticated:
        is_favorite = (
            Favorite.query.filter_by(
                user_id=current_user.id, game_id=game.id
            ).first()
            is not None
        )

    sort = request.args.get("sort", "newest")
    reviews = list(game.reviews)

    if sort == "oldest":
        reviews.sort(key=lambda r: r.created_at)
    elif sort == "highest":
        reviews.sort(key=lambda r: (-r.rating, r.created_at))
    elif sort == "lowest":
        reviews.sort(key=lambda r: (r.rating, r.created_at))
    elif sort == "helpful":
        reviews.sort(key=lambda r: -len(r.helpful_votes))
    else:  # newest
        reviews.sort(key=lambda r: r.created_at, reverse=True)

    return render_template(
        "game.html",
        game=game,
        user_review=user_review,
        reviews=reviews,
        sort=sort,
        is_favorite=is_favorite,
    )


# ---------- Отзывы ----------

@app.route("/game/<int:game_id>/review", methods=["POST"])
@login_required
def add_review(game_id: int):
    game = db.get_or_404(Game, game_id)
    rating = request.form.get("rating", type=int)
    text = request.form.get("text", "").strip()

    if not rating or not (1 <= rating <= 5):
        flash("Поставьте оценку от 1 до 5.", "danger")
        return redirect(url_for("game_detail", game_id=game.id))

    if Review.query.filter_by(game_id=game.id, user_id=current_user.id).first():
        flash("Вы уже оставили отзыв к этой игре.", "warning")
        return redirect(url_for("game_detail", game_id=game.id))

    db.session.add(
        Review(game_id=game.id, user_id=current_user.id, rating=rating, text=text)
    )
    db.session.commit()
    flash("Спасибо за отзыв!", "success")
    return redirect(url_for("game_detail", game_id=game.id))


@app.route("/game/<int:game_id>/review/<int:review_id>/edit", methods=["POST"])
@login_required
def edit_review(game_id: int, review_id: int):
    review = db.get_or_404(Review, review_id)
    if review.game_id != game_id:
        abort(404)
    if review.user_id != current_user.id:
        abort(403)

    rating = request.form.get("rating", type=int)
    text = request.form.get("text", "").strip()

    if not rating or not (1 <= rating <= 5):
        flash("Поставьте оценку от 1 до 5.", "danger")
        return redirect(url_for("game_detail", game_id=game_id))

    review.rating = rating
    review.text = text or None
    db.session.commit()
    flash("Отзыв обновлён.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.route("/game/<int:game_id>/review/<int:review_id>/delete", methods=["POST"])
@login_required
def delete_review(game_id: int, review_id: int):
    review = db.get_or_404(Review, review_id)
    if review.game_id != game_id:
        abort(404)
    # Автор может удалить свой, админ — любой
    if review.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    db.session.delete(review)
    db.session.commit()
    flash("Отзыв удалён.", "info")
    return redirect(url_for("game_detail", game_id=game_id))


@app.route("/review/<int:review_id>/helpful", methods=["POST"])
@login_required
def toggle_helpful(review_id: int):
    review = db.get_or_404(Review, review_id)

    if review.user_id == current_user.id:
        flash("Нельзя голосовать за свой отзыв.", "warning")
        return redirect(url_for("game_detail", game_id=review.game_id))

    existing = ReviewHelpful.query.filter_by(
        review_id=review.id, user_id=current_user.id
    ).first()

    if existing:
        db.session.delete(existing)
        flash("Голос отменён.", "info")
    else:
        db.session.add(ReviewHelpful(review_id=review.id, user_id=current_user.id))
        flash("Спасибо за оценку!", "success")

    db.session.commit()
    return redirect(url_for("game_detail", game_id=review.game_id))


# ---------- Админка ----------

def _validate_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


@app.route("/game/<int:game_id>/edit", methods=["GET", "POST"])
@login_required
def edit_game(game_id: int):
    if not current_user.is_admin:
        abort(403)
    game = db.get_or_404(Game, game_id)

    if request.method == "POST":
        game.title = request.form["title"].strip()
        game.description = request.form.get("description", "").strip() or None
        game.image_url = request.form.get("image_url", "").strip() or None
        game.min_players = request.form.get("min_players", type=int) or 1
        game.max_players = request.form.get("max_players", type=int) or 1
        game.min_age = request.form.get("min_age", type=int) or 0
        game.min_duration = request.form.get("min_duration", type=int) or 0
        game.max_duration = request.form.get("max_duration", type=int) or 0
        game.genre = request.form.get("genre", "").strip() or None
        game.publisher = request.form.get("publisher", "").strip() or None
        game.year = request.form.get("year", type=int)

        db.session.commit()
        flash("Игра обновлена.", "success")
        return redirect(url_for("game_detail", game_id=game.id))

    return render_template("game_form.html", game=game)


@app.route("/game/add", methods=["GET", "POST"])
@login_required
def add_game():
    if not current_user.is_admin:
        abort(403)

    if request.method == "POST":
        game = Game(
            title=request.form["title"].strip(),
            description=request.form.get("description", "").strip() or None,
            image_url=request.form.get("image_url", "").strip() or None,
            min_players=request.form.get("min_players", type=int) or 1,
            max_players=request.form.get("max_players", type=int) or 1,
            min_age=request.form.get("min_age", type=int) or 0,
            min_duration=request.form.get("min_duration", type=int) or 0,
            max_duration=request.form.get("max_duration", type=int) or 0,
            genre=request.form.get("genre", "").strip() or None,
            publisher=request.form.get("publisher", "").strip() or None,
            year=request.form.get("year", type=int),
        )
        db.session.add(game)
        db.session.flush()  # чтобы получить game.id до commit

        # Собираем ссылки: три списка одинаковой длины
        names = request.form.getlist("store_name")
        urls = request.form.getlist("store_url")
        prices = request.form.getlist("store_price")

        for name, url, price in zip(names, urls, prices):
            name, url = name.strip(), url.strip()
            if not name or not url:
                continue
            if not _validate_url(url):
                flash(f"Ссылка «{name}» пропущена: URL должен начинаться с http:// или https://", "warning")
                continue
            db.session.add(StoreLink(
                game_id=game.id,
                store_name=name,
                url=url,
                price=int(price) if price.strip().isdigit() else None,
            ))

        db.session.commit()
        flash("Игра добавлена.", "success")
        return redirect(url_for("game_detail", game_id=game.id))

    return render_template("game_form.html", game=None)


# ---------- Авторизация ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or len(password) < 6:
            flash("Заполните все поля, пароль минимум 6 символов.", "danger")
            return render_template("register.html")

        if User.query.filter(
            (User.username == username) | (User.email == email)
        ).first():
            flash("Такое имя или email уже заняты.", "danger")
            return render_template("register.html")

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Регистрация успешна!", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Привет, {user.username}!", "success")
            next_page = request.args.get("next")
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for("index"))

        flash("Неверное имя или пароль.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли из аккаунта.", "info")
    return redirect(url_for("index"))


# ---------- Профиль ----------

@app.route("/profile")
@login_required
def profile():
    reviews = (
        Review.query.filter_by(user_id=current_user.id)
        .order_by(Review.created_at.desc())
        .all()
    )
    favorites = (
        Favorite.query.filter_by(user_id=current_user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    return render_template("profile.html", reviews=reviews, favorites=favorites)

# ---------- Избранное ----------

@app.route("/game/<int:game_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(game_id: int):
    game = db.get_or_404(Game, game_id)
    existing = Favorite.query.filter_by(
        user_id=current_user.id, game_id=game.id
    ).first()

    if existing:
        db.session.delete(existing)
        flash("Игра удалена из избранного.", "info")
    else:
        db.session.add(Favorite(user_id=current_user.id, game_id=game.id))
        flash("Игра добавлена в избранное.", "success")

    db.session.commit()

    # Возвращаем пользователя туда, откуда он нажал кнопку — с проверкой на свой же хост
    referrer = request.referrer
    if referrer and is_safe_url(referrer):
        return redirect(referrer)
    return redirect(url_for("game_detail", game_id=game.id))

# ---------- CLI-команды ----------

@app.cli.command("seed")
def seed():
    """Заполнить базу тестовыми играми: flask seed"""
    if Game.query.count():
        print("В базе уже есть игры — пропускаем.")
        return

    games = [
        Game(
            title="Каркассон", min_players=2, max_players=5, min_age=8,
            min_duration=30, max_duration=45, genre="Стратегия", year=2000,
            publisher="Hobby World",
            description="Классика о выкладывании тайлов и захвате территорий.",
        ),
        Game(
            title="Колонизаторы", min_players=3, max_players=4, min_age=10,
            min_duration=60, max_duration=120, genre="Стратегия", year=1995,
            publisher="Hobby World",
            description="Торгуйте, стройте, захватывайте остров.",
        ),
        Game(
            title="Манчкин", min_players=3, max_players=6, min_age=10,
            min_duration=60, max_duration=120, genre="Юмор", year=2001,
            publisher="Hobby World",
            description="Пародия на RPG: сражайтесь с монстрами и мешайте друзьям.",
        ),
        Game(
            title="Имаджинариум", min_players=4, max_players=7, min_age=12,
            min_duration=30, max_duration=60, genre="Вечериночная", year=2011,
            publisher="Cosmodrome Games",
            description="Ассоциативная игра с красивыми картинками.",
        ),
        Game(
            title="Пандемия", min_players=2, max_players=4, min_age=8,
            min_duration=45, max_duration=60, genre="Кооператив", year=2008,
            publisher="Hobby World",
            description="Спасите мир от эпидемий вместе с командой.",
        ),
    ]
    db.session.add_all(games)
    db.session.commit()
    print(f"Добавлено игр: {len(games)}")


@app.cli.command("create-admin")
@click.argument("username")
def create_admin(username):
    """Сделать пользователя админом: flask create-admin имя"""
    user = User.query.filter_by(username=username).first()
    if not user:
        print(f"Пользователь {username!r} не найден. Сначала зарегистрируйтесь.")
        return
    user.is_admin = True
    db.session.commit()
    print(f"{username} теперь админ.")


@app.route("/game/<int:game_id>/store-link/add", methods=["POST"])
@login_required
def add_store_link(game_id: int):
    if not current_user.is_admin:
        abort(403)
    game = db.get_or_404(Game, game_id)

    name = request.form.get("store_name", "").strip()
    url = request.form.get("store_url", "").strip()
    price_raw = request.form.get("store_price", "").strip()

    if not name or not url:
        flash("Укажите название магазина и ссылку.", "danger")
        return redirect(url_for("game_detail", game_id=game.id))
    if not _validate_url(url):
        flash("Ссылка должна начинаться с http:// или https://", "danger")
        return redirect(url_for("game_detail", game_id=game.id))

    db.session.add(StoreLink(
        game_id=game.id,
        store_name=name,
        url=url,
        price=int(price_raw) if price_raw.isdigit() else None,
    ))
    db.session.commit()
    flash("Ссылка добавлена.", "success")
    return redirect(url_for("game_detail", game_id=game.id))


@app.route("/game/<int:game_id>/store-link/<int:link_id>/delete", methods=["POST"])
@login_required
def delete_store_link(game_id: int, link_id: int):
    if not current_user.is_admin:
        abort(403)
    link = db.get_or_404(StoreLink, link_id)
    if link.game_id != game_id:
        abort(404)
    db.session.delete(link)
    db.session.commit()
    flash("Ссылка удалена.", "info")
    return redirect(url_for("game_detail", game_id=game_id))


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)