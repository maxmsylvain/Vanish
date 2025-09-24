from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
import os
import requests
import feedparser
from bs4 import BeautifulSoup
import random
import time
from werkzeug.utils import secure_filename
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import TypeDecorator, DateTime

app = Flask(__name__)
app.config.from_object('config.Config')

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class TimezoneUTC(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("created_at must be timezone-aware")
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value

followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('users.id'), primary_key=True)
)
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    profile_pic = db.Column(db.String(200), default='default.jpg')
    bio = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    posts = db.relationship('Post', backref='author', lazy=True, cascade="all, delete-orphan")
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')
    def __repr__(self):
        return f"User('{self.username}', '{self.email}')"
    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)
            return self
    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)
            return self
    def is_following(self, user):
        return self.followed.filter(
            followers.c.followed_id == user.id).count() > 0
    def followed_posts(self):
        followed = Post.query.join(
            followers, (followers.c.followed_id == Post.user_id)
        ).filter(followers.c.follower_id == self.id)
        own = Post.query.filter_by(user_id=self.id)
        return followed.union(own).order_by(Post.created_at.desc())

class Post(db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(TimezoneUTC, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    post_type = db.Column(db.String(20), default='user', nullable=False)  
    source_url = db.Column(db.String(500), nullable=True)  
    replies = db.relationship('Post', 
                             backref=db.backref('parent', remote_side=[id]),
                             lazy='dynamic',
                             cascade="all, delete-orphan")

    remaining_time = None

    def __repr__(self):
        return f"Post('{self.content[:20]}...', '{self.created_at}')"

    @hybrid_property
    def created_at_utc(self):
        return self.created_at
    @property
    def is_reply(self):
        return self.parent_id is not None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

scheduler = BackgroundScheduler(daemon=True)
scheduler.start()

def delete_expired_posts():
    expiration_time = datetime.now(timezone.utc) - timedelta(hours=3)
    expired_posts = Post.query.filter(Post.created_at < expiration_time).all()
    for post in expired_posts:
        db.session.delete(post)
    db.session.commit()


scheduler.add_job(delete_expired_posts, 'interval', minutes=10)

NEWS_SOURCES = {
    'general': [
        {
            'name': 'BBC News',
            'rss_url': 'http://feeds.bbci.co.uk/news/rss.xml',
            'category': 'general'
        },
        {
            'name': 'Reuters',
            'rss_url': 'https://feeds.reuters.com/reuters/topNews',
            'category': 'general'
        },
        {
            'name': 'CNN',
            'rss_url': 'http://rss.cnn.com/rss/edition.rss',
            'category': 'general'
        },
        {
            'name': 'NPR News',
            'rss_url': 'https://feeds.npr.org/1001/rss.xml',
            'category': 'general'
        },
        {
            'name': 'AP News',
            'rss_url': 'https://feeds.apnews.com/rss/apf-topnews',
            'category': 'general'
        },
        {
            'name': 'Google News',
            'rss_url': 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en',
            'category': 'general'
        }
    ],
    'financial': [
        {
            'name': 'Financial Times',
            'rss_url': 'https://www.ft.com/rss/home',
            'category': 'financial'
        },
        {
            'name': 'Bloomberg',
            'rss_url': 'https://feeds.bloomberg.com/markets/news.rss',
            'category': 'financial'
        },
        {
            'name': 'MarketWatch',
            'rss_url': 'https://feeds.marketwatch.com/marketwatch/marketpulse/',
            'category': 'financial'
        },
        {
            'name': 'Yahoo Finance',
            'rss_url': 'https://feeds.finance.yahoo.com/rss/2.0/headline',
            'category': 'financial'
        },
        {
            'name': 'CNBC',
            'rss_url': 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114',
            'category': 'financial'
        },
        {
            'name': 'Wall Street Journal',
            'rss_url': 'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
            'category': 'financial'
        }
    ],
    'political': [
        {
            'name': 'Politico',
            'rss_url': 'https://www.politico.com/rss/politicopicks.xml',
            'category': 'political'
        },
        {
            'name': 'The Hill',
            'rss_url': 'https://thehill.com/rss/syndicator/19110',
            'category': 'political'
        },
        {
            'name': 'Axios',
            'rss_url': 'https://api.axios.com/feeds/axios-all.xml',
            'category': 'political'
        },
        {
            'name': 'Roll Call',
            'rss_url': 'https://www.rollcall.com/feed/',
            'category': 'political'
        },
        {
            'name': 'Real Clear Politics',
            'rss_url': 'https://www.realclearpolitics.com/RSS.xml',
            'category': 'political'
        },
        {
            'name': 'Washington Post Politics',
            'rss_url': 'https://feeds.washingtonpost.com/rss/politics',
            'category': 'political'
        }
    ]
}

def get_or_create_bot_users():
    bots = {}
    bot_configs = {
        'general': {
            'username': 'news_bot',
            'email': 'news_bot@vanish.com',
            'bio': '📰 General News Bot - Bringing you the latest headlines from around the world',
            'profile_pic': 'images/profile_pics/news_bot.png'
        },
        'financial': {
            'username': 'finance_bot',
            'email': 'finance_bot@vanish.com',
            'bio': '💰 Finance Bot - Market updates, business news, and economic insights',
            'profile_pic': 'images/profile_pics/finance_bot.png'
        },
        'political': {
            'username': 'politics_bot',
            'email': 'politics_bot@vanish.com',
            'bio': '🏛️ Politics Bot - Political news, policy updates, and government insights',
            'profile_pic': 'images/profile_pics/politics_bot.png'
        }
    }
    for bot_type, config in bot_configs.items():
        bot_user = User.query.filter_by(username=config['username']).first()
        if not bot_user:
            bot_user = User(
                username=config['username'],
                email=config['email'],
                password=generate_password_hash('bot_password_123'),
                bio=config['bio'],
                profile_pic=config['profile_pic']
            )
            db.session.add(bot_user)
        else:
            if bot_user.profile_pic != config['profile_pic']:
                bot_user.profile_pic = config['profile_pic']
        bots[bot_type] = bot_user
    db.session.commit()
    return bots

def manage_bot_posts(bot_user, max_posts=5):
    current_posts = Post.query.filter(
        Post.user_id == bot_user.id,
        Post.post_type == 'bot',
        Post.created_at > datetime.now(timezone.utc) - timedelta(minutes=15)  
    ).count()
    if current_posts >= max_posts:
        oldest_post = Post.query.filter(
            Post.user_id == bot_user.id,
            Post.post_type == 'bot',
            Post.created_at > datetime.now(timezone.utc) - timedelta(minutes=15)
        ).order_by(Post.created_at.asc()).first()
        if oldest_post:
            db.session.delete(oldest_post)
            db.session.commit()

def scrape_news_for_bot(bot_type, bot_user):
    try:
        sources = NEWS_SOURCES.get(bot_type, [])
        if not sources:
            return
        source = random.choice(sources)
        feed = feedparser.parse(source['rss_url'])
        if not feed.entries:
            return
        recent_articles = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=3)
        for entry in feed.entries[:30]:
            published_date = None
            try:
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'created_parsed') and entry.created_parsed:
                    published_date = datetime(*entry.created_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'published') and entry.published:
                    try:
                        from dateutil import parser
                        published_date = parser.parse(entry.published).replace(tzinfo=timezone.utc)
                    except:
                        pass
            except Exception as e:
                continue
            if published_date and published_date >= cutoff_date:
                recent_articles.append(entry)
        if not recent_articles:
            return
        article = random.choice(recent_articles)
        title = article.get('title', 'No title')
        summary = article.get('summary', '')
        link = article.get('link', '')
        if summary:
            soup = BeautifulSoup(summary, 'html.parser')
            summary = soup.get_text()[:200]
        emoji_map = {
            'general': '📰',
            'financial': '💰',
            'political': '🏛️'
        }
        emoji = emoji_map.get(bot_type, '📰')
        post_content = f"{emoji} {title}\n\n"
        if summary:
            post_content += f"{summary}\n\n"
        post_content += f"Source: {source['name']}"
        recent_posts = Post.query.filter(
            Post.user_id == bot_user.id,
            Post.post_type == 'bot',
            Post.created_at > datetime.now(timezone.utc) - timedelta(hours=1),
            Post.content.like(f'%{title[:50]}%')
        ).first()
        if recent_posts:
            return
        manage_bot_posts(bot_user, max_posts=5)
        new_post = Post(
            content=post_content,
            user_id=bot_user.id,
            post_type='bot',
            source_url=link
        )
        db.session.add(new_post)
        db.session.commit()
    except Exception as e:
        pass

def scrape_news():
    try:
        with app.app_context():
            bots = get_or_create_bot_users()
            bot_types = list(bots.keys())
            selected_bot_type = random.choice(bot_types)
            selected_bot = bots[selected_bot_type]
            scrape_news_for_bot(selected_bot_type, selected_bot)
    except Exception as e:
        pass

scheduler.add_job(scrape_news, 'interval', seconds=30, id='news_scraper')

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    return render_template('index.html', now=datetime.now(timezone.utc))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists')
            return redirect(url_for('register'))
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already registered')
            return redirect(url_for('register'))
        new_user = User(username=username, email=email, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    return render_template('register.html', now=datetime.now(timezone.utc))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('feed'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/post', methods=['POST'])
@login_required
def create_post():
    content = request.form.get('content')
    parent_id = request.form.get('parent_id')
    if not content:
        flash('Post cannot be empty')
        return redirect(url_for('feed'))
    new_post = Post(
        content=content, 
        user_id=current_user.id,
        parent_id=parent_id if parent_id else None,
        post_type='user'
    )
    db.session.add(new_post)
    db.session.commit()
    if parent_id:
        return redirect(url_for('feed') + f'#post-{parent_id}')
    else:
        return redirect(url_for('feed'))
@app.route('/api/post/<int:post_id>/replies')
@login_required
def get_post_replies(post_id):
    post = Post.query.get_or_404(post_id)
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=3)
    replies = Post.query.filter(
        Post.parent_id == post_id,
        Post.created_at > cutoff
    ).order_by(Post.created_at.asc()).all()
    replies_data = []
    for reply in replies:
        if reply.post_type == 'bot':
            expiration_time = reply.created_at + timedelta(minutes=15)
        else:
            expiration_time = reply.created_at + timedelta(hours=3)
        remaining_seconds = (expiration_time - now_utc).total_seconds()
        reply_data = {
            'id': reply.id,
            'content': reply.content,
            'author': {
                'username': reply.author.username,
                'profile_pic': reply.author.profile_pic
            },
            'created_at': reply.created_at.strftime('%H:%M'),
            'remaining_seconds': max(0, remaining_seconds)
        }
        replies_data.append(reply_data)
    return jsonify({'replies': replies_data})

@app.route('/profile/<username>')
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    now_utc = datetime.now(timezone.utc)
    cutoff_user = now_utc - timedelta(hours=3)
    cutoff_bot = now_utc - timedelta(minutes=15)
    posts = Post.query.filter(
        Post.user_id == user.id,
        ((Post.post_type == 'user') & (Post.created_at > cutoff_user)) |
        ((Post.post_type == 'bot') & (Post.created_at > cutoff_bot))
    ).order_by(Post.created_at.desc()).all()
    for post in posts:
        if post.post_type == 'bot':
            expiration_time = post.created_at + timedelta(minutes=15)
        else:
            expiration_time = post.created_at + timedelta(hours=3)
        remaining_seconds = (expiration_time - now_utc).total_seconds()
        post.remaining_time = max(0, remaining_seconds)
    return render_template('profile.html', user=user, posts=posts)

@app.route('/edit_profile', methods=['POST'])
@login_required
def edit_profile():
    bio = request.form.get('bio')
    profile_pic = request.files.get('profile_pic')
    user = User.query.get(current_user.id)

    if not user:
        flash('Error: User not found.', 'error')
        return redirect(url_for('profile', username=current_user.username))

    user.bio = bio

    if profile_pic:
        if allowed_file(profile_pic.filename):
            filename = secure_filename(profile_pic.filename)
            file_extension = filename.rsplit('.', 1)[1].lower()
            new_filename = f"{current_user.username}_profile.{file_extension}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)

            try:
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                profile_pic.save(filepath)
                user.profile_pic = f'images/profile_pics/{new_filename}'
            except Exception as e:
                flash(f'Error saving profile picture: {e}', 'error')
                print(f"Error saving profile picture: {e}")
                return redirect(url_for('profile', username=current_user.username))
        else:
            flash('Invalid file type for profile picture. Allowed types are: png, jpg, jpeg, gif', 'warning')
            print('Error: Invalid file type.')
    else:
        print("No profile picture was uploaded.")

    db.session.commit()
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('profile', username=current_user.username))

@app.route('/api/post/<int:post_id>/remaining')
def get_remaining_time(post_id):
    post = Post.query.get_or_404(post_id)
    now_utc = datetime.now(timezone.utc)
    if post.post_type == 'bot':
        expiration_time = post.created_at + timedelta(minutes=15)
    else:
        expiration_time = post.created_at + timedelta(hours=3)
    remaining_seconds = (expiration_time - now_utc).total_seconds()
    return jsonify({'remaining_seconds': max(0, remaining_seconds)})
@app.route('/follow/<username>')
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user == current_user:
        flash('You cannot follow yourself!')
        return redirect(url_for('profile', username=username))
    current_user.follow(user)
    db.session.commit()
    flash(f'You are now following {username}!')
    return redirect(url_for('profile', username=username))

@app.route('/unfollow/<username>')
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user == current_user:
        flash('You cannot unfollow yourself!')
        return redirect(url_for('profile', username=username))
    current_user.unfollow(user)
    db.session.commit()
    flash(f'You have unfollowed {username}.')
    return redirect(url_for('profile', username=username))

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    if not query:
        return render_template('search.html', query='', users=[], posts=[])
    users = User.query.filter(User.username.ilike(f'%{query}%')).limit(10).all()
    now_utc = datetime.now(timezone.utc)
    cutoff_user = now_utc - timedelta(hours=3)
    cutoff_bot = now_utc - timedelta(minutes=15)
    posts = Post.query.filter(
        Post.content.ilike(f'%{query}%'),
        ((Post.post_type == 'user') & (Post.created_at > cutoff_user)) |
        ((Post.post_type == 'bot') & (Post.created_at > cutoff_bot))
    ).order_by(Post.created_at.desc()).limit(20).all()
    for post in posts:
        if post.post_type == 'bot':
            expiration_time = post.created_at + timedelta(minutes=15)
        else:
            expiration_time = post.created_at + timedelta(hours=3)
        remaining_seconds = (expiration_time - now_utc).total_seconds()
        post.remaining_time = max(0, remaining_seconds)
    return render_template('search.html', query=query, users=users, posts=posts)

@app.route('/feed/followed')
@login_required
def followed_feed():
    now_utc = datetime.now(timezone.utc)
    cutoff_user = now_utc - timedelta(hours=3)
    cutoff_bot = now_utc - timedelta(minutes=15)
    posts = current_user.followed_posts().filter(
        ((Post.post_type == 'user') & (Post.created_at > cutoff_user)) |
        ((Post.post_type == 'bot') & (Post.created_at > cutoff_bot))
    ).all()
    for post in posts:
        if post.post_type == 'bot':
            expiration_time = post.created_at + timedelta(minutes=15)
        else:
            expiration_time = post.created_at + timedelta(hours=3)
        remaining_seconds = (expiration_time - now_utc).total_seconds()
        post.remaining_time = max(0, remaining_seconds)
    return render_template('feed.html', posts=posts, feed_type='followed')

@app.route('/feed')
@login_required
def feed():
    feed_type = request.args.get('type', 'all')
    now_utc = datetime.now(timezone.utc)
    cutoff_user = now_utc - timedelta(hours=3)
    cutoff_bot = now_utc - timedelta(minutes=15)
    if feed_type == 'followed':
        posts = current_user.followed_posts().filter(
            ((Post.post_type == 'user') & (Post.created_at > cutoff_user)) |
            ((Post.post_type == 'bot') & (Post.created_at > cutoff_bot))
        ).all()
    else:
        posts = Post.query.filter(
            ((Post.post_type == 'user') & (Post.created_at > cutoff_user)) |
            ((Post.post_type == 'bot') & (Post.created_at > cutoff_bot))
        ).order_by(Post.created_at.desc()).all()
    for post in posts:
        if post.post_type == 'bot':
            expiration_time = post.created_at + timedelta(minutes=15)
        else:
            expiration_time = post.created_at + timedelta(hours=3)
        remaining_seconds = (expiration_time - now_utc).total_seconds()
        post.remaining_time = max(0, remaining_seconds)
    return render_template('feed.html', posts=posts, feed_type=feed_type)

@app.route('/api/user/<int:user_id>/followers-count')
@login_required
def get_followers_count(user_id):
    user = User.query.get_or_404(user_id)
    followers_count = user.followers.count()
    following_count = user.followed.count()
    is_following = current_user.is_following(user) if current_user.is_authenticated else False
    return jsonify({
        'followers_count': followers_count,
        'following_count': following_count,
        'is_following': is_following
    })

@app.route('/test-news-bot')
def test_news_bot():
    try:
        scrape_news()
        return jsonify({'status': 'success', 'message': 'News scraping triggered for all bots'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/test-bot/<bot_type>')
def test_specific_bot(bot_type):
    try:
        with app.app_context():
            bots = get_or_create_bot_users()
            if bot_type not in bots:
                return jsonify({'status': 'error', 'message': f'Unknown bot type: {bot_type}'})
            bot_user = bots[bot_type]
            scrape_news_for_bot(bot_type, bot_user)
            return jsonify({'status': 'success', 'message': f'News scraping triggered for {bot_user.username}'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/scheduler-status')
def scheduler_status():
    jobs = scheduler.get_jobs()
    return jsonify({
        'scheduler_running': scheduler.running,
        'jobs': [{'id': job.id, 'next_run': str(job.next_run_time)} for job in jobs]
    })
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)