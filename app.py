from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import json

# Create the Flask app
app = Flask(__name__)

# Get database URL from environment variable (set this on Render)
database_url = os.environ.get('DATABASE_URL', 'postgresql://localhost/cuet_test')
# Fix for Render's PostgreSQL URL format (sometimes needs adjustment)
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

# Configure the database connection
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the database
db = SQLAlchemy(app)

# ========== DATABASE MODELS (Tables) ==========

class Student(db.Model):
    """Stores student information"""
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to quiz attempts
    quiz_attempts = db.relationship('QuizAttempt', backref='student', lazy=True)

class Quiz(db.Model):
    """Stores quiz information"""
    __tablename__ = 'quizzes'
    
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer)  # Original ID from QSM
    quiz_name = db.Column(db.String(200))
    subject = db.Column(db.String(50))  # Physics, Chemistry, etc.
    test_type = db.Column(db.String(20))  # 'unit', 'revision', 'full_length'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship to attempts
    attempts = db.relationship('QuizAttempt', backref='quiz', lazy=True)

class QuizAttempt(db.Model):
    """Stores each time a student takes a quiz - THIS IS YOUR MAIN TABLE"""
    __tablename__ = 'quiz_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'))
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'))
    
    # Raw data from quiz
    total_questions = db.Column(db.Integer)
    total_correct = db.Column(db.Integer)
    total_score = db.Column(db.Float)
    time_taken_seconds = db.Column(db.Integer)
    answers_json = db.Column(db.Text)  # Store full answers as JSON
    
    # CALCULATED METRICS (these are what you'll display)
    accuracy_rate = db.Column(db.Float)  # (correct/attempted) * 100
    raw_score = db.Column(db.Float)       # Same as total_score probably
    attempt_rate = db.Column(db.Float)    # (attempted/total) * 100
    smart_attempt_rate = db.Column(db.Float)  # Your custom formula
    risk_ratio = db.Column(db.Float)      # Your custom formula
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ========== METRICS CALCULATION FUNCTIONS ==========

def calculate_metrics(quiz_data):
    """
    Calculate all student metrics from raw quiz data
    You can adjust these formulas based on exactly what CUET needs
    """
    
    total_q = quiz_data.get('total_questions', 0)
    total_correct = quiz_data.get('total_correct', 0)
    
    # Count how many questions were actually attempted
    # This requires looking at the answers array
    answers = quiz_data.get('answers', [])
    attempted_count = 0
    smart_attempts = 0
    
    for answer in answers:
        # Check if student submitted an answer (not blank)
        if answer.get('user_answer') and any(answer['user_answer']):
            attempted_count += 1
            
            # Define "smart attempt" - maybe questions where they spent >30 seconds?
            # Or questions they got correct? You define this!
            if answer.get('correct') == 'correct':
                smart_attempts += 1
    
    # Calculate metrics
    accuracy = (total_correct / attempted_count * 100) if attempted_count > 0 else 0
    attempt_rate = (attempted_count / total_q * 100) if total_q > 0 else 0
    smart_attempt_rate = (smart_attempts / total_q * 100) if total_q > 0 else 0
    
    # Risk ratio - you define this!
    # Example: (incorrect answers) / (total attempted)
    incorrect = attempted_count - total_correct
    risk_ratio = (incorrect / attempted_count) if attempted_count > 0 else 0
    
    return {
        'accuracy_rate': round(accuracy, 2),
        'raw_score': quiz_data.get('total_score', 0),
        'attempt_rate': round(attempt_rate, 2),
        'smart_attempt_rate': round(smart_attempt_rate, 2),
        'risk_ratio': round(risk_ratio, 2)
    }

# ========== API ENDPOINTS ==========

@app.route('/', methods=['GET'])
def home():
    """Simple home page to check if API is running"""
    return jsonify({
        'message': 'CUET Metrics Calculator API is running',
        'status': 'active'
    })

@app.route('/save-quiz-result', methods=['POST'])
def save_quiz_result():
    """
    This is the main endpoint that WordPress calls
    Receives quiz data, calculates metrics, saves to database
    """
    try:
        # Get the JSON data sent from WordPress
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        # Find or create student
        student = Student.query.filter_by(email=data.get('student_email')).first()
        if not student:
            student = Student(
                name=data.get('student_name'),
                email=data.get('student_email')
            )
            db.session.add(student)
            db.session.flush()  # Get student ID without committing yet
        
        # Find or create quiz
        quiz = Quiz.query.filter_by(quiz_id=data.get('quiz_id')).first()
        if not quiz:
            # You'll need to determine subject and test type
            # This could come from WordPress or you can add logic
            quiz = Quiz(
                quiz_id=data.get('quiz_id'),
                quiz_name=data.get('quiz_name'),
                subject='Unknown',  # You'll need to send this from WordPress
                test_type='Unknown'  # Or determine from quiz name
            )
            db.session.add(quiz)
            db.session.flush()
        
        # Calculate metrics
        metrics = calculate_metrics(data)
        
        # Create quiz attempt record
        attempt = QuizAttempt(
            student_id=student.id,
            quiz_id=quiz.id,
            total_questions=data.get('total_questions', 0),
            total_correct=data.get('total_correct', 0),
            total_score=data.get('total_score', 0),
            time_taken_seconds=data.get('time_taken', 0),
            answers_json=json.dumps(data.get('answers', [])),
            accuracy_rate=metrics['accuracy_rate'],
            raw_score=metrics['raw_score'],
            attempt_rate=metrics['attempt_rate'],
            smart_attempt_rate=metrics['smart_attempt_rate'],
            risk_ratio=metrics['risk_ratio']
        )
        
        db.session.add(attempt)
        db.session.commit()
        
        return jsonify({
            'message': 'Quiz results saved successfully',
            'attempt_id': attempt.id,
            'metrics': metrics
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/student-metrics/<email>', methods=['GET'])
def get_student_metrics(email):
    """
    Get all metrics for a specific student
    WordPress will call this to display data on the frontend
    """
    student = Student.query.filter_by(email=email).first()
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    
    # Get all quiz attempts for this student
    attempts = QuizAttempt.query.filter_by(student_id=student.id).all()
    
    # Calculate overall averages
    total_attempts = len(attempts)
    if total_attempts > 0:
        avg_accuracy = sum(a.accuracy_rate for a in attempts) / total_attempts
        avg_attempt_rate = sum(a.attempt_rate for a in attempts) / total_attempts
        avg_smart_rate = sum(a.smart_attempt_rate for a in attempts) / total_attempts
        avg_risk = sum(a.risk_ratio for a in attempts) / total_attempts
    else:
        avg_accuracy = avg_attempt_rate = avg_smart_rate = avg_risk = 0
    
    # Format the response
    result = {
        'student': {
            'name': student.name,
            'email': student.email
        },
        'overall_metrics': {
            'total_quizzes_taken': total_attempts,
            'average_accuracy': round(avg_accuracy, 2),
            'average_attempt_rate': round(avg_attempt_rate, 2),
            'average_smart_attempt_rate': round(avg_smart_rate, 2),
            'average_risk_ratio': round(avg_risk, 2)
        },
        'quiz_history': []
    }
    
    # Add each quiz attempt
    for a in attempts:
        quiz = Quiz.query.get(a.quiz_id)
        result['quiz_history'].append({
            'date': a.created_at.strftime('%Y-%m-%d %H:%M'),
            'quiz_name': quiz.quiz_name if quiz else 'Unknown',
            'subject': quiz.subject if quiz else 'Unknown',
            'test_type': quiz.test_type if quiz else 'Unknown',
            'accuracy': a.accuracy_rate,
            'raw_score': a.raw_score,
            'attempt_rate': a.attempt_rate,
            'smart_attempt_rate': a.smart_attempt_rate,
            'risk_ratio': a.risk_ratio,
            'total_questions': a.total_questions,
            'correct_answers': a.total_correct
        })
    
    return jsonify(result)

# ========== DATABASE CREATION ==========

# Create all tables if they don't exist
with app.app_context():
    db.create_all()
    print("✅ Database tables created/verified!")

# ========== RUN THE APP ==========
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)