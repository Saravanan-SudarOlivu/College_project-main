from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Database Configuration
# Use environment variable or default to a local postgres connection
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/s4learnhub')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'max_overflow': 20,
    'pool_recycle': 1800,
    'pool_pre_ping': True
}

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Database Models
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='student')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'role': self.role
        }

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'receiver_id': self.receiver_id,
            'content': self.content,
            'timestamp': self.timestamp.isoformat(),
            'read': self.is_read
        }

# Create tables if they don't exist
with app.app_context():
    try:
        db.create_all()
        print("Database tables created successfully.")
    except Exception as e:
        print(f"Error creating database tables: {e}")

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            user = User.query.filter_by(email=email).first()
            
            if user and check_password_hash(user.password_hash, password):
                session['user_id'] = user.id
                session['user_name'] = user.name
                session['user_role'] = user.role
                return redirect(url_for('dashboard'))
            
            return render_template('login.html', error='Invalid credentials')
        except Exception as e:
            return render_template('login.html', error='Database connection error')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = request.form.get('role', 'student')
        
        if password != confirm_password:
            return render_template('signup.html', error='Passwords do not match')
        
        try:
            if User.query.filter_by(email=email).first():
                return render_template('signup.html', error='Email already registered')
            
            new_user = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                role=role
            )
            
            db.session.add(new_user)
            db.session.commit()
            
            session['user_id'] = new_user.id
            session['user_name'] = new_user.name
            session['user_role'] = new_user.role
            
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            return render_template('signup.html', error=f'Registration failed: {str(e)}')
    
    return render_template('signup.html')

@app.route('/index')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user_name=session.get('user_name'))

@app.route('/unauthorized')
def unauthorized():
    return render_template('unauthorized.html')

@app.route('/video')
def video():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('video.html', user_name=session.get('user_name'))

@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        current_user = User.query.get(session['user_id'])
        if not current_user:
            session.clear()
            return redirect(url_for('login'))
            
        user_data = current_user.to_dict()
        
        # Get other users for contact list
        other_users = User.query.filter(User.id != session['user_id']).all()
        other_users_data = [u.to_dict() for u in other_users]
        
        return render_template('chat.html', user=user_data, users=other_users_data)
    except Exception as e:
        return f"Error loading chat: {str(e)}"

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            return redirect(url_for('login'))
        
        return render_template('profile.html', user=user)
    except Exception as e:
        return f"Error loading profile: {str(e)}"

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        name = request.form.get('name')
        email = request.form.get('email')
        
        if name:
            user.name = name
            session['user_name'] = name
        
        if email and email != user.email:
            if User.query.filter(User.email == email, User.id != user.id).first():
                return jsonify({'error': 'Email already in use'}), 400
            user.email = email
        
        db.session.commit()
        return jsonify({'message': 'Profile updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        join_room(str(session['user_id']))
        emit('user_online', {
            'user_id': session['user_id'],
            'user_name': session['user_name']
        }, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        leave_room(str(session['user_id']))
        emit('user_offline', {
            'user_id': session['user_id'],
            'user_name': session['user_name']
        }, broadcast=True)

@socketio.on('send_message')
def handle_send_message(data):
    if 'user_id' not in session:
        return
    
    receiver_id = data.get('receiver_id')
    content = data.get('content')
    
    if not receiver_id or not content:
        return
    
    try:
        new_message = Message(
            sender_id=session['user_id'],
            receiver_id=receiver_id,
            content=content
        )
        
        db.session.add(new_message)
        db.session.commit()
        
        message_data = new_message.to_dict()
        message_data['sender_name'] = session['user_name'] # Add sender name for UI convenience
        
        # Send to receiver
        emit('receive_message', message_data, room=str(receiver_id))
        
        # Send confirmation to sender
        emit('message_sent', {'message_id': new_message.id}, room=str(session['user_id']))
    except Exception as e:
        print(f"Error sending message: {e}")
        db.session.rollback()

@socketio.on('typing')
def handle_typing(data):
    receiver_id = data.get('receiver_id')
    if receiver_id:
        emit('user_typing', {
            'user_id': session['user_id'],
            'user_name': session['user_name']
        }, room=str(receiver_id))

@socketio.on('stop_typing')
def handle_stop_typing(data):
    receiver_id = data.get('receiver_id')
    if receiver_id:
        emit('user_stop_typing', {
            'user_id': session['user_id']
        }, room=str(receiver_id))

@socketio.on('get_messages')
def handle_get_messages(data):
    if 'user_id' not in session:
        return
    
    try:
        other_user_id = data.get('user_id')
        current_user_id = session['user_id']
        
        # Get messages between these two users
        messages = Message.query.filter(
            ((Message.sender_id == current_user_id) & (Message.receiver_id == other_user_id)) |
            ((Message.sender_id == other_user_id) & (Message.receiver_id == current_user_id))
        ).order_by(Message.timestamp.asc()).all()
        
        conversation_messages = []
        for msg in messages:
            msg_dict = msg.to_dict()
            # Mark as read if I am the receiver
            if msg.receiver_id == current_user_id and not msg.is_read:
                msg.is_read = True
            conversation_messages.append(msg_dict)
            
        db.session.commit()
        
        emit('load_messages', {'messages': conversation_messages})
    except Exception as e:
        print(f"Error loading messages: {e}")

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
