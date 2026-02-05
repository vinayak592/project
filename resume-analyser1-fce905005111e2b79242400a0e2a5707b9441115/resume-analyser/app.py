from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import pdfplumber
from difflib import SequenceMatcher
import json
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///resume_analyzer.db'
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    analyses = db.relationship('Analysis', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Analysis model
class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    skills_found = db.Column(db.Text, nullable=False)  # JSON string
    roles_scores = db.Column(db.Text, nullable=False)  # JSON string
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()


SKILLS = [
    "python", "java", "c", "c++", "html", "css", "javascript",
    "sql", "machine learning", "data science", "flask", "django"
]

JOB_ROLES = {
    "Software Developer": ["python", "java", "c++"],
    "Web Developer": ["html", "css", "javascript", "flask"],
    "Data Scientist": ["python", "machine learning", "data science", "sql"]
}

# Simple course recommendations per role (short list of suggestions)
COURSE_RECOMMENDATIONS = {
    "Software Developer": [
        {"title": "CS50's Introduction to Computer Science (edX)", "url": "https://cs50.harvard.edu"},
        {"title": "Algorithms and Data Structures (Coursera)", "url": "https://www.coursera.org"}
    ],
    "Web Developer": [
        {"title": "The Web Developer Bootcamp (Udemy)", "url": "https://www.udemy.com"},
        {"title": "Front-End Web Development with React (Coursera)", "url": "https://www.coursera.org"}
    ],
    "Data Scientist": [
        {"title": "IBM Data Science Professional Certificate (Coursera)", "url": "https://www.coursera.org"},
        {"title": "Machine Learning by Andrew Ng (Coursera)", "url": "https://www.coursera.org"}
    ]
}

def extract_text(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text
    return text.lower()

def compute_insights(skills_found, sorted_roles):
    """Compute comprehensive insights including gaps, scores, learning paths, etc."""
    insights = {}
    
    # 1. Resume Score (0-100)
    total_possible_skills = len(SKILLS)
    resume_score = int((len(skills_found) / total_possible_skills) * 100) if total_possible_skills > 0 else 0
    insights['resume_score'] = resume_score
    
    # 2. Skills Gap Analysis per role
    gaps = {}
    for role, req_skills in JOB_ROLES.items():
        missing = [s for s in req_skills if s not in skills_found]
        gaps[role] = {'missing': missing, 'count': len(missing)}
    insights['skill_gaps'] = gaps
    
    # 3. Strengths & Weaknesses
    insights['strengths'] = skills_found[:5] if skills_found else []
    most_common_missing = {}
    for role, req_skills in JOB_ROLES.items():
        for skill in req_skills:
            if skill not in skills_found:
                most_common_missing[skill] = most_common_missing.get(skill, 0) + 1
    insights['weaknesses'] = sorted(most_common_missing.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 4. Personalized Learning Path (top 3 roles)
    learning_paths = {}
    for role, score in sorted_roles[:3]:
        missing_skills = gaps.get(role, {}).get('missing', [])
        learning_paths[role] = {
            'steps': [f"Learn {s}" for s in missing_skills[:3]],
            'courses': COURSE_RECOMMENDATIONS.get(role, [])[:2]
        }
    insights['learning_paths'] = learning_paths
    
    # 5. Job Market Insights (trending/high-demand skills)
    skill_demand = {}
    for role, req_skills in JOB_ROLES.items():
        for skill in req_skills:
            skill_demand[skill] = skill_demand.get(skill, 0) + 1
    insights['trending_skills'] = sorted(skill_demand.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 6. Proficiency Levels (beginner/intermediate/advanced tracks)
    proficiency = {}
    for skill in skills_found:
        proficiency[skill] = 'Intermediate'
    insights['proficiency'] = proficiency
    
    # 7. Multiple Role Comparison summary
    role_comparison = []
    for role, score in sorted_roles:
        role_comparison.append({
            'role': role,
            'score': score,
            'gap_count': gaps.get(role, {}).get('count', 0)
        })
    insights['role_comparison'] = role_comparison
    
    # 8. Feedback & Recommendations
    if resume_score < 30:
        insights['feedback'] = "Your resume needs more skill keywords. Focus on learning foundational skills."
    elif resume_score < 60:
        insights['feedback'] = "Good progress! Build a portfolio with projects to strengthen your profile."
    elif resume_score < 80:
        insights['feedback'] = "Strong resume! Focus on specialization in your target role."
    else:
        insights['feedback'] = "Excellent! You have a well-rounded skill set. Keep learning advanced topics."
    
    return insights

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            return render_template('register.html', error='Username and password required')
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Username already exists')
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    analyses = Analysis.query.filter_by(user_id=current_user.id).all()
    return render_template('profile.html', user=current_user, analyses=analyses)

@app.route("/", methods=["GET", "POST"])
def index():
    skills_found = []
    role_scores = {}
    show_bars = False
    max_roles = "all"
    min_score = 0

    if request.method == "POST":
        file = request.files["resume"]
        max_roles = request.form.get("max_roles", "all")
        show_bars = request.form.get("show_bars") == 'on'
        try:
            min_score = int(request.form.get("min_score", "0"))
        except Exception:
            min_score = 0

        text = extract_text(file)

        for skill in SKILLS:
            if skill in text:
                skills_found.append(skill)

        for role, req_skills in JOB_ROLES.items():
            matched = len(set(skills_found) & set(req_skills))
            score = int((matched / len(req_skills)) * 100)
            role_scores[role] = score

        # apply minimum score filter
        role_scores = {r: s for r, s in role_scores.items() if s >= min_score}

        # sort and limit roles
        sorted_roles = sorted(role_scores.items(), key=lambda x: x[1], reverse=True)
        if max_roles == "top1":
            sorted_roles = sorted_roles[:1]
        elif max_roles == "top3":
            sorted_roles = sorted_roles[:3]
    else:
        sorted_roles = []

    # Prepare chart data
    role_labels = [r for r, s in sorted_roles]
    role_scores = [s for r, s in sorted_roles]

    # For skills chart show found skills (counts)
    skills_labels = skills_found
    skills_counts = [1 for _ in skills_found]

    roles_chart = {"labels": role_labels, "scores": role_scores}
    skills_chart = {"labels": skills_labels, "counts": skills_counts}

    # Compute comprehensive insights
    insights = {}
    if request.method == "POST":
        insights = compute_insights(skills_found, sorted_roles)

    # Store analysis per user if logged in
    if current_user.is_authenticated and request.method == "POST":
        analysis = Analysis(
            user_id=current_user.id,
            filename=file.filename,
            skills_found=json.dumps(skills_found),
            roles_scores=json.dumps(sorted_roles)
        )
        db.session.add(analysis)
        db.session.commit()
        # Store in session for charts page
        session['roles_chart'] = roles_chart
        session['skills_chart'] = skills_chart
        session['insights'] = insights

    return render_template("index.html", skills=skills_found, roles=sorted_roles, show_bars=show_bars, insights=insights)


@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    msg = (data.get('message') or '').strip()
    msg_lower = msg.lower()
    
    if not msg:
        reply = "Hello! Ask me anything about resumes, career advice, skills, job market insights, or how to improve your profile."
        return jsonify({'reply': reply})
    
    # Get context from session (current analysis if available)
    insights = session.get('insights', {})
    skills_found = session.get('skills_found', [])
    
    # ====== INTENT DETECTION & ANALYSIS ======
    
    # 1. Career goal / "How to become" questions
    career_keywords = ("become", "how to become", "want to be", "i want to be", "want to become", "how do i become", "path to", "career in")
    if any(kw in msg_lower for kw in career_keywords) or msg_lower.startswith('how to'):
        best_role = None
        best_score = 0.0
        for role in JOB_ROLES.keys():
            score = SequenceMatcher(None, role.lower(), msg_lower).ratio()
            if score > best_score:
                best_score = score
                best_role = role
        
        if not best_role or best_score < 0.35:
            for role in JOB_ROLES.keys():
                if role.lower() in msg_lower:
                    best_role = role
                    break
        
        if best_role:
            skills = JOB_ROLES.get(best_role, [])
            courses = COURSE_RECOMMENDATIONS.get(best_role, [])
            reply = f"🎯 Path to {best_role}:\n\nRequired skills: {', '.join(skills)}\n\n"
            reply += "📚 Learning roadmap:\n"
            reply += "1. Master fundamentals (start with " + skills[0].title() + ")\n"
            reply += "2. Build 2-3 portfolio projects\n"
            reply += "3. Learn industry best practices\n"
            reply += "4. Network and contribute to open source\n\n"
            
            if courses:
                reply += "Recommended courses:\n"
                for c in courses[:2]:
                    reply += f"• {c['title']}\n"
            
            return jsonify({'reply': reply})
        else:
            reply = "I can guide you on: Software Developer, Web Developer, or Data Scientist. Which role interests you?"
            return jsonify({'reply': reply})
    
    # 2. Resume analysis / What was detected
    analysis_keywords = ("detect", "skill", "skills", "found", "score", "resume analysis", "what", "my resume")
    if any(kw in msg_lower for kw in analysis_keywords):
        if insights:
            score = insights.get('resume_score', 0)
            reply = f"📄 Resume Analysis Summary:\n\n"
            reply += f"Resume Score: {score}%\n"
            reply += f"Skills detected: {len(skills_found)} total\n\n"
            
            if insights.get('strengths'):
                reply += "💪 Strengths: " + ", ".join(insights['strengths'][:3]) + "\n"
            if insights.get('weaknesses'):
                reply += "⚠️ Gaps: " + ", ".join(insights['weaknesses'][:3]) + "\n"
            
            reply += f"\nFeedback: {insights.get('feedback', 'Good resume structure.')}\n"
            return jsonify({'reply': reply})
        else:
            reply = "📄 No resume analyzed yet. Upload a PDF resume and click 'Analyze' to see detailed insights about your skills, score, and career matches!"
            return jsonify({'reply': reply})
    
    # 3. Job role matching
    role_keywords = ("role", "job", "match", "which role", "best role", "suitable", "fit")
    if any(kw in msg_lower for kw in role_keywords):
        if insights and insights.get('role_comparison'):
            reply = "🏆 Your Best Matches:\n\n"
            for role, score in list(insights['role_comparison'].items())[:3]:
                reply += f"• {role}: {score}% match\n"
            reply += "\nCheck 'Detailed Report' to see full role analysis!"
            return jsonify({'reply': reply})
        else:
            reply = "Upload your resume to see which job roles match your skills best!"
            return jsonify({'reply': reply})
    
    # 4. Skill gap / What to learn
    gap_keywords = ("gap", "learn", "missing", "improve", "need", "should i learn", "what to learn")
    if any(kw in msg_lower for kw in gap_keywords):
        if insights and insights.get('skill_gaps'):
            reply = "📈 Skill Development Path:\n\n"
            gaps_dict = insights['skill_gaps']
            if isinstance(gaps_dict, dict):
                for role, gaps in list(gaps_dict.items())[:2]:
                    if gaps:
                        reply += f"{role}:\n• Learn: {', '.join(gaps[:3])}\n\n"
            reply += "Check 'Learning Paths' in your report for courses!"
            return jsonify({'reply': reply})
        else:
            reply = "Upload and analyze a resume to get personalized skill recommendations!"
            return jsonify({'reply': reply})
    
    # 5. General career advice
    advice_keywords = ("advice", "help", "how do i", "tips", "improve", "better", "progress")
    if any(kw in msg_lower for kw in advice_keywords):
        reply = "💡 Career Advice:\n\n"
        reply += "✅ Build a strong portfolio (projects > grades)\n"
        reply += "✅ Contribute to open source\n"
        reply += "✅ Network on LinkedIn & GitHub\n"
        reply += "✅ Learn one skill deeply, then expand\n"
        reply += "✅ Get internships or freelance experience\n"
        reply += "✅ Keep your resume updated & concise\n\n"
        reply += "What specific area do you want help with?"
        return jsonify({'reply': reply})
    
    # 6. Market insights / Job market
    market_keywords = ("market", "demand", "trend", "popular", "future", "growing", "industry")
    if any(kw in msg_lower for kw in market_keywords):
        if insights and insights.get('trending_skills'):
            reply = "📊 Trending Skills & Market Insights:\n\n"
            reply += "🔥 Hot Skills Right Now:\n"
            for skill in insights['trending_skills'][:5]:
                reply += f"• {skill}\n"
            reply += "\n💼 Focus on these for better job prospects!"
            return jsonify({'reply': reply})
        else:
            reply = "Currently trending: Python, JavaScript, Cloud (AWS/Azure), Data Science, AI/ML, DevOps"
            return jsonify({'reply': reply})
    
    # 7. Learning paths / Courses
    learning_keywords = ("course", "learning", "study", "tutorial", "roadmap", "path")
    if any(kw in msg_lower for kw in learning_keywords):
        reply = "🎓 Learning Paths Available:\n\n"
        for role, courses in COURSE_RECOMMENDATIONS.items():
            reply += f"📚 {role}:\n"
            for course in courses[:1]:
                reply += f"• {course['title']}\n"
        reply += "\nCheck 'Learning Paths' in your Detailed Report!"
        return jsonify({'reply': reply})
    
    # 8. General fallback - comprehensive help
    reply = "🤖 I can help with:\n\n"
    reply += "📄 Resume Analysis - Ask 'What skills did you detect?'\n"
    reply += "🎯 Career Guidance - Ask 'How do I become a Data Scientist?'\n"
    reply += "📚 Learning - Ask 'What courses should I take?'\n"
    reply += "📊 Job Matches - Ask 'Which roles match my skills?'\n"
    reply += "📈 Skill Gaps - Ask 'What skills should I learn?'\n"
    reply += "💡 Tips - Ask 'How do I improve my career?'\n\n"
    reply += f"Your question: '{msg}' - Try being more specific!"
    
    return jsonify({'reply': reply})



@app.route('/dashboard')
@login_required
def dashboard():
    # Show user's analytics overview
    user_analyses = Analysis.query.filter_by(user_id=current_user.id).all()
    total_analyses = len(user_analyses)
    if user_analyses:
        latest = user_analyses[-1]
        try:
            roles = json.loads(latest.roles_scores) if isinstance(latest.roles_scores, str) else latest.roles_scores
            skills = json.loads(latest.skills_found) if isinstance(latest.skills_found, str) else latest.skills_found
            # Convert dict to list of tuples if needed
            if isinstance(skills, str):
                skills = []
            elif not isinstance(skills, list):
                skills = list(skills) if skills else []
            if isinstance(roles, dict):
                latest_roles = list(roles.items())
            else:
                latest_roles = roles if roles else []
        except Exception as e:
            roles = {}
            skills = []
            latest_roles = []
    else:
        roles = {}
        skills = []
        latest_roles = []
    return render_template('dashboard.html', total_analyses=total_analyses, latest_roles=latest_roles, latest_skills=skills)

@app.route('/skill-library')
@login_required
def skill_library():
    return render_template('skill_library.html', all_skills=SKILLS, job_roles=JOB_ROLES)

@app.route('/job-roles')
@login_required
def job_roles():
    return render_template('job_roles.html', job_roles=JOB_ROLES, course_recommendations=COURSE_RECOMMENDATIONS)

@app.route('/learning-resources')
@login_required
def learning_resources():
    return render_template('learning_resources.html', courses=COURSE_RECOMMENDATIONS)

@app.route('/career-tips')
@login_required
def career_tips():
    return render_template('career_tips.html')

@app.route('/linkedin-jobs')
@login_required
def linkedin_jobs():
    # Prepare job opportunities data with LinkedIn links
    job_opportunities = {
        "Software Developer": [
            {
                "title": "Python Developer",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=python%20developer"
            },
            {
                "title": "Java Developer", 
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=java%20developer"
            },
            {
                "title": "C++ Developer",
                "company": "Tech Companies", 
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=c%2B%2B%20developer"
            },
            {
                "title": "Full Stack Developer",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=full%20stack%20developer"
            }
        ],
        "Web Developer": [
            {
                "title": "Frontend Developer",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=frontend%20developer"
            },
            {
                "title": "HTML/CSS Developer",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=html%20css%20developer"
            },
            {
                "title": "JavaScript Developer",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=javascript%20developer"
            },
            {
                "title": "React Developer",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=react%20developer"
            }
        ],
        "Data Scientist": [
            {
                "title": "Data Scientist",
                "company": "Tech/Finance Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=data%20scientist"
            },
            {
                "title": "Machine Learning Engineer",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=machine%20learning%20engineer"
            },
            {
                "title": "Data Analyst",
                "company": "Tech/Business Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=data%20analyst"
            },
            {
                "title": "Python Data Scientist",
                "company": "Tech Companies",
                "location": "Remote/Worldwide",
                "linkedin_search": "https://www.linkedin.com/jobs/search/?keywords=python%20data%20scientist"
            }
        ]
    }
    
    return render_template('linkedin_jobs.html', job_opportunities=job_opportunities, job_roles=JOB_ROLES)


@app.route('/interview-prep')
@login_required
def interview_prep():
    return render_template('interview_prep.html')

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html', username=current_user.username)

@app.route('/help')
@login_required
def help():
    return render_template('help.html')

@app.route('/charts')
@login_required
def charts():
    # Serve the last analysis from session
    roles_chart = session.get('roles_chart')
    skills_chart = session.get('skills_chart')
    return render_template('charts.html', roles_chart=roles_chart, skills_chart=skills_chart)

@app.route('/report')
@login_required
def report():
    insights = session.get('insights', {})
    return render_template('report.html', insights=insights)

@app.route('/download-report')
@login_required
def download_report():
    """Generate and download PDF report"""
    insights = session.get('insights', {})
    if not insights:
        return redirect(url_for('index'))
    
    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#0b3b6f'),
        spaceAfter=12,
        alignment=1
    )
    story.append(Paragraph('Resume Analysis Report', title_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Resume Score
    score_text = f"<b>Your Resume Score: {insights.get('resume_score', 0)}%</b>"
    story.append(Paragraph(score_text, styles['Heading2']))
    story.append(Paragraph(insights.get('feedback', ''), styles['Normal']))
    story.append(Spacer(1, 0.2*inch))
    
    # Strengths
    story.append(Paragraph('<b>Your Strengths:</b>', styles['Heading3']))
    strengths = insights.get('strengths', [])[:5]
    for skill in strengths:
        story.append(Paragraph(f"• {skill}", styles['Normal']))
    story.append(Spacer(1, 0.2*inch))
    
    # Weaknesses
    story.append(Paragraph('<b>Common Skill Gaps:</b>', styles['Heading3']))
    weaknesses = insights.get('weaknesses', [])[:5]
    for skill, count in weaknesses:
        story.append(Paragraph(f"• {skill} (needed in {count} role(s))", styles['Normal']))
    story.append(Spacer(1, 0.2*inch))
    
    # High-demand skills
    story.append(Paragraph('<b>High-Demand Skills to Learn:</b>', styles['Heading3']))
    trending = insights.get('trending_skills', [])[:5]
    for skill, demand in trending:
        story.append(Paragraph(f"• {skill} (in {demand} role(s))", styles['Normal']))
    story.append(Spacer(1, 0.2*inch))
    
    # Role Comparison
    story.append(Paragraph('<b>Role Comparison:</b>', styles['Heading3']))
    for comp in insights.get('role_comparison', []):
        story.append(Paragraph(f"• {comp['role']}: {comp['score']}% match | {comp['gap_count']} gaps", styles['Normal']))
    story.append(Spacer(1, 0.2*inch))
    
    # Learning Paths
    story.append(PageBreak())
    story.append(Paragraph('<b>Personalized Learning Paths:</b>', styles['Heading3']))
    for role, path_info in insights.get('learning_paths', {}).items():
        story.append(Paragraph(f"<b>Path to become a {role}:</b>", styles['Heading4']))
        for step in path_info.get('steps', []):
            story.append(Paragraph(f"• {step}", styles['Normal']))
        if path_info.get('courses'):
            story.append(Paragraph("<b>Recommended Courses:</b>", styles['Normal']))
            for course in path_info['courses']:
                story.append(Paragraph(f"• {course['title']}", styles['Normal']))
        story.append(Spacer(1, 0.1*inch))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='resume_analysis_report.pdf'
    )




if __name__ == '__main__':
    app.run(debug=True)
